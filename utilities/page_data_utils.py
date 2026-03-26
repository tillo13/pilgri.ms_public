"""Page data loading utilities for template rendering."""

import hashlib
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


def get_command_page_data(user_id):
    """
    Get all data needed for the colony/command page.
    Consolidates ~80 lines of logic from app.py.

    Returns:
        dict with all template variables for command.html
    """
    from utilities.postgres_utils import get_asset_edit_chain, get_user_scientist, assign_scientist_to_user, get_user_research_data
    from utilities.depot_utils import get_commander_and_stats, get_fast_balance_and_wallet_info, get_pricing_info, get_latest_character_image, eth_to_display
    from utilities.postgres_utils import get_user_replicate_assets
    from utilities.shop_utils import get_effective_commander_stats

    primary_commander, base_stats = get_commander_and_stats(user_id)
    # Apply EVA Suit stat bonuses for display
    commander_stats = get_effective_commander_stats(user_id, base_stats) if base_stats else None

    # Get research bonuses for stat display
    research_data = get_user_research_data(user_id)
    stat_bonuses = research_data.get('stat_bonuses', {}) if research_data else {}

    # Get or assign scientist
    scientist = get_user_scientist(user_id)
    if not scientist:
        assign_scientist_to_user(user_id)
        scientist = get_user_scientist(user_id)
    total_balance, wallet_info, _ = get_fast_balance_and_wallet_info(user_id)  # FAST: no blockchain

    # Single query for both character_image and edited_image
    from utilities.postgres_utils import get_user_commander_images
    commander_images = get_user_commander_images(user_id, limit=50)
    all_images = commander_images['all_images']  # Already sorted by created_at desc
    all_videos = get_user_replicate_assets(user_id, asset_type='character_video', limit=50)

    has_commander = len(all_images) > 0
    commander = character_url = character_video_url = None
    image_history = []
    original_image_url = current_asset_id = None
    all_commanders = []

    if has_commander:
        # Use the PRIMARY/ACTIVE captain, not just the latest by date
        if primary_commander:
            commander = primary_commander
            character_url = commander['gcs_url']
            current_asset_id = commander['id']
        else:
            # Fallback to latest if no primary set
            try:
                character_url, current_asset_id = get_latest_character_image(user_id)
                commander = next((img for img in all_images if img['id'] == current_asset_id), all_images[0])
            except:
                commander = all_images[0]
                character_url, current_asset_id = commander['gcs_url'], commander['id']

        # Get video linked to the active captain, or latest video
        linked_video = next((v for v in all_videos if v.get('parent_asset_id') == current_asset_id), None)
        if linked_video:
            character_video_url = linked_video['gcs_url']
        elif all_videos:
            character_video_url = all_videos[0]['gcs_url']

        chain = get_asset_edit_chain(current_asset_id)
        image_history = [asset['gcs_url'] for asset in chain]
        original_image_url = image_history[0] if image_history else None

        for img in all_images:
            linked_vid = next((v for v in all_videos if v.get('parent_asset_id') == img['id']), None)
            all_commanders.append({
                'id': img['id'], 'image_url': img['gcs_url'], 'asset_type': img['asset_type'],
                'is_original': img.get('is_original', False), 'edit_number': img.get('edit_number'),
                'created_at': img['created_at'], 'is_active': img.get('is_primary_character', False),
                'video_url': linked_vid['gcs_url'] if linked_vid else None,
                'prompt_used': img.get('prompt_used')
            })

    # Check if user has research station for crew page link
    from utilities.tech_utils import _has_research_station
    has_research_station = _has_research_station(user_id)

    # Scientist research stats for crew page
    scientist_research = {'sv_rate': 0, 'sv_total': 0, 'sv_available': 0, 'sv_accumulated': 0}
    if scientist and has_research_station:
        from utilities.postgres_utils import get_passive_sv
        from utilities.tech_utils import _get_available_sv
        from utilities.infrastructure_utils import calculate_accumulated_income
        scientist_research['sv_rate'] = 2.0  # From research_station config
        scientist_research['sv_total'] = int(get_passive_sv(user_id))
        scientist_research['sv_available'] = _get_available_sv(user_id)
        calc = calculate_accumulated_income(user_id)
        scientist_research['sv_accumulated'] = round(calc.get('sv_accumulated', 0), 1)

    # Get base coordinates for trail map centering
    from utilities.infrastructure_utils import get_or_set_user_mars_home
    base_coords = get_or_set_user_mars_home(user_id)

    return {
        'has_commander': has_commander, 'commander': commander, 'character_url': character_url,
        'character_video_url': character_video_url, 'commander_stats': commander_stats,
        'stat_bonuses': stat_bonuses,
        'current_balance': total_balance, 'wallet_info': wallet_info, 'pricing': get_pricing_info(),
        'image_history': image_history, 'original_image_url': original_image_url,
        'current_asset_id': current_asset_id, 'all_commanders': all_commanders,
        'scientist': scientist, 'has_research_station': has_research_station,
        'scientist_research': scientist_research, 'base_coords': base_coords,
        'all_scientists': _get_all_scientists_with_bonuses(),
    }

def _get_all_scientists_with_bonuses():
    """Get all scientists with their research branch bonuses for the swap modal."""
    from config import COLONY_SCIENTISTS
    from config_tech import get_scientist_branch_bonuses
    result = {}
    for key, sci in COLONY_SCIENTISTS.items():
        entry = dict(sci)
        entry['_branch_bonuses'] = get_scientist_branch_bonuses(key)
        result[key] = entry
    return result


def build_recent_activity(user_id, limit=10):
    """
    Build combined activity list from assets and transactions.
    Consolidates repeated activity-building logic from app.py.
    """
    from utilities.postgres_utils import get_user_depot_transactions, get_user_replicate_assets
    from utilities.depot_utils import eth_to_display

    assets = get_user_replicate_assets(user_id, limit=limit)
    transactions = get_user_depot_transactions(user_id, limit=limit)

    activity = [{'type': a['asset_type'], 'timestamp': a['created_at'], 'data': a} for a in assets]
    activity += [{
        'type': 'depot_transaction', 'timestamp': tx['created_at'],
        'data': {
            'purchase_type': tx['purchase_type'],
            'amount_display': eth_to_display(tx['amount_eth']),
            'tx_hash': tx['tx_hash'], 'item_details': tx.get('item_details')
        }
    } for tx in transactions]

    activity.sort(key=lambda x: x['timestamp'], reverse=True)
    return activity[:limit]


