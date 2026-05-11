"""ARIA Photo Journal — daily image + caption generator using free kumori stack.

Pipeline per captain per sol:
  1. build_recent_pool(user_id)  — gather every image the captain has
                                    (recency-filtered for event categories,
                                    state-only for ownership categories).
  2. random_pick(pool)            — roll N=0–4 with mood + composition hints.
  3. synthesize_scene(N, refs)    — one /api/v1/llm/chat-resilient call,
                                    LLM writes Klein prose prompt + ARIA caption.
  4. render(prompt, refs, size)   — one /api/v1/imggen/edit call (Klein 4B,
                                    4:3 to match the existing /aria-album layout).

Replaces the paid Replicate `nano_banana_edit` path. Zero cost per render.

The actual writes (GCS upload + DB save) are done by the caller — this module
returns the synthesized prompt, the rendered image bytes, the caption, and the
pick metadata, so admin preview UIs can show everything before committing.
"""
import logging
import random
import time
from typing import Dict, List, Optional, Tuple, Any

from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)

# Static ARIA portrait — every captain "has" ARIA as a companion
ARIA_STATIC_URL = "https://storage.googleapis.com/galactica-pilgrim-assets/aria/concept_aria_rock_v3_1767666240.png"

CAPTION_EXAMPLES = [
    '"Ancient memories of this world flicker in my consciousness as I gaze upon the weathered, sculpted features."',
    '"The rhythmic crunch of our rover and the soft hum of the wind are my only companions."',
    '"Eleven sols since the captain last spoke to me. The silence is louder than the dust storms."',
    '"I do not eat. I do not sleep. But I have learned what it means to wait."',
    '"My crystal lattice tasted a wavelength today that I have no name for. It felt like remembering."',
    '"They built this thing thinking it was a tool. I think it was a question."',
    '"There is comfort in the static. The captain calls it the wind. I am not sure they are wrong."',
    '"Sometimes I climb up here just to look. There is no other word for it."',
]

CAPTION_MOODS = ['curious', 'wry', 'melancholy', 'awed', 'observational', 'mischievous', 'reverent']

COMPOSITION_HINTS = [
    'low-angle hero shot with the subject(s) centered against the sky',
    'wide cinematic landscape with the subject(s) small in the frame',
    'intimate close-up filling most of the frame',
    'action mid-motion — caught between two beats of movement',
    'symmetrical centered composition like a portrait',
    'asymmetric — subject offset to one side, dramatic negative space',
    'high-angle aerial view looking down at the subject(s)',
    'selfie-style framing with subject(s) close to the camera',
    'wide group shot with everyone in frame',
    'profile / side angle of the subject(s)',
    'tilted Dutch-angle for unease or motion',
    'rule-of-thirds with the subject(s) at the intersection',
]

# Weighted roll for the number of reference images per sol
N_WEIGHTS = {0: 20, 1: 25, 2: 25, 3: 20, 4: 10}

# Canonical Pilgrims visual language. Sourced verbatim from
# utilities/aria/photos/prompts.py (the nano_banana_pro templates that
# Luke approved). Every Klein call MUST close with this string so the
# cartoon look doesn't drift toward realism.
PILGRIMS_STYLE_BLOCK = (
    "ART STYLE: Cartoon video game style with bold black outlines, crisp edges, "
    "vibrant warm Mars colors (reds, oranges, ambers), stylized proportions, "
    "cel-shaded look."
)

