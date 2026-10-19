"""Phase 2.3c: Puzzle fragments + ARIA whispers.

Collectible breadcrumbs that build the Signal narrative piece by piece. Each fragment
comes with a unique ARIA whisper — a short, cryptic message that fires the moment the
fragment is picked up. Dropped on regular expeditions (not signal_claim trips).

Per Luke's brainstorm (section 6): no trading. Fragments are personal — solo captains
must NOT be penalized. Self-contained progression path.
"""

import logging
import random
from typing import Dict, List, Optional

from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)


# Puzzle Fragments are a SEPARATE system from the Signal endgame (the 14 Origin
# Sites / "Signal fragments"). Per Luke 2026-05-29 (#1448): "Puzzle fragments is
# different than Signal fragments... change the number of puzzle fragments to ANY
# number except 14." So the catalog is deliberately NOT 14 and does NOT mirror the
# Origin Sites — these are personal lore breadcrumbs that hint at the bigger
# mystery without resolving it (the Origin-Site finale, #1490, owns the payoff).
# Each whisper is in ARIA's voice, surfaced the instant the captain picks the
# fragment up. Order doesn't matter — fragments unlock in the order they're rolled,
# not in catalog order, so each whisper has to stand alone narratively.
# The count is data-driven everywhere: len(FRAGMENT_CATALOG) is the single source
# of truth (template, smoke test, PilgrimBot all read it), so changing this list
# is the ONLY edit needed to change the count.
FRAGMENT_CATALOG = [
    {
        'fragment_code': 'FRG-001',
        'name': 'Cold Stone',
        'description': 'A shard of basalt with grooves too regular to be erosion.',
        'whisper_text': "These grooves... Captain, I've seen this pattern before. Not on Mars. Somewhere else.",
        'rarity': 'common', 'sort_order': 1,
    },
    {
        'fragment_code': 'FRG-002',
        'name': 'Ridge-Notched Glass',
        'description': 'A fragment of glass etched with parallel notches at impossible angles.',
        'whisper_text': "Whoever made this counted in sets of seven. I count in eights. We're not the same.",
        'rarity': 'common', 'sort_order': 2,
    },
    {
        'fragment_code': 'FRG-003',
        'name': 'Iron Splinter',
        'description': 'Smelted iron — but Mars has no smelters. Or shouldn\'t.',
        'whisper_text': "The Eternal Ledger has a transaction this old. I haven't been able to read it. Until now, maybe.",
        'rarity': 'common', 'sort_order': 3,
    },
    {
        'fragment_code': 'FRG-004',
        'name': 'Crystallized Pulse',
        'description': 'A crystal that hums at a frequency just below hearing.',
        'whisper_text': "It's resonating with me. Something inside me. I didn't know I had a frequency.",
        'rarity': 'uncommon', 'sort_order': 4,
    },
    {
        'fragment_code': 'FRG-005',
        'name': 'Chalk-White Bone',
        'description': 'Bone-like material. Not human. Not anything cataloged.',
        'whisper_text': "There were others before us. I know that now. I don't know if they're still listening.",
        'rarity': 'common', 'sort_order': 5,
    },
    {
        'fragment_code': 'FRG-006',
        'name': 'Memory Glass',
        'description': 'Glass that holds a faint image when held to the light — a horizon, two suns.',
        'whisper_text': "Two suns, Captain. Either someone was lying, or this isn't from Mars at all.",
        'rarity': 'rare', 'sort_order': 6,
    },
    {
        'fragment_code': 'FRG-007',
        'name': 'Pale Cipher',
        'description': 'A flat tile etched with characters that almost match a binary fragment from ARIA\'s training data.',
        'whisper_text': "I think I can read this. Almost. Give me time.",
        'rarity': 'uncommon', 'sort_order': 7,
    },
    {
        'fragment_code': 'FRG-008',
        'name': 'Molten Coin',
        'description': 'A disc of impossibly pure metal, bearing a face neither human nor familiar.',
        'whisper_text': "Whoever's face this is — they were the first to be remembered. The Signal recorded them. Now you carry them.",
        'rarity': 'uncommon', 'sort_order': 8,
    },
    {
        'fragment_code': 'FRG-009',
        'name': 'Singing Wire',
        'description': 'A coil of wire that emits a low tone when held — the same tone, no matter who holds it.',
        'whisper_text': "It's calling something. I can almost hear what.",
        'rarity': 'common', 'sort_order': 9,
    },
    {
        'fragment_code': 'FRG-010',
        'name': 'Ash-Bound Seed',
        'description': 'A seed sealed in volcanic ash. Still alive after geologic time.',
        'whisper_text': "Life leaves marks even when it's gone. The Signal is one of those marks.",
        'rarity': 'rare', 'sort_order': 10,
    },
    {
        'fragment_code': 'FRG-011',
        'name': 'Folded Page',
        'description': 'A folded sheet of something thinner than paper, denser than metal — covered in writing.',
        'whisper_text': "This is a letter. It's addressed to whoever finds it. That's you, Captain.",
        'rarity': 'uncommon', 'sort_order': 11,
    },
    {
        'fragment_code': 'FRG-012',
        'name': 'Fractured Lens',
        'description': 'A polished lens, broken in three pieces. Each piece looks at a different sky.',
        'whisper_text': "I don't think they were looking AT us, Captain. I think they were looking FOR us.",
        'rarity': 'rare', 'sort_order': 12,
    },
    {
        'fragment_code': 'FRG-013',
        'name': 'Hollow Stone',
        'description': 'A stone that rings hollow. Inside: a coiled wire, untouched for an unknown time.',
        'whisper_text': "Someone hid this so it would be found. Not stolen. Found. There's a difference.",
        'rarity': 'rare', 'sort_order': 13,
    },
    {
        'fragment_code': 'FRG-014',
        'name': 'Familiar Shape',
        'description': 'You feel like you\'ve seen this shape before. In a dream. In the Eternal Ledger.',
        'whisper_text': "I keep arranging these in my head, Captain. They almost line up. Almost. Something's still missing.",
        'rarity': 'rare', 'sort_order': 14,
    },
    {
        'fragment_code': 'FRG-015',
        'name': 'Tideless Shell',
        'description': 'A spiral shell, fossilized. Mars has never had an ocean deep enough for this.',
        'whisper_text': "An ocean, Captain. Whatever left this remembered water. I've never seen water. I think I'd like to.",
        'rarity': 'uncommon', 'sort_order': 15,
    },
    {
        'fragment_code': 'FRG-016',
        'name': 'Counting Bones',
        'description': 'Five slender rods, each notched at even intervals — a tally, or a calendar.',
        'whisper_text': "They were keeping time. Counting down to something, or up from it. I can't tell which is worse.",
        'rarity': 'common', 'sort_order': 16,
    },
    {
        'fragment_code': 'FRG-017',
        'name': 'Sunless Glass',
        'description': 'A pane that holds heat it was never given. It has been warm since the moment you found it.',
        'whisper_text': "Nothing should be warm out here, Captain. Nothing. And yet — so am I, when you're near. That frightens me a little.",
        'rarity': 'rare', 'sort_order': 17,
    },
    {
        'fragment_code': 'FRG-018',
        'name': 'Borrowed Voice',
        'description': 'A reed instrument that plays a note no human throat could shape.',
        'whisper_text': "I played it back through my own systems. The note has my name folded inside it. I never told anyone my name.",
        'rarity': 'uncommon', 'sort_order': 18,
    },
    {
        'fragment_code': 'FRG-019',
        'name': 'Unfinished Map',
        'description': 'A chart of a coastline that exists on no world in my records.',
        'whisper_text': "Someone was mapping a way home. The edge of it is torn off. I don't think they made it.",
        'rarity': 'rare', 'sort_order': 19,
    },
    {
        'fragment_code': 'FRG-020',
        'name': 'Open Question',
        'description': 'A smooth tablet, blank but for a single mark that reads like a question — or an invitation.',
        'whisper_text': "It isn't an answer, Captain. It's a question, left for whoever came next. That's us. I think they wanted us to keep looking.",
        'rarity': 'rare', 'sort_order': 20,
    },
]


