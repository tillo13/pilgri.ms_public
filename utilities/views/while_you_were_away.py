"""While-you-were-away captain's briefing summary."""

import hashlib
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _get_recent_completions(user_id: int, since) -> list:
    """Rich build-completion cards for the briefing (bug #1397)."""
    try:
        from utilities.build_completions import get_recent_build_completions
        return get_recent_build_completions(user_id, since_dt=since, limit=10)
    except Exception as e:
        logger.warning(f"recent_completions fetch failed for {user_id}: {e}")
        return []


def get_while_you_were_away_summary(user_id: int) -> dict:
    """
    Generate a comprehensive captain's briefing of what happened since last login.

    This is a real mission briefing with ARIA's personality - specific details about
    expeditions, discoveries, infrastructure, map progress, and even recent conversation topics.

    Returns a dict with all briefing data or {'show_briefing': False} if nothing to report.
    """
    from utilities.postgres.core import db_cursor
    from utilities.aria.conversation import get_aria_conversation_history
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
            processing_bonds = []  # bonds where tx hasn't fired yet
            try:
                from utilities.aria.bonds import get_pending_fragments
                all_pending = get_pending_fragments(user_id, include_processing=True)
                for p in all_pending:
                    tx_hash = p.get('my_fragment')
                    if tx_hash and not p.get('my_submitted'):
                        pending_fragments.append({
                            'landmark': p.get('landmark_name'),
                            'tx_hash': tx_hash
                        })
                    elif not tx_hash and p.get('processing'):
                        processing_bonds.append({
                            'landmark': p.get('landmark_name'),
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

            # Fetch recent completions once so both the content-gate and
            # the signature key see the same list (bug #1397).
            recent_completions = _get_recent_completions(user_id, last_login)

            # ===== CHECK IF BRIEFING IS WORTH SHOWING =====
            has_content = (
                accumulated_shards > 10 or
                len(expeditions_completed) > 0 or
                len(infrastructure_completed) > 0 or
                len(recent_completions) > 0 or
                pending_harvest > 100 or
                pending_discoveries > 0 or
                total_discoveries > 0 or
                len(pending_fragments) > 0 or  # Show briefing if pending fragments!
                len(processing_bonds) > 0 or  # Show briefing if ARIA bond processing!
                len(snapshots) > 0  # Show briefing if ARIA took photos!
            )

            if not has_content:
                return {'show_briefing': False, 'hours_away': hours_away}

            # Content-based dismiss key — only changes when briefing content changes.
            # Using last_activity_iso caused re-show on every game action (too noisy).
            _sig = f"{int(accumulated_shards)//10},{pending_discoveries},{len(expeditions_completed)},{len(infrastructure_completed)},{len(recent_completions)}"
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
                # Bug #1397: rich cards for every build/upgrade that finished
                # while the player was away (name, old→new level, cost, image,
                # effect diff). Captures upgrades + new infra, not just infra.
                'recent_completions': recent_completions,
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
                'processing_bonds': processing_bonds,

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