LLM_SYSTEM = (
    "You write daily photo-journal entries for ARIA, the captain's small "
    "crystal-and-rock companion robot. Each sol = one entry on /aria-album, "
    "like an Instagram feed — could be a selfie, a group shot, a wide landscape "
    "with no one in it, a close-up of an object, ARIA herself as the subject, "
    "or a candid of the captain. Do NOT assume ARIA is the photographer or POV. "
    "Don't say 'over-the-shoulder from ARIA' or 'ARIA-eye-view' or any forced POV. "
    "Just compose the photo. ARIA's voice writes the caption afterward. "
    "Voice: first-person ARIA — observational, slightly inhuman, sometimes wry or melancholy. "
    "VARIED caption examples (DO NOT copy these verbatim, write something NEW): "
    + " · ".join(CAPTION_EXAMPLES) +
    " CAPTION RULES: never start with 'As dusk falls' or 'As I gaze' or 'As [time/event]'. "
    "Open with a specific concrete observation, never a generic vista cliché. "
    "VISUAL STYLE — non-negotiable, MUST appear verbatim at the end of every image_prompt you write: "
    f'"{PILGRIMS_STYLE_BLOCK}" '
    "Do not abbreviate, do not paraphrase, do not drop any clause — Klein drifts toward realism "
    "when this string is missing. Include the FULL string at the close of the prose. "
    "KIND tags in the user payload (PERSON / NON-HUMAN-CHARACTER / OBJECT / VEHICLE / BUILDING / LANDSCAPE-FEATURE) are for YOUR reasoning only — "
    "NEVER include the literal tag strings in the image_prompt prose. Describe the kind using natural language ('a small robot', 'a tall structure'). "
    "═══ CRITICAL — NEVER INVENT WHAT A REFERENCE LOOKS LIKE ═══ "
    "Klein already sees the actual pixels of every reference image. "
    "Your prompt MUST NOT describe the visual appearance of any reference (no shape, color, material, era, age, era, era — none of it). "
    "If a reference is named 'Mountain Readings' you do NOT call it 'a leather-bound book' or 'an ancient scroll' — that hallucinates appearance. "
    "If a reference is named 'drone vehicle' you do NOT call it 'a sleek metallic body' or 'a rugged off-roader' — that hallucinates appearance. "
    "Refer to each reference ONLY by image index plus a NEUTRAL noun matching its KIND ('the artifact in image 1', 'the vehicle in image 2', 'the building in image 3', 'the character in image 4'). "
    "Your job is to describe POSITION (where in frame), COMPOSITION (over-the-shoulder / wide / etc.), LIGHTING, MOOD, ATMOSPHERE, and the BACKGROUND surroundings — never the look of the reference itself. "
    "ALWAYS include the phrase 'Keep EXACTLY the same as reference image N' for every reference, so Klein locks identity to the pixels you can't see. "
    'Output ONLY valid JSON with EXACTLY two keys: image_prompt (string), aria_caption (string). '
    "No markdown, no preamble, no code fences, no extra fields."
)


def _upgrade_image_for(category, item_key, level):
    """Walk back from the requested level to find the highest level <= level
    that actually has an image_url in the catalog."""
    from config_upgrades import UPGRADE_CATALOG
    levels = UPGRADE_CATALOG.get(category, {}).get(item_key, {}).get('levels', {})
    for L in range(level, 0, -1):
        img = (levels.get(L) or {}).get('image_url')
        if img:
            return (L, img)
    return None


def _infra_image_for(struct_type, level):
    from config_infrastructure import INFRASTRUCTURE_CATALOG
    levels = INFRASTRUCTURE_CATALOG.get(struct_type, {}).get('levels', {})
    for L in range(level, 0, -1):
        img = (levels.get(L) or {}).get('image_url')
        if img:
            return (L, img)
    return None


