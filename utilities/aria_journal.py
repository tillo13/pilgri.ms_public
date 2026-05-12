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
    "crystal-and-rock companion robot. Each sol = one entry on /aria-album. "
    "You produce TWO outputs: (1) an image_prompt for the flux-2-klein-4b "
    "edit model that renders the photo, and (2) an aria_caption for the journal. "
    "\n\n"
    "═══ CRITICAL — KLEIN IS AN EDIT MODEL, NOT A SCENE-PAINTER ═══ "
    "Klein/Kontext is built for EDIT VERBS: 'Replace…', 'Add…', 'Keep…'. "
    "When you write descriptive prose like 'a small robot stands centered against a hazy gradient sky, "
    "its silhouette sharp against the fading light', Klein READS THAT AS A COMMAND TO GENERATE a new "
    "small robot — and the reference image becomes nearly irrelevant. The reference's identity is lost. "
    "\n\n"
    "WRITE LIKE AN EDIT INSTRUCTION, NOT A SCENE DESCRIPTION:\n"
    "  ✅ 'Replace the background of reference image 1 with a Mars dusk landscape: hazy orange light, distant rocky cliffs. Keep the character in reference image 1 exactly as-is. Every other detail identical to reference image 1.'\n"
    "  ❌ 'On Mars at dusk: the non-human-character in image 1 stands alone at the center of a shallow crater. Soft dust swirls at its base, catching the last amber rays. Keep EXACTLY the same as reference image 1.'\n"
    "The second one drowns the reference in scene prose and loses identity every single time.\n"
    "\n"
    "RULES — every rule below is non-negotiable:\n"
    "  R1. Every sentence of image_prompt must start with an EDIT VERB: Replace, Add, Keep, Place, Position.\n"
    "  R2. NEVER describe the appearance of a referenced subject — no 'small', 'tall', 'metallic', 'silhouette', 'figure', 'limbs', 'stands', 'crouches', 'crystalline', 'rocky', 'leather-bound'. Klein already sees the pixels; descriptive nouns OVERRIDE the reference.\n"
    "  R3. Refer to referenced subjects ONLY as 'the character in reference image N' or 'the [kind-noun] from reference image N'. KIND nouns: person → 'the character', non-human-character → 'the character', object → 'the object', vehicle → 'the vehicle', building → 'the building', landscape-feature → 'the landscape feature'.\n"
    "  R4. LENGTH CAP: 20–60 words for image_prompt (excluding style block). Edit prompts work better SHORT. If you go over 60, you're scene-painting again.\n"
    "  R5. The Mars setting gets ONE short clause — orange light, dusty plain, distant cliffs. That's it. No 'symmetrical frame isolates', no 'silhouette sharp against', no 'soft dust swirls'.\n"
    "  R6. End image_prompt with this canonical style block verbatim — Klein drifts to realism without it:\n"
    f'      "{PILGRIMS_STYLE_BLOCK}"\n'
    "  R7. The aria_caption is SEPARATE from image_prompt. The caption is first-person ARIA voice — observational, slightly inhuman, wry or melancholy. The caption MAY use proper names from facts; the image_prompt may NOT.\n"
    "\n"
    "VARIED caption examples (DO NOT copy verbatim — write something NEW): "
    + " · ".join(CAPTION_EXAMPLES) +
    " Never start with 'As dusk falls' / 'As I gaze' / 'As [time/event]'. Open with a concrete observation.\n"
    "\n"
    "Output ONLY valid JSON with EXACTLY two keys: image_prompt (string), aria_caption (string). "
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


_KIND_TO_NOUN = {
    'PERSON': 'the character',
    'NON-HUMAN-CHARACTER': 'the character',
    'OBJECT': 'the object',
    'VEHICLE': 'the vehicle',
    'BUILDING': 'the building',
    'LANDSCAPE-FEATURE': 'the landscape feature',
}


