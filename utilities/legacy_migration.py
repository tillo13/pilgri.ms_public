"""
Legacy Shop → Upgrade System Migration
Converts old user_upgrades records to player_upgrades records.
Runs lazily (once per user per app session).
"""
import logging
from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)

# Old item_id → (category, item_key, level) in new system
# For chained items, highest owned wins (max level taken per path)
LEGACY_ITEM_MAP = {
    # Power chain → power/generator (levels matched by passive_income_mult value)
    'solar_tier2': ('power', 'generator', 1),
    'solar_tier3': ('power', 'generator', 3),
    'nuclear_rtg': ('power', 'generator', 5),
    'fusion_reactor': ('power', 'generator', 7),
    # Rover chain → vehicles/rover (default_level=1, only higher tiers need migration)
    'rover_enhanced': ('vehicles', 'rover', 2),
    'rover_advanced': ('vehicles', 'rover', 3),
    'rover_elite': ('vehicles', 'rover', 4),
    # Scanner chain → equipment/scanner (default_level=1)
    'scanner_deep': ('equipment', 'scanner', 2),
    'scanner_quantum': ('equipment', 'scanner', 3),
    # Life support → equipment/life_support
    'life_support_basic': ('equipment', 'life_support', 1),
    'life_support_advanced': ('equipment', 'life_support', 2),
    # Cargo → equipment/cargo
    'cargo_bay': ('equipment', 'cargo', 1),
    'cargo_refrigerated': ('equipment', 'cargo', 2),
    # Research → research/research
    'research_lab': ('research', 'research', 1),
    'research_advanced': ('research', 'research', 2),
    # Automation split (bug #1149): maintenance path = dust, mining path = passive income
    'maintenance_drone': ('maintenance', 'maintenance', 3),  # grants dust immunity
    'mining_drone': ('mining', 'mining', 1),                 # first tier of passive income
}

# Suits are independent (no chain) - count owned = level
LEGACY_SUIT_ITEMS = ['suit_exploration', 'suit_logistics', 'suit_command']

_migrated_users = set()


def ensure_legacy_migrated(user_id: int):
    """Check and migrate old shop purchases to player_upgrades. Runs once per session."""
    if user_id in _migrated_users:
        return
    _migrated_users.add(user_id)

    try:
        _do_migration(user_id)
    except Exception as e:
        logger.error(f"Legacy migration failed for user {user_id}: {e}")


def _do_migration(user_id: int):
    """Read old user_upgrades and insert into player_upgrades where missing."""
    with db_cursor() as cur:
        # Read old purchases
        cur.execute("""
            SELECT item_id, quantity FROM pilgrim.user_upgrades
            WHERE user_id = %s AND status = 'active'
        """, (user_id,))
        old_items = {row['item_id']: row['quantity'] for row in cur.fetchall()}

    if not old_items:
        return

    # Build target levels per (category, item_key) - take max for chained items
    targets = {}
    for item_id, (cat, key, level) in LEGACY_ITEM_MAP.items():
        if item_id in old_items:
            path = (cat, key)
            targets[path] = max(targets.get(path, 0), level)

    # Suits: count how many are owned
    suit_count = sum(1 for s in LEGACY_SUIT_ITEMS if s in old_items)
    if suit_count > 0:
        targets[('gear', 'suit')] = suit_count

    if not targets:
        return

    # Insert into player_upgrades where no record exists or level is lower
    migrated = []
    with db_cursor(commit=True) as cur:
        for (cat, key), level in targets.items():
            cur.execute("""
                SELECT level FROM pilgrim.player_upgrades
                WHERE user_id = %s AND category = %s AND item_key = %s
            """, (user_id, cat, key))
            row = cur.fetchone()

            if row and row['level'] >= level:
                continue  # Already at same or higher level

            if row:
                cur.execute("""
                    UPDATE pilgrim.player_upgrades SET level = %s
                    WHERE user_id = %s AND category = %s AND item_key = %s
                """, (level, user_id, cat, key))
            else:
                cur.execute("""
                    INSERT INTO pilgrim.player_upgrades (user_id, category, item_key, level)
                    VALUES (%s, %s, %s, %s)
                """, (user_id, cat, key, level))
            migrated.append(f"{cat}/{key}=Lv{level}")

    if migrated:
        logger.info(f"Migrated legacy purchases for user {user_id}: {', '.join(migrated)}")