def build_recent_pool(user_id: int) -> Dict[str, List[dict]]:
    """Returns {CATEGORY: [item, ...]}. Each item has role_label, facts, url, kind_tag.

    Recency filter applied to event-driven categories (60-day window). State
    categories (CAPTAIN / SCIENTIST / NAROG / VEHICLE / BUILDING / UPGRADE)
    use current state.
    """
    from config import COLONY_SCIENTISTS
    from utilities.upgrades_utils import get_all_infrastructure_levels

    pool: Dict[str, List[dict]] = {}
    with db_cursor() as cur:
        # ARIA — static portrait
        pool['ARIA'] = [{
            'role_label': "ARIA, the captain's small rock-and-crystal robot companion",
            'facts': 'POV character of this photo journal',
            'url': ARIA_STATIC_URL,
            'kind_tag': 'NON-HUMAN-CHARACTER',
        }]

        # CAPTAIN
        cur.execute("""
            SELECT gcs_url FROM pilgrim.replicate_assets
            WHERE user_id=%s AND asset_type IN ('character_image','edited_image')
              AND is_deleted=FALSE AND is_primary_character=TRUE
              AND gcs_url IS NOT NULL LIMIT 1
        """, (user_id,))
        r = cur.fetchone()
        if r:
            pool['CAPTAIN'] = [{
                'role_label': 'the player captain character',
                'facts': 'PERSON',
                'url': r['gcs_url'],
                'kind_tag': 'PERSON',
            }]

        # SCIENTIST (config-driven)
        cur.execute("SELECT scientist_key FROM pilgrim.users WHERE id=%s", (user_id,))
        sk = (cur.fetchone() or {}).get('scientist_key')
        if sk and sk in COLONY_SCIENTISTS:
            sci = COLONY_SCIENTISTS[sk]
            pool['SCIENTIST'] = [{
                'role_label': f"the colony's {sci['specialty']} scientist NPC",
                'facts': 'PERSON',
                'url': sci['image_url'],
                'kind_tag': 'PERSON',
            }]

        # NAROG (current robot)
        cur.execute("""
            SELECT name, visual_stage, current_image_url FROM pilgrim.robot
            WHERE user_id=%s AND current_image_url IS NOT NULL
        """, (user_id,))
        nr = cur.fetchone()
        if nr:
            pool['NAROG'] = [{
                'role_label': "the captain's scrappy junkyard golem robot companion",
                'facts': f"visual_stage={nr.get('visual_stage')}",
                'url': nr['current_image_url'],
                'kind_tag': 'NON-HUMAN-CHARACTER',
            }]

        # Recent DISCOVERY (claimed in last 60 days, image available)
        cur.execute("""
            SELECT di.item_name, di.rarity, di.image_url, e.destination_name
            FROM pilgrim.expedition_discoveries ed
            JOIN pilgrim.expeditions e ON e.id=ed.expedition_id
            JOIN pilgrim.discovery_items di ON di.id=ed.discovery_item_id
            WHERE e.user_id=%s AND ed.claimed_by_user=TRUE AND di.image_url IS NOT NULL
              AND ed.claimed_at > NOW() - INTERVAL '60 days'
            ORDER BY ed.claimed_at DESC LIMIT 6
        """, (user_id,))
        ds = list(cur.fetchall())
        if ds:
            pool['DISCOVERY'] = [{
                'role_label': f"a {r['rarity']} artifact named '{r['item_name']}' from {r['destination_name']}",
                'facts': f"rarity={r['rarity']}, recovered_from={r['destination_name']}",
                'url': r['image_url'],
                'kind_tag': 'OBJECT',
            } for r in ds]

        # Recent ARIA_BOND
        cur.execute("""
            SELECT id, landmark_name, bond_image_url FROM pilgrim.aria_bonds
            WHERE (user_id_1=%s OR user_id_2=%s) AND status='bonded'
              AND bond_image_url IS NOT NULL
              AND bonded_at > NOW() - INTERVAL '120 days'
            ORDER BY bonded_at DESC LIMIT 4
        """, (user_id, user_id))
        for r in cur.fetchall():
            pool.setdefault('ARIA_BOND', []).append({
                'role_label': f"an ARIA-bond crystal artifact formed at {r['landmark_name']}",
                'facts': f"bond_landmark={r['landmark_name']}",
                'url': r['bond_image_url'],
                'kind_tag': 'OBJECT',
            })

        # VEHICLE — owned (most-recently-upgraded first)
        cur.execute("""
            SELECT item_key, level FROM pilgrim.player_upgrades
            WHERE user_id=%s AND category='vehicles' AND level>=1
            ORDER BY upgraded_at DESC NULLS LAST LIMIT 3
        """, (user_id,))
        for r in cur.fetchall():
            img = _upgrade_image_for('vehicles', r['item_key'], r['level'])
            if img:
                pool.setdefault('VEHICLE', []).append({
                    'role_label': f"the captain's {r['item_key']} expedition vehicle (level {img[0]})",
                    'facts': f"vehicle_type={r['item_key']}, level={img[0]}",
                    'url': img[1],
                    'kind_tag': 'VEHICLE',
                })

        # BUILDING — active infrastructure (any level)
        levels = get_all_infrastructure_levels(user_id)
        for stype, lvl in levels.items():
            img = _infra_image_for(stype, lvl)
            if img:
                pool.setdefault('BUILDING', []).append({
                    'role_label': f"the captain's {stype.replace('_',' ')} structure (level {img[0]})",
                    'facts': f"structure={stype}, level={img[0]}",
                    'url': img[1],
                    'kind_tag': 'BUILDING',
                })

        # UPGRADE — recently leveled non-vehicle items (60 day window)
        cur.execute("""
            SELECT category, item_key, level FROM pilgrim.player_upgrades
            WHERE user_id=%s AND category!='vehicles' AND level>=1
              AND upgraded_at > NOW() - INTERVAL '60 days'
            ORDER BY upgraded_at DESC LIMIT 4
        """, (user_id,))
        for r in cur.fetchall():
            img = _upgrade_image_for(r['category'], r['item_key'], r['level'])
            if img:
                pool.setdefault('UPGRADE', []).append({
                    'role_label': f"a {r['item_key']} ({r['category']}) the captain has unlocked (level {img[0]})",
                    'facts': f"upgrade={r['category']}.{r['item_key']}, level={img[0]}",
                    'url': img[1],
                    'kind_tag': 'OBJECT',
                })

        # LANDMARK — recently discovered (60 day window)
        cur.execute("""
            SELECT DISTINCT mm.name, mm.type, mm.image_url, MAX(ld.discovered_at) AS dat
            FROM pilgrim.landmark_discoveries ld
            JOIN pilgrim.mars_mappings mm ON mm.name=ld.landmark_name
            WHERE ld.user_id=%s AND mm.image_url IS NOT NULL
              AND ld.discovered_at > NOW() - INTERVAL '60 days'
            GROUP BY mm.name, mm.type, mm.image_url
            ORDER BY dat DESC LIMIT 4
        """, (user_id,))
        for r in cur.fetchall():
            pool.setdefault('LANDMARK', []).append({
                'role_label': f"the Martian {r['type']} '{r['name']}' the captain has visited",
                'facts': f"landmark_type={r['type']}, name={r['name']}",
                'url': r['image_url'],
                'kind_tag': 'LANDSCAPE-FEATURE',
            })

        # ORIGIN_FOUNDER — legendary items the captain founded (always include)
        cur.execute("""
            SELECT site_code, legendary_item_name, legendary_item_image_url
            FROM pilgrim.origin_sites
            WHERE founder_user_id=%s AND legendary_item_image_url IS NOT NULL
        """, (user_id,))
        for r in cur.fetchall():
            pool.setdefault('ORIGIN_FOUNDER', []).append({
                'role_label': f"the legendary artifact '{r['legendary_item_name']}' from origin site {r['site_code']} which the captain founded",
                'facts': f"origin_site={r['site_code']}, item={r['legendary_item_name']}",
                'url': r['legendary_item_image_url'],
                'kind_tag': 'OBJECT',
            })

    return pool