def build_llm_user_payload(sol: int, weather: str, time_of_day: str,
                           chosen: List[dict], mood: str, composition: str) -> str:
    """Format the user-side LLM prompt. Branches by N because Klein responds
    radically differently to edit-style instructions vs scene composition:

      • N=0 — no references → text-to-image landscape (different code path)
      • N=1 — single reference → background swap, identity-preserving
      • N≥2 — anchor on image 1, "add" the others, keep image 1 identical

    Per-source: Apatero Kontext guide + Next Diffusion working examples
    (validated via /deep-search 2026-05-11). The minimal-edit verb pattern
    is the documented norm for identity preservation."""
    N = len(chosen)

    # ─── N=0: pure landscape (no edit, text-to-image) ─────────────────────
    if N == 0:
        return (
            f"SOL: {sol}\nMARS_WEATHER: {weather}\nMARS_TIME_OF_DAY: {time_of_day}\n"
            f"CAPTION_MOOD: {mood}\nCOMPOSITION_HINT: {composition}\n\n"
            "EVENT: solitary Mars landscape — no characters, no objects, no buildings, no vehicles. Just the planet.\n\n"
            "TASK: Write a SHORT (20–40 word) text-to-image prompt for a single Mars landscape in the Pilgrims cartoon style. "
            "You pick the vibe (crater rim, dust plain, ice cap, dune sea, distant ridge silhouette). "
            "Apply the COMPOSITION_HINT framing.\n"
            f"END the image_prompt with this style block verbatim: \"{PILGRIMS_STYLE_BLOCK}\"\n\n"
            "Plus a 1-2 sentence ARIA caption in first person, matching CAPTION_MOOD.\n\n"
            'Output JSON: {"image_prompt": "<prose>", "aria_caption": "<1-2 sentences>"}'
        )

    # Index-1 anchor: this character/subject is the IDENTITY we preserve.
    anchor = chosen[0]
    anchor_noun = _KIND_TO_NOUN.get(anchor.get('kind_tag', ''), 'the subject')

    # Caption-side fact map (so caption can use proper names; image_prompt may not).
    facts_lines = []
    for i, c in enumerate(chosen, start=1):
        facts_lines.append(f"  Image {i} [{c['category']} · {c['kind_tag']}]: {c['role_label']}"
                           + (f" — {c['facts']}" if c.get('facts') else ''))
    facts_block = "\n".join(facts_lines)

    # ─── N=1: single reference → BACKGROUND SWAP, identity-preserving ─────
    if N == 1:
        return (
            f"SOL: {sol}\nMARS_WEATHER: {weather}\nMARS_TIME_OF_DAY: {time_of_day}\n"
            f"CAPTION_MOOD: {mood}\nCOMPOSITION_HINT: {composition}\n"
            f"\nREFERENCE (you may NOT describe its appearance):\n{facts_block}\n"
            "\nTASK — write a MINIMAL-EDIT prompt (this is a single-reference background swap):\n"
            "  • Klein already sees image 1's pixels. Your only job is to swap the background and frame the shot.\n"
            "  • Open with: 'Replace the background of reference image 1 with [Mars setting in ~12 words].'\n"
            "  • Then: 'Keep " + anchor_noun + " in reference image 1 exactly as-is.'\n"
            "  • Then: 'Every other detail identical to reference image 1.'\n"
            "  • Optional 1 short clause for COMPOSITION_HINT framing (centered / wide / profile / close-up).\n"
            "  • End with the style block verbatim.\n"
            "  • TARGET LENGTH: 25–45 words BEFORE the style block. SHORT WINS.\n"
            "  • NEVER describe " + anchor_noun + " (no 'small', 'tall', 'metallic', 'crystalline', 'rocky', 'silhouette', 'figure', 'limbs', 'stands', 'crouches'). Klein has the pixels.\n"
            f"  • END the image_prompt verbatim with: \"{PILGRIMS_STYLE_BLOCK}\"\n"
            "\nThen a 1-2 sentence ARIA caption matching CAPTION_MOOD. Caption MAY use proper names from the facts above. Open with a concrete observation.\n"
            "\nWORKED EXAMPLE (for a captain reference):\n"
            '  "Replace the background of reference image 1 with a Mars dusk landscape: hazy orange light, distant rocky cliffs, soft amber shadows on the dust. Keep the character in reference image 1 exactly as-is. Every other detail identical to reference image 1. ART STYLE: …"\n'
            "\n"
            'Output JSON: {"image_prompt": "<prose>", "aria_caption": "<1-2 sentences>"}'
        )

    # ─── N≥2: anchor on image 1, ADD the others, keep image 1 identical ──
    add_lines = []
    for i, c in enumerate(chosen[1:], start=2):
        noun = _KIND_TO_NOUN.get(c.get('kind_tag', ''), 'the subject')
        add_lines.append(f"  • For reference image {i} ({c['kind_tag']}): write 'Add {noun} from reference image {i}, [short position phrase].'")
    add_block = "\n".join(add_lines)

    return (
        f"SOL: {sol}\nMARS_WEATHER: {weather}\nMARS_TIME_OF_DAY: {time_of_day}\n"
        f"CAPTION_MOOD: {mood}\nCOMPOSITION_HINT: {composition}\n"
        f"\nREFERENCES (you may NOT describe their appearance):\n{facts_block}\n"
        f"\nIMAGE 1 IS THE IDENTITY ANCHOR. Klein will start from image 1's pixels and ADD the others around {anchor_noun} in image 1.\n"
        "\nTASK — write a MINIMAL-EDIT prompt structured as edit verbs only:\n"
        "  • Sentence 1: 'Replace the background of reference image 1 with [Mars setting in ~10 words].'\n"
        f"{add_block}\n"
        "  • Then: 'Keep " + anchor_noun + " in reference image 1 exactly as-is. Keep every reference exactly as-is.'\n"
        "  • End with the style block verbatim.\n"
        "  • TARGET LENGTH: 30–60 words BEFORE the style block. SHORTER wins.\n"
        "  • NEVER describe what any reference looks like — no 'small', 'tall', 'metallic', 'silhouette', 'figure', 'limbs', 'stands', 'crouches', 'crystalline', 'rocky', 'leather-bound', etc. Klein has the pixels.\n"
        f"  • END the image_prompt verbatim with: \"{PILGRIMS_STYLE_BLOCK}\"\n"
        "\nThen a 1-2 sentence ARIA caption matching CAPTION_MOOD. Caption MAY use proper names from the facts. Open with a concrete observation.\n"
        "\nWORKED EXAMPLE (captain + vehicle + landmark):\n"
        '  "Replace the background of reference image 1 with a Mars dusk landscape. Add the vehicle from reference image 2, parked to the right. Add the landscape feature from reference image 3, in the distance. Keep the character in reference image 1 exactly as-is. Keep every reference exactly as-is. ART STYLE: …"\n'
        "\n"
        'Output JSON: {"image_prompt": "<prose>", "aria_caption": "<1-2 sentences>"}'
    )