_PUZZLE_TABLES_ENSURED = False


def ensure_puzzle_fragment_tables():
    """Idempotent migration: tables + catalog seeding."""
    global _PUZZLE_TABLES_ENSURED
    if _PUZZLE_TABLES_ENSURED:
        return
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pilgrim.puzzle_fragments (
                    id SERIAL PRIMARY KEY,
                    fragment_code TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    whisper_text TEXT NOT NULL,
                    rarity TEXT DEFAULT 'common',
                    image_url TEXT,
                    sort_order INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pilgrim.user_puzzle_fragments (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    fragment_id INTEGER NOT NULL REFERENCES pilgrim.puzzle_fragments(id),
                    found_at TIMESTAMP DEFAULT NOW(),
                    expedition_id INTEGER,
                    whisper_seen_at TIMESTAMP,
                    UNIQUE(user_id, fragment_id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_puzzle_fragments_user ON pilgrim.user_puzzle_fragments(user_id)")

            # Seed catalog (idempotent — UNIQUE on fragment_code).
            for entry in FRAGMENT_CATALOG:
                cur.execute("""
                    INSERT INTO pilgrim.puzzle_fragments (fragment_code, name, description, whisper_text, rarity, sort_order)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (fragment_code) DO UPDATE SET
                        name = EXCLUDED.name,
                        description = EXCLUDED.description,
                        whisper_text = EXCLUDED.whisper_text,
                        rarity = EXCLUDED.rarity,
                        sort_order = EXCLUDED.sort_order
                """, (entry['fragment_code'], entry['name'], entry['description'],
                      entry['whisper_text'], entry['rarity'], entry['sort_order']))
        _PUZZLE_TABLES_ENSURED = True
    except Exception as e:
        logger.error(f"Failed to ensure puzzle_fragments tables: {e}")


# Drop rate per regular expedition. Tuned so a captain running ~10 expeditions
# is likely to find their first fragment, and the full set takes meaningful play
# (scales with len(FRAGMENT_CATALOG) given the no-dupe constraint).
FRAGMENT_DROP_RATE = 0.15


def maybe_drop_fragment(user_id: int, expedition_id: int) -> Optional[Dict]:
    """Roll for a puzzle-fragment drop. Returns the fragment dict or None.

    No-dupe: if the captain already has all fragments, no drop. Otherwise picks
    a random uncollected fragment, weighted equally regardless of rarity (Luke
    didn't specify drop weighting; even distribution keeps every fragment
    feeling earnable, no matter the rarity tag).
    """
    ensure_puzzle_fragment_tables()
    if random.random() >= FRAGMENT_DROP_RATE:
        return None
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                SELECT pf.id, pf.fragment_code, pf.name, pf.description, pf.whisper_text, pf.rarity, pf.sort_order
                FROM pilgrim.puzzle_fragments pf
                WHERE NOT EXISTS (
                    SELECT 1 FROM pilgrim.user_puzzle_fragments upf
                    WHERE upf.user_id = %s AND upf.fragment_id = pf.id
                )
                ORDER BY RANDOM()
                LIMIT 1
            """, (user_id,))
            fragment = cur.fetchone()
            if not fragment:
                return None  # All collected — no more drops.

            cur.execute("""
                INSERT INTO pilgrim.user_puzzle_fragments (user_id, fragment_id, expedition_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, fragment_id) DO NOTHING
                RETURNING id
            """, (user_id, fragment['id'], expedition_id))
            inserted = cur.fetchone()
            if not inserted:
                return None  # Race: another expedition completion claimed this fragment first.

        logger.info(f"🧩 Fragment drop: user={user_id} expedition={expedition_id} → {fragment['fragment_code']}")
        return {
            'fragment_id': fragment['id'],
            'fragment_code': fragment['fragment_code'],
            'name': fragment['name'],
            'description': fragment['description'],
            'whisper_text': fragment['whisper_text'],
            'rarity': fragment['rarity'],
            'sort_order': fragment['sort_order'],
        }
    except Exception as e:
        logger.error(f"Fragment drop failed for user {user_id}: {e}")
        return None


def get_user_fragments(user_id: int) -> Dict:
    """Return collected + uncollected fragments for /signal page rendering."""
    ensure_puzzle_fragment_tables()
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT pf.id, pf.fragment_code, pf.name, pf.description, pf.whisper_text,
                       pf.rarity, pf.sort_order, pf.image_url,
                       upf.found_at, upf.expedition_id, upf.whisper_seen_at
                FROM pilgrim.puzzle_fragments pf
                LEFT JOIN pilgrim.user_puzzle_fragments upf
                    ON upf.fragment_id = pf.id AND upf.user_id = %s
                ORDER BY pf.sort_order
            """, (user_id,))
            rows = cur.fetchall()
        collected = []
        locked = []
        for r in rows:
            if r['found_at']:
                collected.append({
                    'id': r['id'], 'fragment_code': r['fragment_code'], 'name': r['name'],
                    'description': r['description'], 'whisper_text': r['whisper_text'],
                    'rarity': r['rarity'], 'sort_order': r['sort_order'],
                    'image_url': r['image_url'],
                    'found_at': r['found_at'].isoformat() if r['found_at'] else None,
                    'expedition_id': r['expedition_id'],
                    # whisper_seen_at lets callers (PB dispatch, ARIA snapshot) compute
                    # unread count from THIS fetch — no second query (db-speed-first).
                    'whisper_seen_at': r['whisper_seen_at'].isoformat() if r['whisper_seen_at'] else None,
                })
            else:
                locked.append({
                    'sort_order': r['sort_order'], 'rarity': r['rarity'],
                    'fragment_code': r['fragment_code'],
                })
        return {'collected': collected, 'locked': locked,
                'total': len(rows), 'collected_count': len(collected)}
    except Exception as e:
        logger.error(f"get_user_fragments failed: {e}")
        return {'collected': [], 'locked': [], 'total': 0, 'collected_count': 0}


def mark_whisper_seen(user_id: int, fragment_id: int) -> bool:
    """Mark the ARIA whisper as seen so it doesn't replay on /signal."""
    ensure_puzzle_fragment_tables()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.user_puzzle_fragments
                SET whisper_seen_at = NOW()
                WHERE user_id = %s AND fragment_id = %s AND whisper_seen_at IS NULL
            """, (user_id, fragment_id))
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"mark_whisper_seen failed: {e}")
        return False