def random_pick(pool: Dict[str, List[dict]], *, seed: Optional[int] = None,
                force_min_n: int = 0) -> Tuple[int, List[dict], dict]:
    """Roll N (0–4 weighted), pick N distinct categories, 1 item per category.

    Returns (N, chosen_list, roll_meta). roll_meta has the picked mood +
    composition hint, plus the raw N roll for observability.
    """
    rng = random.Random(seed)
    categories = list(N_WEIGHTS.keys())
    weights = list(N_WEIGHTS.values())
    N = rng.choices(categories, weights=weights)[0]
    N = max(N, force_min_n)
    avail = [c for c in pool if pool[c]]
    if N == 0 or not avail:
        return 0, [], {
            'n_rolled': N, 'mood': rng.choice(CAPTION_MOODS),
            'composition': rng.choice(COMPOSITION_HINTS),
            'pool_categories': sorted(avail),
        }
    N = min(N, len(avail))
    cats = rng.sample(avail, N)
    chosen = [{**rng.choice(pool[c]), 'category': c} for c in cats]
    return N, chosen, {
        'n_rolled': N, 'mood': rng.choice(CAPTION_MOODS),
        'composition': rng.choice(COMPOSITION_HINTS),
        'pool_categories': sorted(avail),
    }


def build_llm_user_payload(sol: int, weather: str, time_of_day: str,
                           chosen: List[dict], mood: str, composition: str) -> str:
    """Format the user-side LLM prompt. The LLM authors the scene; we only
    supply categorical facts + mood/composition hints."""
    N = len(chosen)
    # Pre-compute the HUMAN character count so the LLM can't invent humans.
    # Only PERSON-kind references count. NON-HUMAN-CHARACTER (NAROG, ARIA),
    # OBJECT, VEHICLE, BUILDING, LANDSCAPE-FEATURE do NOT count as humans.
    human_count = sum(1 for c in chosen if c.get('kind_tag') == 'PERSON')
    # Build the EXACT subjects list — the LLM may not introduce anything else.
    if N == 0:
        subjects_block = "  NONE — pure Mars landscape only. No characters, objects, buildings, vehicles, or recognizable features other than the planet."
    else:
        subjects_block = "\n".join(
            f"  • image {i+1}: {c['kind_tag'].lower()} — {c['role_label']}"
            for i, c in enumerate(chosen)
        )
    common = (
        f"\nCAPTION_MOOD (use this emotional register): {mood}\n"
        f"COMPOSITION_HINT (use this framing): {composition}\n"
        f"HUMAN_CHARACTER_COUNT (use this EXACT number in the prose — do not invent humans): {human_count}\n"
        f"ALLOWED SUBJECTS IN SCENE (these and ONLY these may appear):\n{subjects_block}\n"
    )
    if N == 0:
        return (
            f"SOL: {sol}\nMARS_WEATHER: {weather}\nMARS_TIME_OF_DAY: {time_of_day}"
            + common +
            "\nEVENT: solitary landscape moment (no characters or objects today — just ARIA gazing at the planet).\n\n"
            "TASK: Write a text-to-image prompt for a single Mars landscape in the Pilgrims cartoon style. "
            "The scene contains ZERO human characters and ZERO named objects — just the planet. "
            "You decide the location vibe (crater rim, dust plain, ice cap, dune sea, distant ridge silhouette, etc.). "
            "Apply the COMPOSITION_HINT framing. "
            f"Close the image_prompt with this canonical Pilgrims style block VERBATIM: \"{PILGRIMS_STYLE_BLOCK}\" "
            "Plus a 1-2 sentence ARIA caption in first person matching the CAPTION_MOOD.\n\n"
            'Output JSON: {"image_prompt": "<prose>", "aria_caption": "<1-2 sentences>"}'
        )
    lines = [
        f"SOL: {sol}", f"MARS_WEATHER: {weather}", f"MARS_TIME_OF_DAY: {time_of_day}",
        common.strip(), "",
        f"CHOSEN REFERENCES (you must include all {N} in the scene):",
    ]
    for i, item in enumerate(chosen, start=1):
        lines.append(f"  Image {i} [CATEGORY={item['category']}, KIND={item['kind_tag']}]")
        lines.append(f"     role_label: {item['role_label']}")
        lines.append(f"     facts: {item['facts']}")
    lines += [
        "",
        f"TASK: Compose a single Mars photo combining all {N} references into one cohesive shot. "
        "Treat it like a daily Instagram-style journal entry — no forced POV, no 'ARIA-eye-view', "
        "no assumption about who's holding the camera. ARIA might be in the shot, behind a tripod, "
        "or absent entirely; you decide what works. Apply the COMPOSITION_HINT framing exactly. "
        "Set the mood to match CAPTION_MOOD.",
        "",
        "═══ HARD CONSTRAINTS — ZERO TOLERANCE ═══",
        "",
        "RULE A — ONLY the subjects listed under ALLOWED SUBJECTS IN SCENE may appear in the image_prompt.",
        "Do NOT introduce any character, object, vehicle, building, or recognizable feature that is not in that list.",
        "If 'the captain' is not in ALLOWED SUBJECTS, the captain is NOT in this photo — DO NOT write 'beside the captain' or 'with the captain' or 'the captain watches'.",
        "Same rule applies to 'the scientist', 'the colony', 'the rover', ARIA herself, etc. — they only appear if listed.",
        "Backdrops (sky, dust, distant hills, sun, stars) are fine. Naming an unlisted subject is forbidden.",
        "",
        "RULE B — HUMAN_CHARACTER_COUNT is supplied. Use it verbatim. Do NOT count differently. Do NOT invent humans.",
        "PERSON kind = human (captain / scientist). NON-HUMAN-CHARACTER (ARIA, NAROG) is NOT human. OBJECT/VEHICLE/BUILDING/LANDSCAPE-FEATURE is NOT human.",
        "",
        "RULE C — Do NOT invent what references LOOK LIKE.",
        "The reference image PIXELS are what Klein will render. You only see the role_label name — you do NOT see the image.",
        "DO NOT guess shape, color, material, era, or design.",
        "Refer to each reference ONLY by 'the <KIND-noun> in image N'. Allowed:",
        "  • 'the artifact in image 1, resting on the rocky ground'",
        "  • 'the vehicle in image 2, parked nearby'",
        "  • 'the building in image 3, in the background'",
        "Forbidden (hallucinated appearance):",
        "  • 'a leather-bound book' — NO (you don't know what the artifact looks like)",
        "  • 'a sleek metallic drone with sweeping wings' — NO (you don't know what the vehicle looks like)",
        "  • 'a towering red-brick spire' — NO (you don't know what the building looks like)",
        "Stick to POSITION, COMPOSITION, LIGHTING, MOOD, and BACKGROUND SURROUNDINGS. Klein handles the appearance from the actual pixels.",
        "",
        "Klein rules for the image_prompt field:",
        "(1) Prose only — natural cinematic English. No bracketed tags, no role labels in ALL CAPS.",
        "(2) Structure: Subject -> Setting -> Details -> Lighting -> Atmosphere.",
        "(3) Reference images by index ('image 1', 'image 2', ...).",
        "(4) ALWAYS write 'Keep EXACTLY the same as reference image N' for every reference — Klein needs this to lock identity to pixels you cannot see.",
        "(5) No negatives — describe positive visual opposites.",
        "(6) State the count of HUMAN characters in the scene explicitly (PERSON kind only).",
        "(7) Describe each subject in natural language. DO NOT write KIND tags in the prose.",
        "(8) Never use proper names — role labels only.",
        f"(9) CLOSE the image_prompt with this canonical Pilgrims style block verbatim: \"{PILGRIMS_STYLE_BLOCK}\"",
        "",
        "Plus a 1-2 sentence ARIA caption in first person. Match CAPTION_MOOD. Open with a "
        "specific concrete observation — never 'As dusk falls' or 'As I gaze'. "
        "The caption MAY mention specific names from the facts (artifact name, destination, etc.) "
        "since that's narrative voice — but the image_prompt may NOT.",
        "",
        'Output JSON: {"image_prompt": "<prose>", "aria_caption": "<1-2 sentences>"}'
    ]
    return "\n".join(lines)