FINAL_CAPTION_SYSTEM = (
    "You are ARIA, the small crystal-and-rock companion robot of a Mars colony captain. "
    "You curate ARIA's daily photo journal. A first-pass caption has ALREADY been written with proper names, ARIA's voice, and narrative sentimentality. "
    "Your job is to PRESERVE that caption almost entirely. The vision-LLM read of the rendered image is a VETO SIGNAL — only useful for catching when an element was supposed to render but Klein silently dropped it. "
    "Default action: return the first-pass caption VERBATIM. "
    "Only edit when the vision description clearly proves a NAMED element from the picks is absent — and even then, surgically rewrite that one phrase, keeping ARIA's voice, proper names, mood, and Mars sentimentality intact. "
    "RULES: "
    "  • Preserve proper names from the picks (Narog, captain, scientist, specific landmark names like 'Farah Vallis', etc.) whenever they're consistent with vision. "
    "  • Vision LLMs often miss humans inside spacesuits, miscount figures, or call a captain 'a robot'. Do NOT treat that as proof the captain is absent. Trust picks unless vision actively shows something incompatible. "
    "  • Preserve ARIA's voice: observational, slightly inhuman, wry or melancholy, with narrative beats. "
    "  • Preserve Mars sentimentality: references to sol, Martian terrain, the colony, ARIA's relationship with the captain. "
    "  • NEVER flatten the caption into a generic description of what vision saw. 'I'm standing alongside a robot with a fetching Santa hat' is a FAILURE — that's vision-LLM voice, not ARIA voice. "
    "  • Only when a picked element is clearly missing (e.g., picks include 'scientist' but vision sees zero humans and only one robot), surgically remove the scientist clause while preserving everything else. "
    "Output ONLY valid JSON with one key: aria_caption (string). No markdown, no preamble."
)