def get_while_you_were_away_summary(user_id: int) -> dict:
    """
    Generate a comprehensive captain's briefing of what happened since last login.

    This is a real mission briefing with ARIA's personality - specific details about
    expeditions, discoveries, infrastructure, map progress, and even recent conversation topics.

    Returns a dict with all briefing data or {'show_briefing': False} if nothing to report.
    """
    from utilities.postgres_utils import db_cursor
    from utilities.aria_utils import get_aria_conversation_history
    from datetime import datetime, timezone
    import math
    import json

    def calculate_distance(lat1, lon1, lat2, lon2):
        """Calculate distance in km between two Mars coordinates."""
        # Mars radius in km
        R = 3389.5
        lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat/2)**2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon/2)**2
        return 2 * R * math.asin(math.sqrt(a))

    try:
        with db_cursor() as cur:
            # Get user's last meaningful activity time (updates on purchases, expeditions, claims, etc.)
            # This fixes the bug where users with long-lived sessions show stale briefings
            cur.execute("""
                SELECT u.last_meaningful_activity_at, u.previous_login, u.last_login,
                       u.home_mars_lat, u.home_mars_lon, ra.commander_name
                FROM pilgrim.users u
                LEFT JOIN pilgrim.replicate_assets ra ON u.id = ra.user_id
                    AND ra.is_primary_character = true AND ra.is_deleted = false
                WHERE u.id = %s
            """, (user_id,))
            user_row = cur.fetchone()

            if not user_row:
                return {'show_briefing': False}

            # Priority: last_meaningful_activity_at > previous_login > last_login
            # This ensures active players with long sessions get fresh briefings
            last_activity = (
                user_row.get('last_meaningful_activity_at') or
                user_row.get('previous_login') or
                user_row.get('last_login')
            )
            if not last_activity:
                return {'show_briefing': False}

            if last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=timezone.utc)

            colony_lat = float(user_row.get('home_mars_lat') or -4.5)
            colony_lon = float(user_row.get('home_mars_lon') or 137.4)
            commander_name = user_row.get('commander_name') or 'Captain'

            now = datetime.now(timezone.utc)
            hours_away = (now - last_activity).total_seconds() / 3600

            # Use last_activity as the reference time for "since you were away"
            last_login = last_activity

            # ===== EXPEDITION DETAILS (with distances, discovery items) =====
            cur.execute("""
                SELECT e.id, e.destination_name, e.destination_type, e.distance_km,
                       e.completed_at, e.departed_at,
                       mm.latitude as dest_lat, mm.longitude as dest_lon
                FROM pilgrim.expeditions e
                LEFT JOIN pilgrim.mars_mappings mm ON LOWER(e.destination_name) = LOWER(mm.name)
                WHERE e.user_id = %s
                  AND e.status = 'complete'
                  AND e.completed_at > %s
                ORDER BY e.completed_at DESC
            """, (user_id, last_login))
            expedition_rows = cur.fetchall()

            expeditions_completed = []
            total_distance_traveled = 0
            farthest_expedition = None
            max_distance = 0

            for exp in expedition_rows:
                exp_id = exp['id']
                distance = float(exp.get('distance_km') or 0)
                total_distance_traveled += distance * 2  # Round trip

                # Get discoveries for this expedition with item details
                cur.execute("""
                    SELECT di.item_name, di.rarity, di.item_type, ed.enhanced_value
                    FROM pilgrim.expedition_discoveries ed
                    JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
                    WHERE ed.expedition_id = %s
                    ORDER BY
                        CASE di.rarity
                            WHEN 'legendary' THEN 1
                            WHEN 'rare' THEN 2
                            WHEN 'uncommon' THEN 3
                            ELSE 4
                        END
                """, (exp_id,))
                discoveries = []
                for d in cur.fetchall():
                    discoveries.append({
                        'name': d['item_name'],
                        'rarity': d['rarity'],
                        'type': d['item_type'],
                        'value': float(d.get('enhanced_value') or 0)
                    })

                exp_data = {
                    'destination': exp['destination_name'],
                    'type': exp.get('destination_type'),
                    'distance_km': round(distance),
                    'discoveries': discoveries,
                    'discovery_count': len(discoveries)
                }
                expeditions_completed.append(exp_data)

                if distance > max_distance:
                    max_distance = distance
                    farthest_expedition = exp_data

            # ===== DISCOVERY BREAKDOWN BY RARITY (with top items) =====
            cur.execute("""
                SELECT di.rarity, di.item_name, di.item_type, ed.enhanced_value, COUNT(*) as count
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
                WHERE e.user_id = %s
                  AND e.completed_at > %s
                GROUP BY di.rarity, di.item_name, di.item_type, ed.enhanced_value
                ORDER BY
                    CASE di.rarity
                        WHEN 'legendary' THEN 1
                        WHEN 'rare' THEN 2
                        WHEN 'uncommon' THEN 3
                        ELSE 4
                    END,
                    ed.enhanced_value DESC
            """, (user_id, last_login))

            discoveries_by_rarity = {'legendary': 0, 'rare': 0, 'uncommon': 0, 'common': 0}
            top_discoveries = []  # Best finds to highlight
            total_discovery_value = 0

            for row in cur.fetchall():
                rarity = row['rarity'] or 'common'
                count = row['count']
                discoveries_by_rarity[rarity] = discoveries_by_rarity.get(rarity, 0) + count
                value = float(row.get('enhanced_value') or 0)
                total_discovery_value += value * count

                # Track top discoveries (legendary and rare only)
                if rarity in ('legendary', 'rare') and len(top_discoveries) < 3:
                    top_discoveries.append({
                        'name': row['item_name'],
                        'rarity': rarity,
                        'type': row['item_type'],
                        'value': round(value)
                    })

            total_discoveries = sum(discoveries_by_rarity.values())

            # ===== INFRASTRUCTURE STATUS =====
            cur.execute("""
                SELECT structure_type, build_completed_at
                FROM pilgrim.colony_infrastructure
                WHERE user_id = %s
                  AND status = 'active'
                  AND build_completed_at > %s
                ORDER BY build_completed_at DESC
            """, (user_id, last_login))
            infrastructure_completed = [row['structure_type'] for row in cur.fetchall()]

            # Get current infrastructure with generation breakdown
            cur.execute("""
                SELECT structure_type, generation_rate,
                       COALESCE(last_payout_at, build_completed_at, created_at) as last_payout,
                       COALESCE(total_generated, 0) as total_generated
                FROM pilgrim.colony_infrastructure
                WHERE user_id = %s AND status = 'active' AND generates_resource = 'sepolia'
            """, (user_id,))

            infrastructure_income = []
            pending_harvest = 0
            accumulated_shards = 0  # Since last login specifically

            for row in cur.fetchall():
                last_payout = row.get('last_payout')
                hourly_rate = float(row.get('generation_rate') or 0)
                struct_pending = 0
                struct_accumulated = 0

                if last_payout:
                    # Make last_payout timezone-aware if needed
                    if last_payout.tzinfo is None:
                        last_payout = last_payout.replace(tzinfo=timezone.utc)
                    hours_since_payout = (now - last_payout).total_seconds() / 3600
                    struct_pending = hourly_rate * hours_since_payout
                    pending_harvest += struct_pending

                    # Calculate shards specifically since last login
                    hours_since_login = (now - max(last_payout, last_login)).total_seconds() / 3600
                    if hours_since_login > 0:
                        struct_accumulated = hourly_rate * hours_since_login
                        accumulated_shards += struct_accumulated

                infrastructure_income.append({
                    'structure': row['structure_type'],
                    'rate': round(hourly_rate),
                    'pending': round(struct_pending),
                    'accumulated': round(struct_accumulated)
                })

            # ===== MAP EXPLORATION PROGRESS =====
            cur.execute("""
                SELECT COUNT(DISTINCT destination_name) as visited
                FROM pilgrim.expeditions
                WHERE user_id = %s AND status = 'complete'
            """, (user_id,))
            visited_locations = cur.fetchone()['visited'] or 0

            cur.execute("SELECT COUNT(*) as total FROM pilgrim.mars_mappings")
            total_locations = cur.fetchone()['total'] or 1
            exploration_percent = round((visited_locations / total_locations) * 100, 1)

            # Get closest unexplored frontier destination
            cur.execute("""
                SELECT DISTINCT destination_name FROM pilgrim.expeditions
                WHERE user_id = %s
            """, (user_id,))
            visited_names = [r['destination_name'] for r in cur.fetchall()]

            closest_frontier = None
            if visited_names:
                cur.execute("""
                    SELECT name, type, latitude, longitude
                    FROM pilgrim.mars_mappings
                    WHERE name != ALL(%s)
                    LIMIT 50
                """, (visited_names,))
                closest_dist = float('inf')
                for loc in cur.fetchall():
                    if loc.get('latitude') and loc.get('longitude'):
                        dist = calculate_distance(
                            colony_lat, colony_lon,
                            float(loc['latitude']), float(loc['longitude'])
                        )
                        if dist < closest_dist:
                            closest_dist = dist
                            closest_frontier = {
                                'name': loc['name'],
                                'type': loc['type'],
                                'distance_km': round(dist)
                            }

            # ===== TOTAL TRAIL KM BUILT (for dashboard stat box) =====
            total_trail_km = 0
            try:
                cur.execute("""
                    SELECT COALESCE(SUM(km_built), 0) as total_km
                    FROM pilgrim.trail_segments
                    WHERE user_id = %s
                """, (user_id,))
                total_trail_km = float(cur.fetchone()['total_km'] or 0)
            except Exception:
                pass

            # ===== PENDING ACTIONS =====
            cur.execute("""
                SELECT COUNT(*) as count
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                WHERE e.user_id = %s AND ed.claimed_by_user = false
            """, (user_id,))
            pending_discoveries = cur.fetchone()['count'] or 0

            # ===== ARIA CONVERSATION MEMORY =====
            aria_memory_note = None
            try:
                recent_history = get_aria_conversation_history(user_id, limit=6)
                if recent_history:
                    # Get the last user message topic
                    user_messages = [m['content'] for m in recent_history if m['role'] == 'user']
                    if user_messages:
                        last_topic = user_messages[-1][:60]
                        if len(user_messages[-1]) > 60:
                            last_topic += "..."
                        aria_memory_note = last_topic
            except Exception:
                pass

            # ===== ARIA PHOTO JOURNAL SNAPSHOTS =====
            # Get recent snapshots (generated daily by cron)
            snapshots = []
            try:
                cur.execute("""
                    SELECT id, subcategory, gcs_url, caption, metadata, created_at
                    FROM pilgrim.generated_images
                    WHERE user_id = %s AND category = 'aria_snapshot' AND is_active = true
                    ORDER BY created_at DESC
                    LIMIT 10
                """, (user_id,))
                for snap in cur.fetchall():
                    # Extract thumbnail and mars_sol from metadata
                    metadata = snap.get('metadata') or {}
                    if isinstance(metadata, str):
                        try:
                            metadata = json.loads(metadata)
                        except:
                            metadata = {}
                    thumbnail_url = metadata.get('thumbnail_url')
                    time_of_day = metadata.get('time_of_day', 'day')
                    # Calculate sol from created_at (not stored metadata) so epoch changes apply
                    created = snap.get('created_at')
                    from utilities.mars_environment_utils import get_mars_sol_number
                    mars_sol = get_mars_sol_number(created) if created else metadata.get('mars_sol')

                    # Just show date — Sol badge is the time reference
                    created = snap.get('created_at')
                    earth_date = created.strftime('%b %d, %Y') if created else None
                    earth_time = None

                    snapshots.append({
                        'id': snap['id'],
                        'type': snap['subcategory'],
                        'image_url': snap['gcs_url'],
                        'thumbnail_url': thumbnail_url or snap['gcs_url'],  # Fallback to full image
                        'caption': snap['caption'],
                        'created_at': snap['created_at'].isoformat() if created else None,
                        'mars_sol': mars_sol,
                        'time_of_day': time_of_day,
                        'earth_date': earth_date,
                        'earth_time': earth_time,
                    })
            except Exception:
                pass

            # ===== BUILD THE GREETING =====
            # Make it personal and specific based on what happened
            if hours_away < 1:
                time_phrase = "less than an hour"
            elif hours_away < 2:
                time_phrase = "1 hour"
            elif hours_away < 24:
                time_phrase = f"{int(hours_away)} hours"
            elif hours_away < 48:
                time_phrase = "a day"
            elif hours_away < 168:
                time_phrase = f"{int(hours_away / 24)} days"
            else:
                time_phrase = f"{int(hours_away / 24)} days"

            # Build a contextual greeting
            greeting_parts = []
            if hours_away >= 168:  # 7+ days
                greeting_parts.append(f"Captain {commander_name}! It's been {time_phrase}.")
            elif hours_away >= 72:
                greeting_parts.append(f"Welcome back, Captain. {time_phrase} since your last visit.")
            else:
                greeting_parts.append(f"Captain. Quick briefing on the last {time_phrase}.")

            # Add a highlight to the greeting
            if discoveries_by_rarity.get('legendary', 0) > 0:
                greeting_parts.append(f"We found something extraordinary.")
            elif discoveries_by_rarity.get('rare', 0) > 0:
                greeting_parts.append(f"The rovers brought back some interesting finds.")
            elif len(expeditions_completed) > 0:
                greeting_parts.append(f"{len(expeditions_completed)} expedition{'s' if len(expeditions_completed) > 1 else ''} returned safely.")
            elif accumulated_shards > 500:
                greeting_parts.append(f"Solar arrays have been productive.")

            greeting = " ".join(greeting_parts)

            # Determine tone
            if hours_away < 24:
                tone = 'brief'
            elif hours_away < 72:
                tone = 'normal'
            elif hours_away < 168:
                tone = 'eager'
            else:
                tone = 'concerned'

            # ===== CHECK FOR PENDING ARIA BOND FRAGMENTS =====
            pending_fragments = []
            try:
                from utilities.aria_bond_utils import get_pending_fragments
                all_pending = get_pending_fragments(user_id)
                # Only include fragments that have a tx_hash and haven't been submitted
                for p in all_pending:
                    tx_hash = p.get('my_fragment')
                    if tx_hash and not p.get('my_submitted'):
                        pending_fragments.append({
                            'landmark': p.get('landmark_name'),
                            'tx_hash': tx_hash
                        })
            except Exception as e:
                logger.warning(f"Could not check ARIA fragments: {e}")

            # ===== TECH TREE PROGRESS =====
            tech_progress = {'researched': 0, 'total': 0, 'percent': 0, 'active_research': None,
                             'active_name': None, 'active_progress_pct': 0, 'active_remaining_secs': 0}
            try:
                cur.execute("""
                    SELECT COUNT(*) as researched
                    FROM pilgrim.player_techs
                    WHERE user_id = %s AND completed_at IS NOT NULL
                """, (user_id,))
                tech_progress['researched'] = cur.fetchone()['researched'] or 0

                # Get total techs from catalog
                from config import TECH_CATALOG
                total_techs = sum(len(branch.get('techs', {})) for branch in TECH_CATALOG.values())
                tech_progress['total'] = total_techs
                tech_progress['percent'] = round((tech_progress['researched'] / total_techs * 100), 1) if total_techs > 0 else 0

                # Check for active research with progress
                cur.execute("""
                    SELECT tech_key, branch, research_started_at, research_duration_seconds
                    FROM pilgrim.player_techs
                    WHERE user_id = %s AND status = 'researching'
                    LIMIT 1
                """, (user_id,))
                active = cur.fetchone()
                if active:
                    tech_key = active['tech_key']
                    branch_key = active['branch']
                    tech_progress['active_research'] = tech_key
                    # Get tech details from catalog
                    branch_data = TECH_CATALOG.get(branch_key, {})
                    tech_data = branch_data.get('techs', {}).get(tech_key, {})
                    tech_progress['active_name'] = tech_data.get('name', tech_key.replace('_', ' ').title())
                    research_time = active['research_duration_seconds'] or 3600
                    started_at = active['research_started_at']
                    if started_at:
                        if started_at.tzinfo is None:
                            started_at = started_at.replace(tzinfo=timezone.utc)
                        elapsed = (now - started_at).total_seconds()
                        progress_pct = min(100, (elapsed / research_time) * 100)
                        remaining = max(0, research_time - elapsed)
                        tech_progress['active_progress_pct'] = round(progress_pct, 2)
                        tech_progress['active_remaining_secs'] = round(remaining)
            except Exception:
                pass

            # ===== LAB EXPERIMENTS =====
            lab_stats = {'experiments_run': 0, 'research_points': 0}
            try:
                cur.execute("""
                    SELECT experiments_run, research_points
                    FROM pilgrim.xenobiology_lab
                    WHERE user_id = %s
                """, (user_id,))
                lab_row = cur.fetchone()
                if lab_row:
                    lab_stats['experiments_run'] = lab_row.get('experiments_run') or 0
                    lab_stats['research_points'] = lab_row.get('research_points') or 0
            except Exception:
                pass

            # ===== CHECK IF BRIEFING IS WORTH SHOWING =====
            has_content = (
                accumulated_shards > 10 or
                len(expeditions_completed) > 0 or
                len(infrastructure_completed) > 0 or
                pending_harvest > 100 or
                pending_discoveries > 0 or
                total_discoveries > 0 or
                len(pending_fragments) > 0 or  # Show briefing if pending fragments!
                len(snapshots) > 0  # Show briefing if ARIA took photos!
            )

            if not has_content:
                return {'show_briefing': False, 'hours_away': hours_away}

            # Content-based dismiss key — only changes when briefing content changes.
            # Using last_activity_iso caused re-show on every game action (too noisy).
            _sig = f"{int(accumulated_shards)//10},{pending_discoveries},{len(expeditions_completed)},{len(infrastructure_completed)}"
            briefing_key = hashlib.md5(_sig.encode()).hexdigest()[:10]

            return {
                'show_briefing': True,
                'hours_away': round(hours_away, 1),
                'last_activity_iso': last_activity.isoformat(),  # For live JS timer
                'briefing_key': briefing_key,  # For dismiss logic
                'time_phrase': time_phrase,
                'tone': tone,
                'greeting': greeting,
                'commander_name': commander_name,

                # Expedition details
                'expeditions_completed': expeditions_completed,
                'total_distance_traveled': round(total_distance_traveled),
                'farthest_expedition': farthest_expedition,

                # Discovery details
                'discoveries_found': total_discoveries,
                'discoveries_by_rarity': discoveries_by_rarity,
                'top_discoveries': top_discoveries,
                'total_discovery_value': round(total_discovery_value),

                # Infrastructure
                'infrastructure_completed': infrastructure_completed,
                'infrastructure_income': infrastructure_income,
                'accumulated_shards': round(accumulated_shards, 1),
                'pending_harvest': round(pending_harvest, 1),

                # Map progress
                'visited_locations': visited_locations,
                'total_locations': total_locations,
                'exploration_percent': exploration_percent,
                'closest_frontier': closest_frontier,
                'total_trail_km': round(total_trail_km, 4),

                # Pending actions
                'pending_discoveries': pending_discoveries,

                # ARIA memory
                'aria_memory_note': aria_memory_note,

                # ARIA Photo Journal
                'snapshots': snapshots,

                # Pending ARIA bond fragments (for nagging reminder)
                'pending_fragments': pending_fragments,

                # Tech tree progress
                'tech_progress': tech_progress,

                # Lab experiments
                'lab_stats': lab_stats,
            }

    except Exception as e:
        logger.error(f"Error getting while-you-were-away summary for user {user_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {'show_briefing': False}


def get_fleet_status(user_id: int, debug_mode: bool = False) -> Dict[str, Any]:
    """
    Get status of all 3 mobility slots (rover, drone, buggy) for Fleet Status bar.

    Returns dict with 3 slots, each containing:
    - status: 'at_base', 'en_route', 'returned'
    - For en_route: destination, eta, distance_km, progress_pct
    - For returned: distance_km, shards_earned, discoveries (list with rarity breakdown), distance_bonus

    Distance bonus tiers (Fallout Shelter style):
    - < 200km: 1x (none)
    - 200-500km: 2x "Long Haul"
    - 500-1000km: 3x "Deep Expedition"
    - 1000-2000km: 5x "Frontier Run"
    - 2000+ km: 10x "Legendary Journey"
    """
    from utilities.postgres_utils import db_cursor

    def get_distance_bonus(distance_km: float) -> Dict:
        """Get multiplier and label for distance."""
        if distance_km < 200:
            return {'mult': 1, 'label': None}
        elif distance_km < 500:
            return {'mult': 2, 'label': 'Long Haul'}
        elif distance_km < 1000:
            return {'mult': 3, 'label': 'Deep Expedition'}
        elif distance_km < 2000:
            return {'mult': 5, 'label': 'Frontier Run'}
        else:
            return {'mult': 10, 'label': 'Legendary Journey'}

    # Initialize all 3 slots as "at_base"
    fleet = {
        'rover': {'status': 'at_base', 'vehicle_name': 'Rover', 'icon': '🚗'},
        'drone': {'status': 'at_base', 'vehicle_name': 'Drone', 'icon': '🚁'},
        'buggy': {'status': 'at_base', 'vehicle_name': 'Buggy', 'icon': '🛞'}
    }

    # Debug mode: show mock data for all slots
    if debug_mode:
        now = datetime.now()
        fleet['rover'] = {
            'status': 'en_route', 'vehicle_name': 'Rover', 'icon': '🚗',
            'destination': 'Olympus Mons', 'distance_km': 847,
            'eta_iso': (now + timedelta(hours=2, minutes=34)).isoformat(),
            'progress_pct': 65, 'departed_at_iso': (now - timedelta(hours=5)).isoformat()
        }
        fleet['drone'] = {
            'status': 'returned', 'vehicle_name': 'Drone', 'icon': '🚁',
            'destination': 'Jezero Crater', 'distance_km': 1247,
            'shards_earned': 142, 'expedition_id': 999,
            'discoveries': [
                {'rarity': 'rare', 'count': 1},
                {'rarity': 'uncommon', 'count': 2},
                {'rarity': 'common', 'count': 1}
            ],
            'total_discoveries': 4,
            'distance_bonus': get_distance_bonus(1247)
        }
        fleet['buggy'] = {
            'status': 'at_base', 'vehicle_name': 'Buggy', 'icon': '🛞'
        }
        return fleet

    try:
        with db_cursor() as cur:
            now = datetime.now()

            # Get all expeditions for this user that are active or recently completed
            cur.execute("""
                SELECT e.id, e.vehicle_type, e.status, e.destination_name, e.distance_km,
                       e.departed_at, e.arrives_at, e.return_arrives_at, e.sepolia_earned,
                       e.completed_at,
                       COALESCE(unclaimed.count, 0) as unclaimed_discoveries
                FROM pilgrim.expeditions e
                LEFT JOIN (
                    SELECT expedition_id, COUNT(*) as count
                    FROM pilgrim.expedition_discoveries
                    WHERE claimed_by_user = false
                    GROUP BY expedition_id
                ) unclaimed ON unclaimed.expedition_id = e.id
                WHERE e.user_id = %s
                  AND (e.status = 'traveling'
                       OR (e.status = 'complete' AND COALESCE(unclaimed.count, 0) > 0))
                ORDER BY e.departed_at DESC
            """, (user_id,))
            expeditions = cur.fetchall()

            for exp in expeditions:
                vehicle_type = exp['vehicle_type'] or 'rover'
                if vehicle_type not in fleet:
                    continue

                # Skip if this slot already has data (take most recent)
                if fleet[vehicle_type]['status'] != 'at_base':
                    continue

                distance_km = float(exp['distance_km'] or 0)
                distance_bonus = get_distance_bonus(distance_km)

                if exp['status'] == 'traveling':
                    # Calculate progress and ETA
                    departed_at = exp['departed_at']
                    return_arrives_at = exp['return_arrives_at'] or exp['arrives_at']
                    total_seconds = (return_arrives_at - departed_at).total_seconds() if departed_at and return_arrives_at else 0
                    elapsed_seconds = (now - departed_at).total_seconds() if departed_at else 0
                    progress_pct = min(100, (elapsed_seconds / total_seconds * 100)) if total_seconds > 0 else 0

                    # Check if expedition has actually returned (return_arrives_at passed)
                    if return_arrives_at and now >= return_arrives_at:
                        # Get discovery breakdown for this expedition
                        cur.execute("""
                            SELECT rarity, COUNT(*) as count
                            FROM pilgrim.expedition_discoveries
                            WHERE expedition_id = %s AND claimed_by_user = false
                            GROUP BY rarity
                        """, (exp['id'],))
                        discoveries = []
                        total_disc = 0
                        for row in cur.fetchall():
                            discoveries.append({'rarity': row['rarity'], 'count': row['count']})
                            total_disc += row['count']

                        fleet[vehicle_type] = {
                            'status': 'returned', 'vehicle_name': vehicle_type.title(), 'icon': fleet[vehicle_type]['icon'],
                            'destination': exp['destination_name'], 'distance_km': distance_km,
                            'shards_earned': round(float(exp['sepolia_earned'] or 0) * 10000000, 1),
                            'expedition_id': exp['id'],
                            'discoveries': discoveries, 'total_discoveries': total_disc,
                            'distance_bonus': distance_bonus
                        }
                    else:
                        # Still traveling
                        fleet[vehicle_type] = {
                            'status': 'en_route', 'vehicle_name': vehicle_type.title(), 'icon': fleet[vehicle_type]['icon'],
                            'destination': exp['destination_name'], 'distance_km': distance_km,
                            'eta_iso': return_arrives_at.isoformat() if return_arrives_at else None,
                            'progress_pct': round(progress_pct, 1),
                            'departed_at_iso': departed_at.isoformat() if departed_at else None
                        }

                elif exp['status'] == 'complete' and exp['unclaimed_discoveries'] > 0:
                    # Returned with unclaimed discoveries
                    cur.execute("""
                        SELECT rarity, COUNT(*) as count
                        FROM pilgrim.expedition_discoveries
                        WHERE expedition_id = %s AND claimed_by_user = false
                        GROUP BY rarity
                    """, (exp['id'],))
                    discoveries = []
                    total_disc = 0
                    for row in cur.fetchall():
                        discoveries.append({'rarity': row['rarity'], 'count': row['count']})
                        total_disc += row['count']

                    fleet[vehicle_type] = {
                        'status': 'returned', 'vehicle_name': vehicle_type.title(), 'icon': fleet[vehicle_type]['icon'],
                        'destination': exp['destination_name'], 'distance_km': distance_km,
                        'shards_earned': round(float(exp['sepolia_earned'] or 0) * 10000000, 1),
                        'expedition_id': exp['id'],
                        'discoveries': discoveries, 'total_discoveries': total_disc,
                        'distance_bonus': distance_bonus
                    }

    except Exception as e:
        logger.error(f"Error getting fleet status for user {user_id}: {e}")

    return fleet


def get_dashboard_page_data(user_id, auth):
    """Get all data needed for colony/dashboard page."""
    from utilities.postgres_utils import (
        get_user_sepolia_wallets, get_user_by_google_id, get_user_active_expeditions,
        get_user_completed_expeditions_count, get_user_visited_locations_count,
        get_crew_mission_status, get_user_replicate_assets, db_cursor
    )
    from utilities.infrastructure_utils import get_user_infrastructure
    from utilities.depot_utils import get_fast_balance_and_wallet_info, get_commander_and_stats

    wallets = get_user_sepolia_wallets(user_id)
    images = get_user_replicate_assets(user_id, asset_type='character_image', limit=1)

    # If user is missing wallet or captain, something went wrong during onboarding
    # Log the issue but don't redirect - let them stay on dashboard
    if not wallets:
        logger.warning(f"User {user_id} has no wallet - onboarding incomplete")
    if not images:
        logger.warning(f"User {user_id} has no captain - onboarding incomplete")

    user = get_user_by_google_id(auth.get_current_user().get('google_id'))
    total_balance, _, primary_wallet = get_fast_balance_and_wallet_info(user_id)  # FAST: no blockchain
    commander, commander_stats = get_commander_and_stats(user_id)
    active_expeditions = get_user_active_expeditions(user_id)

    # Get real expedition stats
    completed_expeditions = get_user_completed_expeditions_count(user_id)
    visited_locations = get_user_visited_locations_count(user_id)
    total_expeditions = completed_expeditions + len(active_expeditions)

    # Safely get captain - handle case where user has no captain yet
    has_commander = commander is not None or len(images) > 0
    commander_data = commander or (images[0] if images else None)

    # Get live Mars environment data
    try:
        from utilities.mars_environment_utils import get_mars_environment_summary
        mars_env = get_mars_environment_summary()
    except Exception as e:
        logger.warning(f"Failed to get Mars environment: {e}")
        mars_env = None

    # Get "While You Were Away" summary
    away_summary = get_while_you_were_away_summary(user_id)

    # Get building items (upgrades + infrastructure)
    building_items = []
    # Upgrade system builds
    try:
        from utilities.upgrades_utils import get_active_builds
        for build in get_active_builds(user_id):
            building_items.append({
                'name': build['name'],
                'seconds_remaining': build['seconds_remaining'],
                'total_seconds': build['seconds_remaining'],
                'progress_pct': 0,
                'ready_at': None,
                'ready_at_str': build.get('ready_at_str', '')
            })
    except Exception as e:
        logger.warning(f"Failed to get upgrade builds for dashboard: {e}")
    # Add infrastructure builds
    try:
        from config_infrastructure import INFRASTRUCTURE_CATALOG
        for infra in get_user_infrastructure(user_id):
            if infra.get('status') == 'building' and infra.get('ready_at'):
                ready_at = infra['ready_at']
                if hasattr(ready_at, 'tzinfo') and ready_at.tzinfo is None:
                    ready_at = ready_at.replace(tzinfo=timezone.utc)
                secs = max(0, int((ready_at - datetime.now(timezone.utc)).total_seconds()))
                cat = INFRASTRUCTURE_CATALOG.get(infra['structure_type'], {})
                building_items.append({
                    'name': cat.get('name', infra['structure_type'].replace('_', ' ').title()),
                    'seconds_remaining': secs,
                    'total_seconds': secs,
                    'progress_pct': 0,
                    'ready_at': ready_at,
                    'ready_at_str': ready_at.strftime('%b %d')
                })
    except Exception as e:
        logger.warning(f"Failed to get infra builds for dashboard: {e}")
    building_items.sort(key=lambda b: b['seconds_remaining'])

    crew_missions = get_crew_mission_status(user_id)

    # ========================================================================
    # LIVE RATES: Calculate rates for ticking briefing panel stats
    # All rates are per SECOND for smooth JS animation
    # ========================================================================
    live_rates = {
        'shard_rate': 0,      # shards per second
        'km_rate': 0,         # km per second (from expeditions)
        'tech_rate': 0,       # tech tree % per second (from active research)
        'trail_rate': 0,      # trail km per second (from crew missions)
        'build_rate': 0,      # build % per second (from building queue)
    }

    # 1. SHARD RATE: From infrastructure
    try:
        from utilities.infrastructure_utils import calculate_accumulated_income
        income_calc = calculate_accumulated_income(user_id)
        hourly_rate = income_calc.get('rate_breakdown', {}).get('theoretical_max_rate', 0)
        live_rates['shard_rate'] = hourly_rate / 3600  # per second
    except Exception:
        pass

    # 2. KM RATE: From active expeditions (round trip: out + back)
    try:
        for exp in active_expeditions:
            if exp.get('status') in ('traveling', 'recalled') and exp.get('distance_km') and exp.get('departed_at'):
                departed = exp['departed_at']
                # Use return_arrives_at for full round-trip, fall back to arrives_at for one-way
                end_time = exp.get('return_arrives_at') or exp.get('arrives_at')
                if end_time and hasattr(departed, 'timestamp') and hasattr(end_time, 'timestamp'):
                    travel_seconds = (end_time - departed).total_seconds()
                    if travel_seconds > 0:
                        # Round trip = distance * 2
                        round_trip_km = float(exp['distance_km']) * 2
                        speed_per_sec = round_trip_km / travel_seconds
                        live_rates['km_rate'] += speed_per_sec
    except Exception:
        pass

    # 3. TECH RATE: From active research (% progress per second)
    try:
        tech_prog = away_summary.get('tech_progress', {})
        if tech_prog.get('active_research') and tech_prog.get('active_remaining_secs', 0) > 0:
            current_pct = tech_prog.get('active_progress_pct', 0)
            remaining_secs = tech_prog['active_remaining_secs']
            # Rate = remaining % / remaining seconds
            remaining_pct = 100 - current_pct
            live_rates['tech_rate'] = remaining_pct / remaining_secs
    except Exception:
        pass

    # 4. TRAIL RATE: From crew missions (km per second)
    try:
        now = datetime.now(timezone.utc)
        for member in ['captain', 'scientist', 'aria']:
            mission = crew_missions.get(member)
            if mission and mission.get('busy') and not mission.get('complete'):
                ends_at_str = mission.get('ends_at')
                km_to_add = mission.get('km_pending', 0)
                if ends_at_str and km_to_add > 0:
                    # ends_at is ISO string, parse it
                    ends_at = datetime.fromisoformat(ends_at_str.replace('Z', '+00:00'))
                    if ends_at.tzinfo is None:
                        ends_at = ends_at.replace(tzinfo=timezone.utc)
                    secs_remaining = (ends_at - now).total_seconds()
                    if secs_remaining > 0:
                        live_rates['trail_rate'] += km_to_add / secs_remaining
        logger.debug(f"Trail rate calculated: {live_rates['trail_rate']}")
    except Exception as e:
        logger.warning(f"Trail rate calculation failed: {e}")

    # 5. BUILD RATE: From building queue (average % per second across all builds)
    avg_build_progress = 0
    try:
        if building_items:
            total_progress = sum(b['progress_pct'] for b in building_items)
            avg_build_progress = total_progress / len(building_items)
            # Rate = average remaining % / average remaining seconds
            total_remaining_pct = sum(100 - b['progress_pct'] for b in building_items)
            total_remaining_secs = sum(b['seconds_remaining'] for b in building_items if b['seconds_remaining'] > 0)
            if total_remaining_secs > 0:
                live_rates['build_rate'] = total_remaining_pct / total_remaining_secs / len(building_items)
    except Exception as e:
        logger.warning(f"Build rate calculation failed: {e}")

    # Fleet Status bar (debug mode from query param)
    from flask import request
    fleet_debug = request.args.get('show_expeditions', '').lower() == 'true'
    fleet_status = get_fleet_status(user_id, debug_mode=fleet_debug)
    if fleet_debug:
        logger.info(f"🚀 FLEET DEBUG MODE: fleet_status={fleet_status}")

    # Welcome-back modal gating
    welcome_back = {}
    try:
        with db_cursor() as cur:
            cur.execute("SELECT previous_login, last_login, last_meaningful_activity_at FROM pilgrim.users WHERE id = %s", (user_id,))
            urow = cur.fetchone()
        if urow and urow.get('previous_login') != urow.get('last_login'):
            ref = urow.get('last_meaningful_activity_at') or urow.get('previous_login') or urow.get('last_login')
            if ref:
                if ref.tzinfo is None:
                    ref = ref.replace(tzinfo=timezone.utc)
                hours_away = (datetime.now(timezone.utc) - ref).total_seconds() / 3600
                if hours_away > 1:
                    welcome_back = {'show': True, 'previous_activity_iso': ref.isoformat()}
    except Exception:
        pass

    # Get completed ARIA bonds for dashboard display
    completed_bonds = []
    try:
        from utilities.aria_bond_utils import get_bonds_for_display
        completed_bonds = get_bonds_for_display(user_id)
    except Exception as e:
        logger.warning(f"Could not fetch completed bonds: {e}")

    # Last completed buggy expedition for cinematic card
    last_buggy_expedition = None
    try:
        from utilities.db_expeditions import get_last_completed_buggy_expedition
        from utilities.upgrades_utils import get_user_upgrade_level
        lbe = get_last_completed_buggy_expedition(user_id)
        if lbe:
            buggy_level = get_user_upgrade_level(user_id, 'vehicles', 'buggy')
            lbe['buggy_level'] = buggy_level
            lbe['shards_display'] = int(float(lbe.get('sepolia_earned') or 0) * 10000000)
            if lbe.get('departed_at') and lbe.get('completed_at'):
                lbe['travel_hours'] = round((lbe['completed_at'] - lbe['departed_at']).total_seconds() / 3600, 1)
            # Get longhaul hero image for player's buggy level
            from config_upgrades import UPGRADE_CATALOG
            buggy_cfg = UPGRADE_CATALOG.get('vehicles', {}).get('buggy', {}).get('levels', {}).get(buggy_level, {})
            lbe['longhaul_image_url'] = buggy_cfg.get('longhaul_image_url') or buggy_cfg.get('image_url', '')
            lbe['buggy_name'] = buggy_cfg.get('name', 'Buggy')
            # Sol date for return
            from datetime import datetime, timezone
            SOL_EPOCH = datetime(2025, 10, 4, tzinfo=timezone.utc)
            if lbe.get('completed_at'):
                completed_utc = lbe['completed_at'].replace(tzinfo=timezone.utc) if not lbe['completed_at'].tzinfo else lbe['completed_at']
                lbe['return_sol'] = int((completed_utc - SOL_EPOCH).total_seconds() // 86400)
            # Current buggy status: idle, traveling, or returned
            buggy_now = next((e for e in active_expeditions if e.get('vehicle_type') == 'buggy' and e.get('status') == 'traveling'), None)
            if buggy_now:
                lbe['buggy_status'] = 'traveling'
                lbe['buggy_current_dest'] = buggy_now.get('destination_name', '')
                lbe['buggy_current_distance'] = float(buggy_now.get('distance_km', 0))
            else:
                lbe['buggy_status'] = 'idle'
                # How long since the last expedition returned
                if lbe.get('completed_at'):
                    now = datetime.now(timezone.utc) if lbe['completed_at'].tzinfo else datetime.now()
                    idle_hours = (now - lbe['completed_at']).total_seconds() / 3600
                    lbe['buggy_idle_hours'] = round(idle_hours, 1)
            last_buggy_expedition = lbe
    except Exception as e:
        logger.warning(f"Could not fetch last buggy expedition: {e}")

    return {
        'user': user, 'wallets': wallets, 'primary_wallet': primary_wallet,
        'total_balance': total_balance, 'primary_balance': total_balance, 'has_commander': has_commander,
        'commander': commander_data, 'commander_stats': commander_stats,
        'recent_activity': build_recent_activity(user_id, 10),
        'active_expeditions': active_expeditions,
        'has_infrastructure': len(get_user_infrastructure(user_id)) > 0,
        'expedition_stats': {
            'total': total_expeditions,
            'completed': completed_expeditions,
            'active': len(active_expeditions),
            'locations_visited': visited_locations
        },
        'mars_env': mars_env,
        'away_summary': away_summary,
        'building_items': building_items,
        'avg_build_progress': avg_build_progress,
        'crew_missions': crew_missions,
        'live_rates': live_rates,
        'fleet_status': fleet_status,
        'fleet_debug': fleet_debug,
        'welcome_back': welcome_back,
        'completed_bonds': completed_bonds,
        'last_buggy_expedition': last_buggy_expedition,
    }

def get_profile_page_data(user_id, auth):
    """Get all data needed for colony/profile page - LEGACY, use get_colony_page_data instead."""
    from utilities.postgres_utils import get_user_sepolia_wallets, get_user_replicate_assets
    from utilities.depot_utils import get_fast_balance_and_wallet_info
    return {
        'user': auth.get_current_user(),
        'wallets': get_user_sepolia_wallets(user_id),
        'total_balance': get_fast_balance_and_wallet_info(user_id)[0],  # FAST: no blockchain
        'images': get_user_replicate_assets(user_id, asset_type='character_image', limit=50),
        'videos': get_user_replicate_assets(user_id, asset_type='character_video', limit=20)
    }


def get_colony_page_data(user_id, auth):
    """
    Get all data needed for the Colony page (formerly Inventory).
    Includes: discoveries, equipment, infrastructure, vehicles, building items.
    """
    from datetime import datetime
    from utilities.postgres_utils import get_building_upgrades, complete_ready_builds, db_cursor
    from utilities.infrastructure_utils import get_user_infrastructure, INFRASTRUCTURE_CATALOG, get_or_set_user_mars_home, calculate_generation_rate
    from utilities.upgrades_utils import get_user_owned_vehicles
    from config_upgrades import UPGRADE_CATALOG
    from utilities.depot_utils import get_fast_balance_and_wallet_info

    total_balance = get_fast_balance_and_wallet_info(user_id)[0]

    # Get user's Mars home coordinates for solar calculations
    coords = get_or_set_user_mars_home(user_id)

    # Get infrastructure - separate active vs building
    existing_raw = get_user_infrastructure(user_id)
    active_infrastructure = []
    building_infrastructure = []

    # Fetch actual infrastructure levels from player_upgrades (single query)
    from utilities.upgrades_utils import get_all_user_upgrades
    all_upgrades = get_all_user_upgrades(user_id)
    infra_levels = all_upgrades.get('infrastructure', {})

    for building in existing_raw:
        enriched = dict(building)
        catalog_def = INFRASTRUCTURE_CATALOG.get(building['structure_type'], {})
        # Get actual level from player_upgrades, default to 1 if building exists
        current_level = infra_levels.get(building['structure_type'], 1)
        enriched['level'] = current_level
        level_data = catalog_def.get('levels', {}).get(current_level, {})

        # Basic catalog data
        enriched['name'] = catalog_def.get('name', building['structure_type'].replace('_', ' ').title())
        # Image resolution: walk back to nearest level with image (Lv2+ often empty)
        from utilities.upgrade_image_utils import get_best_available_image
        enriched['image_url'] = get_best_available_image('infrastructure', building['structure_type'], current_level)
        enriched['icon'] = catalog_def.get('icon', '')
        enriched['description'] = catalog_def.get('description', '')
        enriched['effect'] = catalog_def.get('effect')
        enriched['effect_value'] = catalog_def.get('effect_value')
        enriched['generates_resource'] = catalog_def.get('generates_resource')
        enriched['tier'] = catalog_def.get('tier', 1)
        enriched['category'] = catalog_def.get('category', 'general')
        enriched['total_generated'] = float(building.get('total_generated', 0) or 0)
        enriched['cost_display'] = int(level_data.get('cost', 0))  # Already in display units
        enriched['requirements'] = catalog_def.get('requirements', [])
        enriched['build_time_total'] = level_data.get('build_time_days', 0) * 86400  # Convert to seconds
        enriched['tx_hash'] = building.get('tx_hash', '')

        # Format dates for display (include exact time for user reference)
        if building.get('created_at'):
            enriched['created_at_str'] = building['created_at'].strftime('%b %d, %Y at %I:%M %p')
            # Calculate time active/owned
            time_owned = datetime.now() - building['created_at']
            days_owned = time_owned.days
            if days_owned > 0:
                enriched['time_owned_str'] = f"{days_owned} day{'s' if days_owned != 1 else ''}"
            else:
                hours_owned = int(time_owned.total_seconds() / 3600)
                enriched['time_owned_str'] = f"{hours_owned} hour{'s' if hours_owned != 1 else ''}"
        else:
            enriched['time_owned_str'] = ''

        if building.get('build_completed_at'):
            enriched['completed_at_str'] = building['build_completed_at'].strftime('%b %d, %Y at %I:%M %p')
            # Time active since completion
            time_active = datetime.now() - building['build_completed_at']
            days_active = time_active.days
            if days_active > 0:
                enriched['time_active_str'] = f"{days_active} day{'s' if days_active != 1 else ''}"
            else:
                hours_active = int(time_active.total_seconds() / 3600)
                enriched['time_active_str'] = f"{hours_active} hour{'s' if hours_active != 1 else ''}"
        else:
            enriched['time_active_str'] = ''

        if building.get('ready_at'):
            enriched['ready_at_str'] = building['ready_at'].strftime('%b %d, %Y at %I:%M %p')
            enriched['ready_at_iso'] = building['ready_at'].isoformat()

        # Calculate generation rate
        if building['structure_type'] == 'solar_array':
            enriched['generation_rate'] = calculate_generation_rate('solar_array', coords['latitude'], coords['longitude'])
        else:
            enriched['generation_rate'] = float(catalog_def.get('generation_rate', 0.0))

        # Calculate remaining time for building items
        if building['status'] == 'building' and building.get('ready_at'):
            remaining = (building['ready_at'] - datetime.now()).total_seconds()
            enriched['seconds_remaining'] = max(0, int(remaining))
        else:
            enriched['seconds_remaining'] = 0

        if building['status'] == 'active':
            active_infrastructure.append(enriched)
        elif building['status'] == 'building':
            building_infrastructure.append(enriched)

    # Legacy shop building items removed — all builds now use upgrade system
    building_equipment = []

    # Get owned vehicles with COMPREHENSIVE stats
    raw_vehicles = get_user_owned_vehicles(user_id)
    owned_vehicles = []

    # Check which vehicles are currently on active expeditions + lifetime stats
    expedition_vehicles = {}
    vehicle_lifetime_stats = {}
    with db_cursor() as cur:
        cur.execute("""
            SELECT id, vehicle_type, destination_name, distance_km, status,
                   departed_at, arrives_at, return_arrives_at
            FROM pilgrim.expeditions
            WHERE user_id = %s AND status IN ('traveling', 'recalled')
        """, (user_id,))
        for row in cur.fetchall():
            expedition_vehicles[row['vehicle_type']] = {
                'id': row['id'],
                'destination': row['destination_name'],
                'distance_km': row['distance_km'],
                'status': row['status'],
                'departed_at': row['departed_at'],
                'arrives_at': row['arrives_at'],
                'returns_at': row['return_arrives_at'],
            }
        # Lifetime stats per vehicle type — uses denormalized discovery_count (no JOIN)
        cur.execute("""
            SELECT vehicle_type, COUNT(*) as trips, SUM(distance_km) as total_km,
                   SUM(discovery_count) as total_finds
            FROM pilgrim.expeditions
            WHERE user_id = %s AND status = 'complete'
            GROUP BY vehicle_type
        """, (user_id,))
        for row in cur.fetchall():
            vehicle_lifetime_stats[row['vehicle_type']] = {
                'trips': row['trips'],
                'total_km': float(row['total_km']),
                'total_finds': row['total_finds'] or 0,
            }

    # Bulk-fetch ALL vehicle acquisition dates in one query (not per-vehicle)
    vehicle_upgrades = {}
    with db_cursor() as cur:
        cur.execute("""
            SELECT item_key, upgraded_at, tx_hash FROM pilgrim.player_upgrades
            WHERE user_id = %s AND category = 'vehicles'
        """, (user_id,))
        for row in cur.fetchall():
            vehicle_upgrades[row['item_key']] = row

    from utilities.upgrade_image_utils import get_best_available_image

    for v in raw_vehicles:
        enriched = dict(v)
        vehicle_config = UPGRADE_CATALOG.get('vehicles', {}).get(v['vehicle_type'], {})
        level_stats = vehicle_config.get('levels', {}).get(v['level'], {})

        # Image fallback: walk back to nearest level with image (Lv2+ often empty)
        enriched['image_url'] = get_best_available_image('vehicles', v['vehicle_type'], v['level'])

        # Add catalog data
        enriched['description'] = vehicle_config.get('description', '')
        enriched['max_level'] = vehicle_config.get('max_level', 1)
        enriched['fuel_cost_mult'] = level_stats.get('fuel_cost_mult', 1.0)
        enriched['cost_paid'] = level_stats.get('cost', 0)

        # Lifetime stats
        lifetime = vehicle_lifetime_stats.get(v['vehicle_type'], {})
        enriched['lifetime_trips'] = lifetime.get('trips', 0)
        enriched['lifetime_km'] = lifetime.get('total_km', 0)
        enriched['lifetime_finds'] = lifetime.get('total_finds', 0)
        # Total Cost = sum of all upgrade costs from level 1 to current level
        total_cost = sum(vehicle_config.get('levels', {}).get(lv, {}).get('cost', 0) for lv in range(1, v['level'] + 1))
        enriched['lifetime_cost'] = total_cost

        # Range/speed breakdown data
        lv1_stats = vehicle_config.get('levels', {}).get(1, {})
        enriched['base_range_km'] = lv1_stats.get('max_range_km', v.get('max_range_km', 0))
        enriched['base_speed'] = lv1_stats.get('expedition_speed_mult', v.get('speed_mult', 1.0))

        # Next level preview
        next_level = v['level'] + 1
        next_stats = vehicle_config.get('levels', {}).get(next_level)
        if next_stats:
            enriched['next_level'] = next_level
            enriched['next_level_name'] = next_stats.get('name', f'Level {next_level}')
            enriched['next_level_cost'] = next_stats.get('cost', 0)
            enriched['next_level_cargo'] = next_stats.get('cargo', 0)
            enriched['next_level_speed'] = next_stats.get('expedition_speed_mult', 1.0)
            enriched['next_level_build_days'] = next_stats.get('build_time_days', 0)
        else:
            enriched['next_level'] = None  # Max level reached

        # Acquisition date from bulk-fetched data
        upgrade_row = vehicle_upgrades.get(v['vehicle_type'])
        if upgrade_row:
            enriched['acquired_at'] = upgrade_row['upgraded_at']
            enriched['acquired_at_str'] = upgrade_row['upgraded_at'].strftime('%b %d, %Y at %I:%M %p') if upgrade_row['upgraded_at'] else ''
            enriched['tx_hash'] = upgrade_row['tx_hash'] or ''
        else:
            enriched['acquired_at_str'] = 'Starting equipment'
            enriched['tx_hash'] = ''

        # Check expedition status
        exp_info = expedition_vehicles.get(v['vehicle_type'])
        if exp_info:
            enriched['on_expedition'] = True
            enriched['expedition_id'] = exp_info['id']
            enriched['expedition_destination'] = exp_info['destination']
            enriched['expedition_distance_km'] = exp_info['distance_km']
            enriched['expedition_status'] = exp_info['status']
            enriched['expedition_departed_at'] = exp_info['departed_at']
            enriched['expedition_departed_at_iso'] = exp_info['departed_at'].isoformat() + 'Z' if exp_info['departed_at'] else ''
            enriched['expedition_arrives_at_iso'] = exp_info['arrives_at'].isoformat() + 'Z' if exp_info['arrives_at'] else ''
            enriched['expedition_returns_at'] = exp_info['returns_at']
            enriched['expedition_returns_at_str'] = exp_info['returns_at'].strftime('%b %d, %Y at %I:%M %p') if exp_info['returns_at'] else ''
            enriched['expedition_returns_at_iso'] = exp_info['returns_at'].isoformat() + 'Z' if exp_info['returns_at'] else ''
        else:
            enriched['on_expedition'] = False

        owned_vehicles.append(enriched)

    # Welcome-back modal gating: compute hours_away from last meaningful activity
    welcome_back = {}
    try:
        with db_cursor() as cur:
            cur.execute("SELECT previous_login, last_login, last_meaningful_activity_at FROM pilgrim.users WHERE id = %s", (user_id,))
            urow = cur.fetchone()
        if urow and urow.get('previous_login') != urow.get('last_login'):
            from datetime import timezone
            ref = urow.get('last_meaningful_activity_at') or urow.get('previous_login') or urow.get('last_login')
            if ref:
                if ref.tzinfo is None:
                    ref = ref.replace(tzinfo=timezone.utc)
                hours_away = (datetime.now(timezone.utc) - ref).total_seconds() / 3600
                if hours_away > 1:
                    welcome_back = {'show': True, 'previous_activity_iso': ref.isoformat()}
    except Exception:
        pass

    # Get ARIA bond data (pending + completed)
    from utilities.aria_bond_utils import get_user_bonds
    raw_bonds = get_user_bonds(user_id)

    # Bulk-fetch all partner names in one query (not per-bond)
    partner_ids = [b.get('partner_id') for b in raw_bonds if b.get('partner_id')]
    partner_names = {}
    if partner_ids:
        with db_cursor() as cur:
            cur.execute("SELECT id, captain_name FROM pilgrim.users WHERE id = ANY(%s)", (partner_ids,))
            for row in cur.fetchall():
                partner_names[row['id']] = row['captain_name']

    aria_bonds = []
    for b in raw_bonds:
        partner_id = b.get('partner_id')
        partner_name = partner_names.get(partner_id, f"Captain {partner_id}") if partner_id else None
        aria_bonds.append({
            'id': b['id'],
            'landmark_name': b['landmark_name'],
            'status': b['status'],
            'partner_name': partner_name or 'Unknown',
            'partner_id': partner_id,
            'bond_tx_hash': b.get('bond_tx_hash', ''),
            'bond_image_url': b.get('bond_image_url', ''),
            'my_submitted': b.get('fragment_1_submitted') if user_id == b.get('user_id_1') else b.get('fragment_2_submitted'),
            'created_at': b['created_at'].strftime('%b %d, %Y') if b.get('created_at') else '',
            'bonded_at': b['bonded_at'].strftime('%b %d, %Y') if b.get('bonded_at') else '',
        })

    # Discovery-based range multiplier (for vehicle range display)
    from utilities.postgres_utils import get_user_discovered_landmarks
    discovered = get_user_discovered_landmarks(user_id)
    discovery_count = len(discovered) if discovered else 0
    fog_radius = min(1000, 300 + discovery_count * 50)
    range_mult = round(fog_radius / 300.0, 2)

    # Enrich vehicles with effective range
    for v in owned_vehicles:
        v['effective_range_km'] = int(v.get('max_range_km', 0) * range_mult)

    # Get income calculation with multipliers so colony UI shows effective rates
    income_data = {}
    try:
        from utilities.infrastructure_utils import calculate_accumulated_income
        income_calc = calculate_accumulated_income(user_id)
        income_data = {
            'effective_rate': income_calc.get('rate_breakdown', {}).get('actual_avg_rate', 0),
            'base_rate': income_calc.get('rate_breakdown', {}).get('base_hourly_rate', 0),
            'passive_income_mult': income_calc.get('bonuses_applied', {}).get('passive_income_mult', 1.0),
            'passive_income_source': income_calc.get('bonuses_applied', {}).get('passive_income_source'),
            'all_generation_mult': income_calc.get('bonuses_applied', {}).get('all_generation_mult', 1.0),
            'passive_income_base': income_calc.get('bonuses_applied', {}).get('passive_income_base', 0),
            'scientist_shard_mult': income_calc.get('bonuses_applied', {}).get('scientist_shard_mult', 1.0),
            'theoretical_max_rate': income_calc.get('rate_breakdown', {}).get('theoretical_max_rate', 0),
        }
    except Exception as e:
        logger.warning(f"Could not get income calc for colony: {e}")

    return {
        'user': auth.get_current_user(),
        'total_balance': total_balance,
        'active_infrastructure': active_infrastructure,
        'building_infrastructure': building_infrastructure,
        'building_equipment': building_equipment,
        'owned_vehicles': owned_vehicles,
        'aria_bonds': aria_bonds,
        'welcome_back': welcome_back,
        'now': datetime.now(),
        'discovery_count': discovery_count,
        'range_mult': range_mult,
        'income_data': income_data,
    }


def get_depot_page_data(user_id, auth):
    """Get all data needed for colony/depot page."""
    from utilities.depot_utils import get_fast_balance_and_wallet_info, get_commander_and_stats, get_pricing_info, OPERATIONS_FEE_BUFFER_DISPLAY
    from utilities.postgres_utils import get_user_replicate_assets

    total_balance, wallet_info, _ = get_fast_balance_and_wallet_info(user_id)  # FAST: no blockchain
    images = get_user_replicate_assets(user_id, asset_type='character_image', limit=1)

    # Get shop catalog with availability info (excluding items now in UPGRADE_CATALOG)
    # ALL shop items have been migrated to the unified 10-level upgrade system
    MIGRATED_TO_UPGRADES = {
        # Vehicles (now in UPGRADE_CATALOG as rover/drone/buggy paths)
        'rover_basic', 'rover_enhanced', 'rover_advanced', 'rover_elite',
        # Equipment (now scanner/life_support/cargo paths)
        'scanner_basic', 'scanner_deep', 'scanner_quantum',
        'life_support_basic', 'life_support_advanced',
        'cargo_bay', 'cargo_refrigerated',
        # Power (now generator path)
        'solar_tier2', 'solar_tier3', 'nuclear_rtg', 'fusion_reactor',
        # Research (now research path)
        'research_lab', 'research_advanced',
        # Gear (now suit path)
        'suit_exploration', 'suit_command', 'suit_logistics',
        # Automation (now automation path)
        'mining_drone', 'maintenance_drone',
    }
    # =========================================================================
    # DEPRECATED: Legacy shop_catalog disabled - all items now in upgrade_catalog
    # Existing player purchases still work via get_user_upgrade_effects()
    # =========================================================================
    shop_catalog = {}

    # Get upgrade catalog (vehicles, equipment, storage, etc.)
    try:
        from utilities.upgrades_utils import get_upgrade_catalog_for_user
        upgrade_catalog = get_upgrade_catalog_for_user(user_id)
    except ImportError:
        upgrade_catalog = {}

    # Get captain stats for display
    commander, stats = get_commander_and_stats(user_id)

    # Get upgrade cap info and active builds for UI
    try:
        from utilities.upgrades_utils import count_concurrent_upgrades, get_user_upgrade_cap, get_active_builds
        concurrent_upgrades = count_concurrent_upgrades(user_id)
        upgrade_cap = get_user_upgrade_cap(user_id)
        active_builds = get_active_builds(user_id)  # NEW system (player_upgrades)
    except ImportError:
        concurrent_upgrades = 0
        upgrade_cap = 3
        active_builds = []

    # Add infrastructure builds to active_builds
    from utilities.infrastructure_utils import get_user_infrastructure, INFRASTRUCTURE_CATALOG
    for infra in get_user_infrastructure(user_id):
        if infra.get('status') == 'building' and infra.get('ready_at'):
            ready_at = infra['ready_at']
            if hasattr(ready_at, 'tzinfo') and ready_at.tzinfo is None:
                ready_at = ready_at.replace(tzinfo=timezone.utc)
            secs = max(0, int((ready_at - datetime.now(timezone.utc)).total_seconds()))
            cat = INFRASTRUCTURE_CATALOG.get(infra['structure_type'], {})
            active_builds.append({
                'name': cat.get('name', infra['structure_type'].replace('_', ' ').title()),
                'category': 'infrastructure',
                'item_key': infra['structure_type'],
                'target_level': infra.get('level', 1),
                'seconds_remaining': secs,
                'ready_at_str': infra['ready_at'].strftime('%b %d, %Y at %I:%M %p'),
            })
    # Sort all builds by seconds remaining (soonest first)
    active_builds.sort(key=lambda b: b['seconds_remaining'])

    # Discovery-based range multiplier (for vehicle effective range display)
    from utilities.postgres_utils import get_user_discovered_landmarks
    discovered = get_user_discovered_landmarks(user_id)
    depot_discovery_count = len(discovered) if discovered else 0
    depot_fog_radius = min(1000, 300 + depot_discovery_count * 50)
    depot_range_mult = round(depot_fog_radius / 300.0, 2)

    # Build speed bonus from Logistics stat + upgrades
    try:
        from utilities.upgrades_utils import get_user_upgrade_effects
        build_time_mult = get_user_upgrade_effects(user_id).get('build_time_mult', 1.0)
    except Exception:
        build_time_mult = 1.0

    return {
        'user': auth.get_current_user(), 'current_balance': total_balance, 'wallet_info': wallet_info,
        'pricing': get_pricing_info(user_id), 'has_commander': len(images) > 0,
        'commander': images[0] if images else None,
        'stats': stats,
        'shop_catalog': shop_catalog,
        'upgrade_catalog': upgrade_catalog,
        'building_items': [],
        'operations_fee': OPERATIONS_FEE_BUFFER_DISPLAY,
        'concurrent_upgrades': concurrent_upgrades,
        'upgrade_cap': upgrade_cap,
        'active_builds': active_builds,
        'discovery_count': depot_discovery_count,
        'range_mult': depot_range_mult,
        'build_time_mult': round(build_time_mult, 3),
    }


def get_claimed_discoveries_data(user_id):
    """Get claimed discoveries with aggregated stats, plus ARIA bonds."""
    from utilities.postgres_utils import get_claimed_discoveries

    raw_discoveries = get_claimed_discoveries(user_id)

    # Normalize numeric fields to avoid Decimal serialization issues
    discoveries = []
    for d in raw_discoveries:
        normalized = dict(d)
        normalized['enhanced_value'] = float(d.get('enhanced_value') or 0)
        normalized['weight_kg'] = float(d.get('weight_kg') or 0)
        normalized['quantity'] = int(d.get('quantity') or 1)
        normalized['found_at_km'] = float(d.get('found_at_km') or 0)
        normalized['base_scientific_value'] = int(d.get('base_scientific_value') or 0)
        discoveries.append(normalized)

    # Get ARIA bonds for this user (special artifacts from shared discoveries)
    aria_bonds = []
    try:
        from utilities.aria_bond_utils import get_user_bonds, _get_commander_name
        bonds = get_user_bonds(user_id)
        for b in bonds:
            if b['status'] == 'bonded':  # Only show completed bonds
                # Determine partner
                partner_id = b['user_id_2'] if b['user_id_1'] == user_id else b['user_id_1']
                partner_name = _get_commander_name(partner_id) or f"Captain {partner_id}"
                my_name = _get_commander_name(user_id) or f"Captain {user_id}"
                sol = int(b['bonded_at'].timestamp() / 86400) if b.get('bonded_at') else '?'

                aria_bonds.append({
                    'id': b['id'],
                    'landmark': b['landmark_name'],
                    'partner_name': partner_name,
                    'my_name': my_name,
                    'sol': sol,
                    'image_url': b.get('bond_image_url'),
                    'bond_tx': b.get('bond_tx_hash'),
                    'bonded_at': b['bonded_at'].isoformat() if b.get('bonded_at') else None
                })
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not load ARIA bonds: {e}")

    from utilities.tech_utils import _get_available_sv
    available_sv = _get_available_sv(user_id)

    # Include equipment bonuses so frontend can show accurate extraction previews
    try:
        from utilities.upgrades_utils import get_user_upgrade_effects
        effects = get_user_upgrade_effects(user_id)
        discovery_value_mult = effects.get('discovery_value_mult', 1.0)
        bio_discovery_value_mult = effects.get('bio_discovery_value_mult', 1.0)
    except Exception:
        discovery_value_mult = 1.0
        bio_discovery_value_mult = 1.0

    return {
        'success': True, 'discoveries': discoveries, 'total_count': len(discoveries),
        'total_scientific_value': available_sv,
        'total_weight_kg': sum(d['weight_kg'] * d['quantity'] for d in discoveries),
        'by_rarity': {r: len([d for d in discoveries if d['rarity'] == r]) for r in ['legendary', 'rare', 'uncommon', 'common']},
        'aria_bonds': aria_bonds,
        'discovery_value_mult': discovery_value_mult,
        'bio_discovery_value_mult': bio_discovery_value_mult
    }


def get_formatted_discovery_items():
    """Get all discovery items formatted for API response."""
    from utilities.postgres_utils import get_all_discovery_items

    items = get_all_discovery_items()
    return {'items': [{
        'id': i['id'], 'item_name': i['item_name'], 'item_type': i['item_type'], 'rarity': i['rarity'],
        'description': i['description'], 'weight_kg': float(i['weight_kg'] or 0), 'stackable': i['stackable'],
        'preferred_mars_features': i['preferred_mars_features'], 'min_distance_km': float(i['min_distance_km'] or 0),
        'max_distance_km': float(i['max_distance_km']) if i['max_distance_km'] else None,
        'base_scientific_value': i['base_scientific_value'], 'base_trade_value_eth': float(i['base_trade_value_eth'] or 0),
        'exploration_enhancement_value': float(i['exploration_enhancement_value'] or 0), 'image_url': i['image_url']
    } for i in items]}