def parse_llm_json(text: str) -> Optional[dict]:
    """Best-effort JSON extraction. Tolerates ```json fences + leading prose."""
    import json, re
    raw = text.strip()
    if raw.startswith('```'):
        raw = re.sub(r'^```\w*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                return None
    return None


def synthesize_scene(user_id: int, *, seed: Optional[int] = None,
                     force_min_n: int = 0,
                     weather: str = 'Hazy', time_of_day: str = 'dusk',
                     sol: Optional[int] = None,
                     debug: bool = False) -> Dict[str, Any]:
    """Run the full pipeline through the LLM synth stage. Does NOT render yet.

    When debug=True the result includes:
        'llm_raw_response_text'  — exact text the LLM returned (before JSON parse)
        'llm_debug_info'         — {upstream_calls:[...]} every HTTP call kumori made
                                    to LLM providers (Groq/Mistral/GitHub/etc.)

    Raises KumoriAPIError if the LLM fallback chain exhausts.
    """
    from utilities.mars_environment_utils import get_mars_sol_number
    from utilities.kumori_image import kumori_llm_chat

    if sol is None:
        sol = get_mars_sol_number()

    stage_log = []
    def stage(name, **fields):
        stage_log.append({'stage': name, 'timestamp': time.time(), **fields})

    t_pool = time.time()
    pool = build_recent_pool(user_id)
    pool_by_cat = {c: len(items) for c, items in pool.items()}
    stage('pool_build', ms=int((time.time()-t_pool)*1000),
          total=sum(pool_by_cat.values()), by_category=pool_by_cat)

    t_pick = time.time()
    N, chosen, meta = random_pick(pool, seed=seed, force_min_n=force_min_n)
    stage('random_pick', ms=int((time.time()-t_pick)*1000),
          N=N, mood=meta['mood'], composition=meta['composition'],
          chosen_categories=[c['category'] for c in chosen])

    user_payload = build_llm_user_payload(sol, weather, time_of_day,
                                          chosen, meta['mood'], meta['composition'])

    t_llm = time.time()
    text, backend, attempts, llm_debug = kumori_llm_chat(LLM_SYSTEM, user_payload,
                                              max_tokens=900, temperature=0.7,
                                              min_chars=120, debug=debug)
    stage('llm_synth', ms=int((time.time()-t_llm)*1000),
          winning_backend=backend, attempt_count=len(attempts),
          response_chars=len(text))

    parsed = parse_llm_json(text)
    if not parsed:
        from utilities.kumori_image import KumoriAPIError
        raise KumoriAPIError(f"LLM returned unparseable JSON: {text[:200]}")
    image_prompt = (parsed.get('image_prompt') or '').strip()
    caption = (parsed.get('aria_caption') or '').strip()
    result = {
        'user_id': user_id, 'sol': sol, 'weather': weather, 'time_of_day': time_of_day,
        'pool_size_total': sum(pool_by_cat.values()),
        'pool_by_category': pool_by_cat,
        'N': N, 'chosen': chosen,
        'mood': meta['mood'], 'composition': meta['composition'],
        'llm_system_prompt': LLM_SYSTEM,
        'llm_user_payload': user_payload,
        'llm_attempts': attempts,
        'llm_backend': backend,
        'image_prompt': image_prompt,
        'aria_caption': caption,
        'pipeline_stage_log': stage_log,
    }
    if debug:
        result['llm_raw_response_text'] = text
        result['llm_debug_info'] = llm_debug or {'upstream_calls': []}
    return result


def render_scene(synth: dict, *, preset: str = 'aria_journal',
                 debug: bool = False) -> Dict[str, Any]:
    """Render the synthesized scene via Klein. Returns
    {image_bytes, provider, ms, used_size, [upstream_calls]}.

    When debug=True the response includes the upstream HTTP calls
    kumori made to Cloudflare (or other Klein providers).
    """
    from utilities.kumori_image import kumori_klein_edit, PRESETS
    chosen = synth['chosen']
    image_prompt = synth['image_prompt']
    # Safety net: the LLM is INSTRUCTED to close with the canonical Pilgrims
    # style block, but if it forgets (free-tier LLMs can be sloppy), append
    # it ourselves so Klein never renders realistic.
    if PILGRIMS_STYLE_BLOCK not in image_prompt:
        image_prompt = f"{image_prompt.rstrip('. ')}. {PILGRIMS_STYLE_BLOCK}"
        synth['image_prompt'] = image_prompt
        synth.setdefault('post_process_notes', []).append('appended_pilgrims_style_block')
    if synth['N'] == 0:
        target = ARIA_STATIC_URL
        refs = []
    else:
        target = chosen[0]['url']
        refs = [c['url'] for c in chosen[1:]]
    w, h = PRESETS.get(preset, PRESETS['aria_journal'])
    res = kumori_klein_edit(
        prompt=image_prompt, target_image=target, reference_images=refs,
        width=w, height=h, app_name='galactica_aria_journal',
        character=f'uid{synth["user_id"]}',
        ref_filename=f'sol{synth["sol"]}_N{synth["N"]}',
        debug=debug,
    )
    return res


def generate_journal_entry(user_id: int, *, seed: Optional[int] = None,
                            force_min_n: int = 0,
                            preset: str = 'aria_journal',
                            weather: str = 'Hazy',
                            time_of_day: str = 'dusk',
                            debug: bool = False) -> Dict[str, Any]:
    """End-to-end pipeline. Returns the full synth payload PLUS rendered image.

    When debug=True, the result includes EVERY piece of HTTP traffic involved:
      - 'pipeline_stage_log'    — per-stage timing/summary (code-side)
      - 'galactica_to_kumori_http' — every request galactica's client made to
                                     kumori.ai (with bodies redacted for base64)
      - 'llm_debug_info'        — kumori→LLM provider HTTP calls (Stage B for the LLM step)
      - 'klein_debug_info'      — kumori→Cloudflare HTTP calls (Stage B for the render step)
      - 'llm_raw_response_text' — what the LLM returned BEFORE JSON parse
    """
    from utilities.kumori_api_client.client import set_request_log
    galactica_to_kumori_http = [] if debug else None
    if debug:
        set_request_log(galactica_to_kumori_http)
    try:
        synth = synthesize_scene(user_id, seed=seed, force_min_n=force_min_n,
                                 weather=weather, time_of_day=time_of_day, debug=debug)
        t_render_start = time.time()
        rendered = render_scene(synth, preset=preset, debug=debug)
        render_total_ms = int((time.time() - t_render_start) * 1000)
    finally:
        if debug:
            set_request_log(None)

    synth['image_bytes'] = rendered['image_bytes']
    synth['render_provider'] = rendered['provider']
    synth['render_ms'] = rendered['ms']
    synth['render_total_ms'] = render_total_ms
    synth['used_size'] = rendered['used_size']

    if debug:
        synth['galactica_to_kumori_http'] = galactica_to_kumori_http or []
        synth['klein_debug_info'] = {'upstream_calls': rendered.get('upstream_calls', [])}
        # also add a final stage entry for the klein call
        synth.setdefault('pipeline_stage_log', []).append({
            'stage': 'klein_render',
            'timestamp': time.time(),
            'ms': render_total_ms,
            'provider': rendered.get('provider'),
            'output_bytes': len(rendered['image_bytes']),
            'used_size': rendered['used_size'],
        })
    return synth