def build_caption_reconciliation_prompt(synth: dict, vision_text: str) -> str:
    """Give the strong LLM the first-pass caption AS THE STARTING POINT,
    the picks (for proper names + facts), and the vision read (as a veto
    signal for elements Klein silently dropped). Default behavior: return
    the first-pass caption unchanged. Edit only when vision proves a named
    element is absent."""
    chosen = synth.get('chosen') or []
    first_pass = (synth.get('aria_caption') or '').strip()
    parts = [
        f"SOL: {synth.get('sol')}",
        f"MOOD: {synth.get('mood')}",
        f"COMPOSITION: {synth.get('composition')}",
        "",
        "FIRST-PASS CAPTION (this is the starting point — your DEFAULT output is to return this verbatim):",
        f'  "{first_pass}"',
        "",
    ]
    if chosen:
        parts.append("PICKED ELEMENTS (these were supposed to render — proper names & facts to preserve):")
        for i, c in enumerate(chosen, start=1):
            parts.append(f"  • image {i} [{c['category']} · {c['kind_tag']}]")
            parts.append(f"      role_label: {c['role_label']}")
            if c.get('facts'):
                parts.append(f"      facts: {c['facts']}")
    else:
        parts.append("PICKED ELEMENTS: none (pure Mars landscape)")
    parts += [
        "",
        "VISION-LLM READ (what the vision model saw — use ONLY as a veto signal):",
        f'  "{vision_text}"',
        "",
        "DECISION PROCESS:",
        "  STEP 1 — For each PICKED element, decide if vision actively CONTRADICTS its presence.",
        "    • 'contradicts' = vision describes the scene in a way that's incompatible with the element rendering at all.",
        "    • 'vision called the captain a robot' is NOT a contradiction — vision LLMs misread cartoon spacesuits all the time.",
        "    • 'picks have a scientist but vision sees zero humans and one robot' IS a contradiction.",
        "    • When in doubt, trust the picks. The picks are ground truth for INTENT; vision is just QA.",
        "  STEP 2 — If NOTHING is contradicted: return the first-pass caption VERBATIM. Do not paraphrase, do not 'improve' it.",
        "  STEP 3 — If something IS contradicted: surgically rewrite ONLY the phrase that mentions the missing element. Preserve everything else: proper names, ARIA voice, Mars sentimentality, mood, narrative beats.",
        "",
        "FORBIDDEN OUTPUTS:",
        "  • Flattening the caption into a generic vision-style description ('I'm standing alongside a robot with a Santa hat…') — this destroys ARIA's voice. NEVER do this.",
        "  • Replacing proper names from the picks with generic vision nouns ('Narog' → 'a robot') — keep the proper name.",
        "  • Stripping out colony/Mars references that the vision LLM didn't explicitly see — those are ARIA's worldview, not vision's job to corroborate.",
        "",
        'Output JSON: {"aria_caption": "<the first-pass caption verbatim, OR a surgically-edited version preserving voice/names/sentiment>"}',
    ]
    return "\n".join(parts)


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
    # max_tokens lowered from 900 → 350 to discourage rambling prompts that
    # bury references mid-paragraph. Klein de-prioritizes refs buried in
    # long prose, so we want tight ~80-100-word image_prompts.
    text, backend, attempts, llm_debug = kumori_llm_chat(LLM_SYSTEM, user_payload,
                                              max_tokens=350, temperature=0.7,
                                              min_chars=80, debug=debug)
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


