"""Email notification, FOMO data, and captain quote database operations."""

import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

from utilities.postgres_utils import db_cursor, _fetchone, _fetchall, _update
from utilities.mars_math import calculate_mars_distance

logger = logging.getLogger(__name__)


# ============================================================================
# EMAIL NOTIFICATION QUERIES
# ============================================================================

def get_users_with_completed_expeditions() -> List[Dict]:
    """Get users who have expeditions that completed but haven't been notified"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT DISTINCT u.id, u.email, u.given_name, u.name,
                       e.id as expedition_id, e.destination_name, e.completed_at
                FROM pilgrim.users u
                JOIN pilgrim.expeditions e ON e.user_id = u.id
                WHERE e.status = 'completed'
                  AND e.notified_at IS NULL
                  AND u.email IS NOT NULL
                  AND u.email_verified = true
            """)
            return _fetchall(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get users with completed expeditions: {e}")
        return []

def mark_expedition_notified(expedition_id: int) -> bool:
    """Mark an expedition as having sent notification"""
    return _update('expeditions', 'notified_at = NOW()', 'id = %s', (expedition_id,), 'expedition notified')

def get_inactive_users(days_inactive: int = 3) -> List[Dict]:
    """Get users who haven't logged in for X days and have pending activity"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT u.id, u.email, u.given_name, u.name, u.last_login,
                       EXTRACT(DAY FROM NOW() - u.last_login) as days_away,
                       (SELECT COUNT(*) FROM pilgrim.expeditions e
                        WHERE e.user_id = u.id AND e.status = 'completed') as pending_expeditions,
                       (SELECT COUNT(*) FROM pilgrim.expedition_discoveries ed
                        JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                        WHERE e.user_id = u.id AND ed.claimed_by_user = false) as unclaimed_discoveries
                FROM pilgrim.users u
                WHERE u.last_login < NOW() - INTERVAL '%s days'
                  AND u.email IS NOT NULL
                  AND u.email_verified = true
                  AND (u.last_nudge_email IS NULL OR u.last_nudge_email < NOW() - INTERVAL '7 days')
            """, (days_inactive,))
            return _fetchall(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get inactive users: {e}")
        return []

def mark_user_nudged(user_id: int) -> bool:
    """Mark user as having received a nudge email"""
    return _update('users', 'last_nudge_email = NOW()', 'id = %s', (user_id,), 'user nudged')

def get_user_fomo_data(user_id: int) -> Dict:
    """
    Get all FOMO-inducing data for re-engagement emails.
    Returns progress toward goals, what they're missing, social comparison, etc.
    """
    try:
        with db_cursor() as cur:
            # Get user's last login time and colony location
            cur.execute("""
                SELECT last_login, home_mars_lat, home_mars_lon FROM pilgrim.users WHERE id = %s
            """, (user_id,))
            user_row = cur.fetchone()
            last_login = user_row['last_login'] if user_row else None
            colony_lat = float(user_row['home_mars_lat']) if user_row and user_row.get('home_mars_lat') else -4.5  # Default: Gale Crater
            colony_lon = float(user_row['home_mars_lon']) if user_row and user_row.get('home_mars_lon') else 137.4

            # Get user's current Sepolia balance (table is sepolia_assets, column is is_primary_wallet)
            cur.execute("""
                SELECT COALESCE(current_balance_eth, 0) * 10000000 as balance_display
                FROM pilgrim.sepolia_assets
                WHERE user_id = %s AND is_primary_wallet = true
            """, (user_id,))
            balance_row = cur.fetchone()
            current_balance = float(balance_row['balance_display']) if balance_row else 0

            # Get user's owned upgrades
            cur.execute("""
                SELECT item_id FROM pilgrim.user_upgrades WHERE user_id = %s
            """, (user_id,))
            owned_upgrades = [r['item_id'] for r in cur.fetchall()]

            # Get user's infrastructure
            cur.execute("""
                SELECT structure_type, status FROM pilgrim.colony_infrastructure WHERE user_id = %s
            """, (user_id,))
            owned_infrastructure = {r['structure_type']: r['status'] for r in cur.fetchall()}

            # Get total discoveries count and rarity breakdown
            cur.execute("""
                SELECT
                    COUNT(*) as total_discoveries,
                    COUNT(*) FILTER (WHERE di.rarity = 'legendary') as legendary_count,
                    COUNT(*) FILTER (WHERE di.rarity = 'rare') as rare_count,
                    COALESCE(SUM(ed.enhanced_value), 0) as total_value
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
                WHERE e.user_id = %s AND ed.claimed_by_user = true
            """, (user_id,))
            discovery_stats = cur.fetchone() or {}

            # Get expedition stats
            cur.execute("""
                SELECT
                    COUNT(*) as total_expeditions,
                    COUNT(*) FILTER (WHERE status = 'completed') as completed,
                    COUNT(*) FILTER (WHERE status = 'in_progress') as active
                FROM pilgrim.expeditions WHERE user_id = %s
            """, (user_id,))
            expedition_stats = cur.fetchone() or {}

            # Get global stats for social comparison
            cur.execute("""
                SELECT
                    COUNT(DISTINCT e.user_id) as active_commanders,
                    COUNT(*) FILTER (WHERE di.rarity = 'legendary' AND ed.created_at > NOW() - INTERVAL '7 days') as legendary_finds_this_week,
                    COUNT(*) FILTER (WHERE di.rarity = 'rare' AND ed.created_at > NOW() - INTERVAL '7 days') as rare_finds_this_week
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
                WHERE ed.created_at > NOW() - INTERVAL '7 days'
            """)
            global_stats = cur.fetchone() or {}

            # Get infrastructure PENDING income with BREAKDOWN by structure
            cur.execute("""
                SELECT
                    structure_type, generation_rate,
                    COALESCE(last_payout_at, build_completed_at, created_at) as last_payout,
                    COALESCE(total_generated, 0) as total_generated
                FROM pilgrim.colony_infrastructure
                WHERE user_id = %s AND status = 'active' AND generates_resource = 'sepolia'
            """, (user_id,))
            infra_rows = cur.fetchall()

            pending_income = 0.0
            total_all_time = 0.0
            infrastructure_breakdown = []
            for row in infra_rows:
                total_all_time += float(row.get('total_generated', 0))
                last_payout = row.get('last_payout')
                hourly_rate = float(row.get('generation_rate', 0))
                struct_pending = 0.0
                if last_payout:
                    hours_elapsed = (datetime.utcnow() - last_payout).total_seconds() / 3600
                    struct_pending = hourly_rate * hours_elapsed
                    pending_income += struct_pending
                infrastructure_breakdown.append({
                    'structure_type': row.get('structure_type'),
                    'hourly_rate': hourly_rate,
                    'pending': round(struct_pending, 2),
                    'last_payout': last_payout
                })

            # Get active expeditions with time remaining (join mars_mappings for destination image/link/coords)
            cur.execute("""
                SELECT e.id, e.destination_name, e.destination_type, e.distance_km,
                       e.departed_at, e.arrives_at, e.status, mm.image_url as destination_image_url,
                       mm.link as destination_link, mm.latitude as destination_lat, mm.longitude as destination_lon
                FROM pilgrim.expeditions e
                LEFT JOIN pilgrim.mars_mappings mm ON LOWER(e.destination_name) = LOWER(mm.name)
                WHERE e.user_id = %s AND e.status = 'traveling'
                ORDER BY e.departed_at DESC
            """, (user_id,))
            active_expeditions = []
            for exp in cur.fetchall():
                departed = exp.get('departed_at')
                arrives = exp.get('arrives_at')
                if departed and arrives:
                    total_secs = (arrives - departed).total_seconds()
                    elapsed = (datetime.now() - departed).total_seconds()
                    remaining_secs = max(0, (arrives - datetime.now()).total_seconds())
                    progress_pct = min(100, (elapsed / total_secs) * 100) if total_secs > 0 else 100
                else:
                    remaining_secs = 0
                    progress_pct = 100
                active_expeditions.append({
                    'id': exp.get('id'),
                    'destination_name': exp.get('destination_name'),
                    'destination_type': exp.get('destination_type'),
                    'distance_km': exp.get('distance_km'),
                    'remaining_seconds': int(remaining_secs),
                    'progress_pct': round(progress_pct, 1),
                    'destination_image_url': exp.get('destination_image_url'),
                    'destination_link': exp.get('destination_link'),
                    'destination_lat': exp.get('destination_lat'),
                    'destination_lon': exp.get('destination_lon')
                })

            # Get nearby destinations user hasn't visited recently (for allure)
            cur.execute("""
                SELECT DISTINCT destination_name FROM pilgrim.expeditions
                WHERE user_id = %s
            """, (user_id,))
            visited = [r['destination_name'] for r in cur.fetchall()]

            # Get some interesting Mars destinations they could visit (from mars_mappings)
            # Strategy: Get 2 with interesting origins + 1 that can be unknown
            # "Interesting" = origin doesn't contain 'albedo' (generic naming)
            # Images are generated on-demand if missing
            suggested_destinations = []
            try:
                # First, get 2 destinations with interesting (non-albedo) origins
                # Don't require image_url - we'll generate on demand
                if visited:
                    cur.execute("""
                        SELECT name, type, latitude, longitude, diameter_km, origin, image_url, link
                        FROM pilgrim.mars_mappings
                        WHERE name != ALL(%s)
                        AND origin IS NOT NULL
                        AND origin NOT ILIKE '%%albedo%%'
                        ORDER BY
                            image_url IS NOT NULL DESC,
                            CASE
                                WHEN type ILIKE '%%chasma%%' THEN 1
                                WHEN type ILIKE '%%mons%%' THEN 2
                                WHEN type ILIKE '%%crater%%' AND COALESCE(diameter_km, 0) > 50 THEN 3
                                ELSE 4
                            END,
                            RANDOM()
                        LIMIT 2
                    """, (visited,))
                else:
                    cur.execute("""
                        SELECT name, type, latitude, longitude, diameter_km, origin, image_url, link
                        FROM pilgrim.mars_mappings
                        WHERE origin IS NOT NULL
                        AND origin NOT ILIKE '%%albedo%%'
                        ORDER BY
                            image_url IS NOT NULL DESC,
                            CASE
                                WHEN type ILIKE '%%chasma%%' THEN 1
                                WHEN type ILIKE '%%mons%%' THEN 2
                                WHEN type ILIKE '%%crater%%' AND COALESCE(diameter_km, 0) > 50 THEN 3
                                ELSE 4
                            END,
                            RANDOM()
                        LIMIT 2
                    """)
                interesting_dests = [dict(r) for r in cur.fetchall()]
                interesting_names = [d['name'] for d in interesting_dests]

                # Then get 1 more (can be any origin) to fill the 3rd slot
                exclude_list = (visited or []) + interesting_names
                cur.execute("""
                    SELECT name, type, latitude, longitude, diameter_km, origin, image_url, link
                    FROM pilgrim.mars_mappings
                    WHERE name != ALL(%s)
                    ORDER BY
                        image_url IS NOT NULL DESC,
                        CASE
                            WHEN type ILIKE '%%chasma%%' THEN 1
                            WHEN type ILIKE '%%mons%%' THEN 2
                            WHEN type ILIKE '%%crater%%' AND COALESCE(diameter_km, 0) > 50 THEN 3
                            ELSE 4
                        END,
                        RANDOM()
                    LIMIT 1
                """, (exclude_list,))
                any_dest = [dict(r) for r in cur.fetchall()]

                suggested_destinations = interesting_dests + any_dest

                # Generate images on-demand for destinations that don't have one
                try:
                    from tools.mars_location_image_generator import generate_location_image
                    for dest in suggested_destinations:
                        if not dest.get('image_url'):
                            logger.info(f"Generating image on-demand for: {dest['name']}")
                            result = generate_location_image(dest['name'])
                            if result.get('success'):
                                dest['image_url'] = result['image_url']
                                logger.info(f"Generated image for {dest['name']}: {result['image_url']}")
                except Exception as gen_err:
                    logger.warning(f"Could not generate destination images: {gen_err}")

                # Calculate distance from colony to each destination (Mars great circle)
                for dest in suggested_destinations:
                    dest_lat = float(dest.get('latitude', 0))
                    dest_lon = float(dest.get('longitude', 0))
                    dest['distance_km'] = round(calculate_mars_distance(colony_lat, colony_lon, dest_lat, dest_lon), 1)
            except Exception as dest_err:
                logger.warning(f"Could not fetch suggested destinations: {dest_err}")

            # Add competition stats to each suggested destination
            # (how many other explorers, total discoveries found there)
            try:
                for dest in suggested_destinations:
                    dest_name = dest.get('name')
                    if not dest_name:
                        continue

                    # Get stats for this destination across all users
                    cur.execute("""
                        SELECT
                            COUNT(DISTINCT e.user_id) as explorer_count,
                            COUNT(ed.id) as total_discoveries,
                            COUNT(CASE WHEN di.rarity = 'legendary' THEN 1 END) as legendary_finds,
                            COUNT(CASE WHEN di.rarity = 'rare' THEN 1 END) as rare_finds
                        FROM pilgrim.expeditions e
                        LEFT JOIN pilgrim.expedition_discoveries ed ON ed.expedition_id = e.id
                        LEFT JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
                        WHERE e.destination_name = %s AND e.status = 'complete'
                    """, (dest_name,))
                    stats = cur.fetchone()

                    if stats:
                        dest['explorer_count'] = stats.get('explorer_count', 0) or 0
                        dest['total_discoveries'] = stats.get('total_discoveries', 0) or 0
                        dest['legendary_finds'] = stats.get('legendary_finds', 0) or 0
                        dest['rare_finds'] = stats.get('rare_finds', 0) or 0
                    else:
                        dest['explorer_count'] = 0
                        dest['total_discoveries'] = 0
                        dest['legendary_finds'] = 0
                        dest['rare_finds'] = 0

                    # Check if THIS user has explored this destination
                    cur.execute("""
                        SELECT COUNT(*) as visit_count
                        FROM pilgrim.expeditions
                        WHERE user_id = %s AND destination_name = %s AND status = 'complete'
                    """, (user_id, dest_name))
                    user_visit = cur.fetchone()
                    dest['user_visited'] = (user_visit.get('visit_count', 0) or 0) > 0

            except Exception as comp_err:
                logger.warning(f"Could not fetch destination competition stats: {comp_err}")

            # Get global expedition stats (user's % of total discoveries, total explorers, closest competitor)
            try:
                # Get user's discovery count and total discovery count across all users
                cur.execute("""
                    SELECT
                        (SELECT COUNT(*) FROM pilgrim.expedition_discoveries ed
                         JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                         WHERE e.user_id = %s) as user_discoveries,
                        (SELECT COUNT(*) FROM pilgrim.expedition_discoveries) as total_discoveries,
                        (SELECT COUNT(DISTINCT user_id) FROM pilgrim.expeditions WHERE status = 'complete') as total_explorers
                """, (user_id,))
                stats_row = cur.fetchone()
                user_discoveries = stats_row.get('user_discoveries', 0) or 0
                total_all_discoveries = stats_row.get('total_discoveries', 0) or 0
                total_explorers = stats_row.get('total_explorers', 0) or 0

                # Calculate percentage with 3 decimal places
                if total_all_discoveries > 0:
                    user_discovery_pct = (user_discoveries / total_all_discoveries) * 100
                else:
                    user_discovery_pct = 0.0

                # Find closest competitor (next person ahead or behind in discovery count)
                competitor_pct = 0.0
                competitor_ahead = True
                try:
                    # Get the person just ahead of user (more discoveries)
                    cur.execute("""
                        SELECT COUNT(ed.id) as discoveries
                        FROM pilgrim.expeditions e
                        JOIN pilgrim.expedition_discoveries ed ON ed.expedition_id = e.id
                        WHERE e.user_id != %s
                        GROUP BY e.user_id
                        HAVING COUNT(ed.id) > %s
                        ORDER BY COUNT(ed.id) ASC
                        LIMIT 1
                    """, (user_id, user_discoveries))
                    ahead_row = cur.fetchone()

                    if ahead_row and total_all_discoveries > 0:
                        competitor_pct = (ahead_row['discoveries'] / total_all_discoveries) * 100
                        competitor_ahead = True
                    else:
                        # No one ahead, find the person just behind (fewer discoveries)
                        cur.execute("""
                            SELECT COUNT(ed.id) as discoveries
                            FROM pilgrim.expeditions e
                            JOIN pilgrim.expedition_discoveries ed ON ed.expedition_id = e.id
                            WHERE e.user_id != %s
                            GROUP BY e.user_id
                            HAVING COUNT(ed.id) < %s
                            ORDER BY COUNT(ed.id) DESC
                            LIMIT 1
                        """, (user_id, user_discoveries))
                        behind_row = cur.fetchone()
                        if behind_row and total_all_discoveries > 0:
                            competitor_pct = (behind_row['discoveries'] / total_all_discoveries) * 100
                            competitor_ahead = False
                except Exception as comp_pct_err:
                    logger.warning(f"Could not fetch competitor stats: {comp_pct_err}")

                global_expedition_stats = {
                    'user_discoveries': user_discoveries,
                    'total_discoveries': total_all_discoveries,
                    'user_discovery_pct': round(user_discovery_pct, 3),
                    'total_explorers': total_explorers,
                    'competitor_pct': round(competitor_pct, 3),
                    'competitor_ahead': competitor_ahead
                }
            except Exception as ges_err:
                logger.warning(f"Could not fetch global expedition stats: {ges_err}")
                global_expedition_stats = {'user_discoveries': 0, 'total_discoveries': 0, 'user_discovery_pct': 0.0, 'total_explorers': 0, 'competitor_pct': 0.0, 'competitor_ahead': True}

            # Get TOTAL count of unclaimed discoveries
            cur.execute("""
                SELECT COUNT(*) as cnt
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                WHERE e.user_id = %s AND ed.unlocked_at IS NOT NULL AND ed.claimed_by_user = false
            """, (user_id,))
            pending_discoveries_count = cur.fetchone()['cnt']

            # Get pending discovery previews (top 3 unclaimed with images)
            cur.execute("""
                SELECT di.item_name, di.rarity, di.image_url, di.description,
                       ed.enhanced_value, di.base_scientific_value as scientific_value, e.destination_name
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                WHERE e.user_id = %s AND ed.unlocked_at IS NOT NULL AND ed.claimed_by_user = false
                ORDER BY di.rarity = 'legendary' DESC, di.rarity = 'rare' DESC, ed.enhanced_value DESC
                LIMIT 3
            """, (user_id,))
            pending_discoveries = [dict(row) for row in cur.fetchall()]

            # Get user's assigned scientist
            scientist_info = None
            try:
                cur.execute("SELECT scientist_key FROM pilgrim.users WHERE id = %s", (user_id,))
                sci_row = cur.fetchone()
                if sci_row and sci_row.get('scientist_key'):
                    from config import COLONY_SCIENTISTS
                    key = sci_row['scientist_key']
                    if key in COLONY_SCIENTISTS:
                        scientist_info = {'key': key, **COLONY_SCIENTISTS[key]}
            except Exception as sci_err:
                logger.warning(f"Could not get scientist info: {sci_err}")

            # Get xenobiology research points (from users table)
            research_points = 0
            try:
                cur.execute("""
                    SELECT research_points FROM pilgrim.users
                    WHERE id = %s
                """, (user_id,))
                rp_row = cur.fetchone()
                if rp_row:
                    research_points = rp_row.get('research_points', 0) or 0
            except Exception as rp_err:
                logger.warning(f"Could not get research points: {rp_err}")

            # Calculate total scientific value of discoveries
            total_scientific_value = 0
            try:
                cur.execute("""
                    SELECT COALESCE(SUM(di.base_scientific_value), 0) as total_scientific
                    FROM pilgrim.expedition_discoveries ed
                    JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                    JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
                    WHERE e.user_id = %s AND ed.claimed_by_user = true
                """, (user_id,))
                sv_row = cur.fetchone()
                if sv_row:
                    total_scientific_value = float(sv_row.get('total_scientific', 0) or 0)
            except Exception as sv_err:
                logger.warning(f"Could not get scientific value: {sv_err}")

            # Get primary captain data (name, image, stats) for email header
            # Captain data is stored in replicate_assets table
            # Fall back to user's given_name if captain name not set
            # Priority: is_primary_character=true first, then most recent character_image
            commander_info = None
            try:
                cur.execute("""
                    SELECT ra.id, ra.commander_name, ra.gcs_url,
                           ra.commander_leadership, ra.commander_strategy, ra.commander_exploration,
                           ra.commander_logistics, ra.commander_charisma,
                           u.given_name as user_name
                    FROM pilgrim.replicate_assets ra
                    JOIN pilgrim.users u ON ra.user_id = u.id
                    WHERE ra.user_id = %s AND ra.asset_type IN ('character_image', 'edited_image')
                          AND ra.is_deleted = false
                    ORDER BY ra.is_primary_character DESC, ra.id DESC
                    LIMIT 1
                """, (user_id,))
                cmd_row = cur.fetchone()
                if cmd_row:
                    # Use commander_name if set, otherwise fall back to user's name
                    name = cmd_row.get('commander_name') or cmd_row.get('user_name') or 'Captain'
                    commander_info = {
                        'id': cmd_row.get('id'),
                        'name': name,
                        'image_url': cmd_row.get('gcs_url'),
                        'stats': {
                            'leadership': cmd_row.get('commander_leadership', 0) or 0,
                            'strategy': cmd_row.get('commander_strategy', 0) or 0,
                            'exploration': cmd_row.get('commander_exploration', 0) or 0,
                            'logistics': cmd_row.get('commander_logistics', 0) or 0,
                            'charisma': cmd_row.get('commander_charisma', 0) or 0
                        }
                    }
            except Exception as cmd_err:
                logger.warning(f"Could not get captain info: {cmd_err}")

            return {
                'user_id': user_id,  # Include user_id for downstream use (e.g., saving quotes)
                'current_balance': current_balance,
                'last_login': last_login,
                'owned_upgrades': owned_upgrades,
                'owned_infrastructure': owned_infrastructure,
                'discovery_stats': {
                    'total': discovery_stats.get('total_discoveries', 0),
                    'legendary': discovery_stats.get('legendary_count', 0),
                    'rare': discovery_stats.get('rare_count', 0),
                    'total_value': float(discovery_stats.get('total_value', 0))
                },
                'expedition_stats': {
                    'total': expedition_stats.get('total_expeditions', 0),
                    'completed': expedition_stats.get('completed', 0),
                    'active': expedition_stats.get('active', 0)
                },
                'global_stats': {
                    'active_commanders': global_stats.get('active_commanders', 0),
                    'legendary_this_week': global_stats.get('legendary_finds_this_week', 0),
                    'rare_this_week': global_stats.get('rare_finds_this_week', 0)
                },
                'infrastructure_generated': round(pending_income, 2),
                'infrastructure_total_all_time': round(total_all_time, 2),
                'infrastructure_breakdown': infrastructure_breakdown,
                'active_expeditions': active_expeditions,
                'suggested_destinations': suggested_destinations,
                'pending_discoveries': pending_discoveries,
                'pending_discoveries_count': pending_discoveries_count,
                'colony_lat': colony_lat,
                'colony_lon': colony_lon,
                'scientist': scientist_info,
                'research_points': research_points,
                'total_scientific_value': total_scientific_value,
                'commander': commander_info,
                'global_expedition_stats': global_expedition_stats
            }
    except Exception as e:
        logger.error(f"❌ Failed to get user FOMO data: {e}")
        return {}


# ============================================================================
# CAPTAIN QUOTES
# ============================================================================

def save_commander_quote(user_id: int, commander_name: str, quote: str,
                        context_type: str = 'email', context_data: Dict = None) -> Optional[int]:
    """
    Save a captain quote to the database for the captain's log.

    Args:
        user_id: The user/captain's ID
        commander_name: The captain's display name
        quote: The generated quote text
        context_type: Type of quote context ('email', 'expedition', 'discovery', etc.)
        context_data: Optional dict with relevant context (stats, destination, etc.)

    Returns:
        The quote ID if successful, None otherwise
    """
    try:
        import json
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.commander_quotes
                    (user_id, commander_name, quote, context_type, context_data)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (user_id, commander_name, quote, context_type,
                  json.dumps(context_data) if context_data else None))
            result = cur.fetchone()
            return result['id'] if result else None
    except Exception as e:
        logger.error(f"❌ Failed to save captain quote: {e}")
        return None


def get_commander_quotes(user_id: int, limit: int = 50) -> List[Dict]:
    """
    Get captain quotes for a user's captain's log.

    Args:
        user_id: The user ID
        limit: Max quotes to return (default 50)

    Returns:
        List of quote dicts, most recent first
    """
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, commander_name, quote, context_type, context_data, created_at
                FROM pilgrim.commander_quotes
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (user_id, limit))
            return _fetchall(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get captain quotes: {e}")
        return []


def get_commander_quote_count(user_id: int) -> int:
    """Get total number of captain quotes for a user."""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) as count FROM pilgrim.commander_quotes WHERE user_id = %s
            """, (user_id,))
            result = cur.fetchone()
            return result['count'] if result else 0
    except Exception as e:
        logger.error(f"❌ Failed to get quote count: {e}")
        return 0