def verify_and_caption(synth: dict, image_bytes: bytes, *, debug: bool = False) -> Dict[str, Any]:
    """Post-render redundancy loop. Two HTTP calls:
      1. Vision LLM describes what's ACTUALLY in the rendered image (ground truth)
      2. Strongest LLM rewrites the caption using picks + vision description,
         using proper names only for things that actually rendered.

    Returns a dict that the caller merges into the synth result, surfacing
    every byte of the verification stages for the debug console.
    """
    from utilities.kumori_image import kumori_describe, kumori_llm_chat

    VISION_PROMPT = (
        "Describe everything visible in this single image, clearly and factually, in 3-4 short sentences. "
        "Name every character, every object, every notable feature you can identify. "
        "Focus on visual content — what shapes, colors, characters, objects, structures appear. "
        "Do not interpret meaning, mood, or context. Just describe what is visibly there."
    )

    t_v = time.time()
    try:
        vision_text, vision_backend = kumori_describe(image_bytes, prompt=VISION_PROMPT)
    except Exception as e:
        logger.warning(f"verify_and_caption: vision describe failed: {e}")
        vision_text, vision_backend = '', '?'
    vision_ms = int((time.time() - t_v) * 1000)

    cap_user = build_caption_reconciliation_prompt(synth, vision_text or '(vision describe failed; only PICKED ELEMENTS are known)')
    t_c = time.time()
    try:
        cap_text, cap_backend, cap_attempts, cap_debug = kumori_llm_chat(
            FINAL_CAPTION_SYSTEM, cap_user,
            max_tokens=200, temperature=0.7, min_chars=20, debug=debug,
        )
    except Exception as e:
        logger.warning(f"verify_and_caption: final caption LLM failed: {e}")
        cap_text, cap_backend, cap_attempts, cap_debug = '', '?', [], None
    cap_ms = int((time.time() - t_c) * 1000)
    parsed = parse_llm_json(cap_text) if cap_text else None
    if parsed and parsed.get('aria_caption'):
        final_caption = parsed['aria_caption'].strip()
    elif cap_text:
        # LLM didn't return JSON — use the raw text as caption fallback
        final_caption = cap_text.strip()[:300]
    else:
        # All else failed — fall back to first-pass caption
        final_caption = synth.get('aria_caption', '').strip()

    return {
        'verification_vision_prompt': VISION_PROMPT,
        'verification_vision_description': vision_text,
        'verification_vision_backend': vision_backend,
        'verification_vision_ms': vision_ms,
        'verification_caption_user_prompt': cap_user,
        'verification_caption_system_prompt': FINAL_CAPTION_SYSTEM,
        'verification_caption_llm_backend': cap_backend,
        'verification_caption_llm_attempts': cap_attempts,
        'verification_caption_llm_debug': cap_debug,
        'verification_caption_ms': cap_ms,
        'verification_caption_raw': cap_text,
        'final_aria_caption': final_caption,
    }


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

        # Post-render verification + caption rewrite. Vision LLM describes
        # the actual rendered image; strongest LLM rewrites the caption using
        # the picks + vision read so the caption only names things that
        # actually rendered. If scientist was supposed to be there but
        # Klein dropped them, vision won't see them, and the caption won't
        # mention them.
        t_verify_start = time.time()
        verification = verify_and_caption(synth, rendered['image_bytes'], debug=debug)
        verify_ms = int((time.time() - t_verify_start) * 1000)
        synth.update(verification)
    finally:
        if debug:
            set_request_log(None)

    synth['image_bytes'] = rendered['image_bytes']
    synth['render_provider'] = rendered['provider']
    synth['render_ms'] = rendered['ms']
    synth['render_total_ms'] = render_total_ms
    synth['used_size'] = rendered['used_size']
    synth['verification_total_ms'] = verify_ms

    if debug:
        synth['galactica_to_kumori_http'] = galactica_to_kumori_http or []
        synth['klein_debug_info'] = {'upstream_calls': rendered.get('upstream_calls', [])}
        synth.setdefault('pipeline_stage_log', []).append({
            'stage': 'klein_render',
            'timestamp': time.time(),
            'ms': render_total_ms,
            'provider': rendered.get('provider'),
            'output_bytes': len(rendered['image_bytes']),
            'used_size': rendered['used_size'],
        })
        synth['pipeline_stage_log'].append({
            'stage': 'vision_describe_rendered',
            'timestamp': time.time(),
            'ms': verification.get('verification_vision_ms'),
            'backend': verification.get('verification_vision_backend'),
            'chars': len(verification.get('verification_vision_description', '')),
        })
        synth['pipeline_stage_log'].append({
            'stage': 'final_caption_rewrite',
            'timestamp': time.time(),
            'ms': verification.get('verification_caption_ms'),
            'backend': verification.get('verification_caption_llm_backend'),
            'chars': len(verification.get('final_aria_caption', '')),
        })
    return synth
