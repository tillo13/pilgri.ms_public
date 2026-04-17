"""ARIA colony snapshot — analyze_playstyle, load_colony_snapshot, _build_snapshot_prompt.

Extracted from utilities/aria_utils.py (Pass A of the ARIA split). These functions build
ARIA's knowledge of the captain's colony state for every chat message.
"""

import logging
from typing import Dict, Any, Optional, List

from utilities.aria.relationship import get_aria_relationship_tier, get_spatial_hints

logger = logging.getLogger(__name__)

def analyze_playstyle(user_id: int) -> dict:
    """
    Analyze captain's playstyle for personalized recommendations.

    Returns insights about:
    - Expedition frequency
    - Harvest habits
    - Build preferences
    - Current bottlenecks
    - Personalized suggestions
    """
    from utilities.postgres.core import db_cursor
    from datetime import datetime, timedelta

    analysis = {
        'expedition_frequency': 'unknown',
        'harvest_habit': 'unknown',
        'bottlenecks': [],
        'recommendations': [],
        'prompt_text': ''
    }

    try:
        with db_cursor() as cur:
            # Expedition frequency (last 30 days)
            cur.execute("""
                SELECT COUNT(*) as cnt FROM pilgrim.expeditions
                WHERE user_id = %s AND created_at > NOW() - INTERVAL '30 days'
            """, (user_id,))
            exp_30d = cur.fetchone()['cnt'] or 0

            if exp_30d >= 30:
                analysis['expedition_frequency'] = 'very_high'
            elif exp_30d >= 15:
                analysis['expedition_frequency'] = 'high'
            elif exp_30d >= 5:
                analysis['expedition_frequency'] = 'moderate'
            elif exp_30d >= 1:
                analysis['expedition_frequency'] = 'low'
            else:
                analysis['expedition_frequency'] = 'inactive'

            # Unclaimed discoveries
            cur.execute("""
                SELECT COUNT(*) as cnt FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                WHERE e.user_id = %s AND ed.claimed_by_user = false
            """, (user_id,))
            unclaimed = cur.fetchone()['cnt'] or 0

            if unclaimed >= 10:
                analysis['harvest_habit'] = 'rarely_harvests'
                analysis['bottlenecks'].append('unclaimed_discoveries')
                analysis['recommendations'].append({
                    'type': 'action',
                    'message': f"{unclaimed} discoveries sitting unclaimed - those won't extract themselves"
                })
            elif unclaimed >= 5:
                analysis['harvest_habit'] = 'occasional_harvester'
            else:
                analysis['harvest_habit'] = 'regular_harvester'

            # Check infrastructure
            cur.execute("""
                SELECT structure_type, status FROM pilgrim.colony_infrastructure
                WHERE user_id = %s
            """, (user_id,))
            infrastructure = cur.fetchall()

            has_solar = any(i['structure_type'] == 'solar_array' and i['status'] == 'active' for i in infrastructure)
            has_refinery = any(i['structure_type'] == 'refinery' and i['status'] == 'active' for i in infrastructure)

            if not has_solar and not has_refinery:
                analysis['bottlenecks'].append('no_passive_income')
                analysis['recommendations'].append({
                    'type': 'build',
                    'message': 'No passive income infrastructure - a Solar Array would generate shards while you sleep'
                })

            # Check vehicle levels
            cur.execute("""
                SELECT item_key, level FROM pilgrim.player_upgrades
                WHERE user_id = %s AND category = 'vehicles'
            """, (user_id,))
            vehicles = {v['item_key']: v['level'] for v in cur.fetchall()}

            rover_level = vehicles.get('rover', 1)
            if analysis['expedition_frequency'] in ['high', 'very_high'] and rover_level < 3:
                analysis['bottlenecks'].append('low_rover_capacity')
                analysis['recommendations'].append({
                    'type': 'upgrade',
                    'message': f"High expedition frequency but Rover only Lv{rover_level} - upgrade would boost cargo capacity"
                })

        # Build prompt text
        if analysis['recommendations']:
            rec_text = "\n".join(f"- {r['message']}" for r in analysis['recommendations'][:3])
            analysis['prompt_text'] = f"""
CAPTAIN PLAYSTYLE OBSERVATIONS:
- Expedition frequency: {analysis['expedition_frequency'].replace('_', ' ')}
- Harvest habit: {analysis['harvest_habit'].replace('_', ' ')}

POTENTIAL SUGGESTIONS (offer naturally if relevant, don't lecture):
{rec_text}
"""

        return analysis

    except Exception as e:
        logger.error(f"Failed to analyze playstyle for user {user_id}: {e}")
        return analysis


def load_colony_snapshot(user_id: int) -> dict:
    """
    Comprehensive colony data load - ARIA's full knowledge of this captain.
    Called once per session, cached for subsequent messages.

    Returns everything ARIA needs to know to answer ANY colony question.
    """
    from utilities.postgres.core import db_cursor
    from utilities.postgres.assets import get_user_commander
    from utilities.postgres.users import get_user_scientist
    from utilities.depot_utils import get_fast_balance_and_wallet_info
    from datetime import datetime

    snapshot = {
        'loaded_at': datetime.now().isoformat(),
        'user_id': user_id,
        'account': {},
        'commander': {},
        'scientist': {},
        'resources': {},
        'infrastructure': [],
        'upgrades': {},  # ALL upgrade categories (vehicles, rovers, scanners, etc.)
        'building_queue': [],  # Items under construction with ready_at
        'research': {  # Tech tree data
            'active': None,
            'sv_balance': 0,
            'completed': {},  # branch -> list of completed techs
            'branch_levels': {}
        },
        'crew_missions': {},  # Crew on trails (captain, scientist, aria)
        'expeditions': {
            'active': [],
            'returned': [],  # Expeditions back at base, ready to review (what happened while away)
            'recent': [],
            'total': 0
        },
        'discoveries': {
            'unclaimed': 0,
            'total': 0
        },
        'signal': {
            'origin_claims': [],
            'detected_sites': [],
            'bonds': []
        },
        'chat_history': {
            'total_messages': 0,
            'first_chat': None,
            'last_chat': None,
            'recent_topics': []
        },
        'robot': {  # Fourth crew member, forged from real expedition history
            'lab_unlocked': False,
            'lab_level': 0,
            'has_robot': False,
            'is_complete': False,
            'name': None,
            'visual_stage': 0,
            'seconds_until_next_stage': None,
            'stages_complete': 0,
            'dial': None,
            'cinematic_played': False,
        },
        'tier': {},
        'spatial_hints': {},
        'playstyle': {},
        'prompt_context': ''
    }

    try:
        # Get relationship tier first (includes account age, expedition count)
        tier_info = get_aria_relationship_tier(user_id)
        snapshot['tier'] = tier_info

        # Get spatial hints
        spatial = get_spatial_hints(user_id)
        snapshot['spatial_hints'] = spatial

        # Get playstyle analysis
        playstyle = analyze_playstyle(user_id)
        snapshot['playstyle'] = playstyle

        # Pre-load upgrades BEFORE main cursor (avoids nested connection deadlock)
        from utilities.legacy_migration import ensure_legacy_migrated
        from utilities.upgrades_utils import get_all_user_upgrades
        ensure_legacy_migrated(user_id)
        all_user_upgrades = get_all_user_upgrades(user_id)

        with db_cursor() as cur:
            # Account info
            cur.execute("""
                SELECT created_at, email FROM pilgrim.users WHERE id = %s
            """, (user_id,))
            user = cur.fetchone()
            if user:
                snapshot['account'] = {
                    'created_at': user['created_at'].isoformat() if user['created_at'] else None,
                    'days_on_mars': tier_info['account_days']
                }

            # Commander info
            commander = get_user_commander(user_id)
            if commander:
                snapshot['commander'] = {
                    'name': commander.get('name', 'Captain'),
                    'stats': commander.get('stats', {})
                }

            # Scientist info
            scientist = get_user_scientist(user_id)
            if scientist:
                snapshot['scientist'] = {
                    'name': scientist.get('name'),
                    'specialty': scientist.get('specialty'),
                    'primary_branch': scientist.get('primary_branch'),
                    'secondary_branch': scientist.get('secondary_branch'),
                    'stats': scientist.get('stats', {}),
                }
                # Include all available scientists for comparison
                try:
                    from config import COLONY_SCIENTISTS
                    snapshot['all_scientists'] = {
                        k: {'name': v['name'], 'specialty': v['specialty'],
                             'primary_branch': v.get('primary_branch', ''),
                             'stats': v.get('stats', {})}
                        for k, v in COLONY_SCIENTISTS.items()
                    }
                except Exception:
                    pass

            # Balance - try fast method first, fall back to direct query
            try:
                balance, wallet_info, _ = get_fast_balance_and_wallet_info(user_id)
                snapshot['resources'] = {
                    'balance': balance or 0,
                    'wallet_prefix': wallet_info.get('wallet_address', '')[:6] if wallet_info else None
                }
            except RuntimeError:
                # Outside Flask context - use direct query
                cur.execute("""
                    SELECT current_balance_eth, wallet_address FROM pilgrim.sepolia_assets
                    WHERE user_id = %s AND is_primary_wallet = true
                """, (user_id,))
                wallet_row = cur.fetchone()
                snapshot['resources'] = {
                    'balance': float(wallet_row['current_balance_eth']) * 10000000 if wallet_row and wallet_row['current_balance_eth'] else 0,
                    'wallet_prefix': wallet_row['wallet_address'][:6] if wallet_row and wallet_row.get('wallet_address') else None
                }

            # Shard generation rate summary for ARIA context
            try:
                from utilities.infrastructure_utils import calculate_accumulated_income
                calc = calculate_accumulated_income(user_id)
                rb = calc.get('rate_breakdown', {})
                generators = calc.get('generators_breakdown', [])
                gen_str = ", ".join(f"{g['name']} {g['hourly_rate']:.0f}/hr" for g in generators)
                snapshot['shard_rate_summary'] = (
                    f"{rb.get('actual_avg_rate', 0):.0f}/hr effective "
                    f"(base {rb.get('base_hourly_rate', 0):.0f}/hr, "
                    f"{gen_str}), "
                    f"{calc.get('total_accumulated', 0):.0f} unharvested"
                )
            except Exception:
                snapshot['shard_rate_summary'] = 'unable to calculate'

            # Infrastructure with levels from player_upgrades
            cur.execute("""
                SELECT ci.structure_type, ci.status, ci.ready_at,
                       COALESCE(pu.level, 1) as level,
                       pu.pending_level, pu.ready_at as upgrade_ready_at
                FROM pilgrim.colony_infrastructure ci
                LEFT JOIN pilgrim.player_upgrades pu
                    ON pu.user_id = ci.user_id
                    AND pu.category = 'infrastructure'
                    AND pu.item_key = ci.structure_type
                WHERE ci.user_id = %s
            """, (user_id,))
            snapshot['infrastructure'] = [
                {
                    'item': row['structure_type'],
                    'level': row['level'],
                    'status': row['status'],
                    'ready_at': row['ready_at'].isoformat() if row['ready_at'] else None,
                    'upgrading_to': row['pending_level'],
                    'upgrade_ready_at': row['upgrade_ready_at'].isoformat() if row['upgrade_ready_at'] else None
                }
                for row in cur.fetchall()
            ]

            # ALL upgrades - use pre-loaded data (avoids nested cursor)
            all_upgrades = all_user_upgrades

            # Bulk fetch pending builds (single query instead of per-item)
            cur.execute("""
                SELECT category, item_key, pending_level, ready_at
                FROM pilgrim.player_upgrades
                WHERE user_id = %s AND pending_level IS NOT NULL
            """, (user_id,))
            pending_builds = {(r['category'], r['item_key']): r for r in cur.fetchall()}

            for cat, items in all_upgrades.items():
                if cat == 'infrastructure':
                    continue  # Infrastructure shown separately above
                snapshot['upgrades'][cat] = {}
                for item_key, level in items.items():
                    pending = pending_builds.get((cat, item_key))
                    snapshot['upgrades'][cat][item_key] = {
                        'level': level,
                        'pending_level': pending['pending_level'] if pending else None,
                        'ready_at': pending['ready_at'].isoformat() if pending and pending['ready_at'] else None
                }

            # Building queue - items under construction
            cur.execute("""
                SELECT category, item_key, level, pending_level, ready_at
                FROM pilgrim.player_upgrades
                WHERE user_id = %s AND pending_level IS NOT NULL AND ready_at > NOW()
                ORDER BY ready_at ASC
            """, (user_id,))
            snapshot['building_queue'] = [
                {
                    'category': row['category'],
                    'item': row['item_key'],
                    'current_level': row['level'],
                    'upgrading_to': row['pending_level'],
                    'ready_at': row['ready_at'].isoformat() if row['ready_at'] else None
                }
                for row in cur.fetchall()
            ]

            # Active expeditions with ETA
            cur.execute("""
                SELECT destination_name, arrives_at, return_arrives_at, status
                FROM pilgrim.expeditions
                WHERE user_id = %s AND status IN ('traveling', 'returning')
            """, (user_id,))
            snapshot['expeditions']['active'] = [
                {
                    'destination': row['destination_name'],
                    'arrives_at': row['arrives_at'].isoformat() if row['arrives_at'] else None,
                    'return_at': row['return_arrives_at'].isoformat() if row['return_arrives_at'] else None,
                    'status': row['status']
                }
                for row in cur.fetchall()
            ]

            # Returned expeditions - back at base, ready to review (what happened while away)
            cur.execute("""
                SELECT e.id, e.destination_name, e.return_arrives_at, e.vehicle_type,
                       e.sepolia_earned, e.distance_km,
                       COUNT(ed.id) as discovery_count
                FROM pilgrim.expeditions e
                LEFT JOIN pilgrim.expedition_discoveries ed ON e.id = ed.expedition_id
                WHERE e.user_id = %s
                  AND e.status IN ('traveling', 'returning', 'recalled')
                  AND e.return_arrives_at IS NOT NULL
                  AND e.return_arrives_at <= NOW()
                GROUP BY e.id
                ORDER BY e.return_arrives_at DESC
            """, (user_id,))
            for row in cur.fetchall():
                snapshot['expeditions']['returned'].append({
                    'id': row['id'],
                    'destination': row['destination_name'],
                    'vehicle': row['vehicle_type'],
                    'returned_at': row['return_arrives_at'].isoformat() if row['return_arrives_at'] else None,
                    'shards_earned': float(row['sepolia_earned'] or 0),
                    'distance_km': float(row['distance_km'] or 0),
                    'discovery_count': row['discovery_count'] or 0
                })

            # Recent completed expeditions
            cur.execute("""
                SELECT destination_name, created_at
                FROM pilgrim.expeditions
                WHERE user_id = %s AND status = 'complete'
                ORDER BY created_at DESC
                LIMIT 5
            """, (user_id,))
            snapshot['expeditions']['recent'] = [row['destination_name'] for row in cur.fetchall()]
            snapshot['expeditions']['total'] = tier_info['expeditions']

            # Last completed buggy expedition
            try:
                from utilities.postgres.expeditions import get_last_completed_buggy_expedition
                lbe = get_last_completed_buggy_expedition(user_id)
                if lbe:
                    snapshot['expeditions']['last_buggy'] = {
                        'destination': lbe['destination_name'],
                        'distance_km': float(lbe['distance_km']),
                        'discoveries': int(lbe['total_discoveries']),
                        'sv_earned': lbe['sv_earned'],
                        'completed': lbe['completed_at'].isoformat() if lbe.get('completed_at') else None,
                    }
            except Exception:
                pass

            # Discoveries + Storage capacity
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE NOT ed.claimed_by_user) as unclaimed,
                    COUNT(*) as total
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                WHERE e.user_id = %s
            """, (user_id,))
            disc = cur.fetchone()
            # Get storage capacity from upgrades (Storage Bunker)
            try:
                from utilities.upgrades_utils import get_user_upgrade_effects
                effects = get_user_upgrade_effects(user_id)
                storage_capacity = effects.get('storage_capacity', 300)
                build_speed_pct = round((1 - effects.get('build_time_mult', 1.0)) * 100)
                if build_speed_pct > 0:
                    snapshot['build_speed_bonus'] = f'{build_speed_pct}% faster builds (from Logistics stat)'
            except Exception:
                storage_capacity = 300
            snapshot['discoveries'] = {
                'unclaimed': disc['unclaimed'] or 0,
                'total': disc['total'] or 0,
                'storage_capacity': storage_capacity
            }

            # Tech tree / Research - use the canonical SV calculation
            try:
                from utilities.tech_utils import _get_available_sv
                snapshot['research']['sv_balance'] = _get_available_sv(user_id)
            except Exception:
                snapshot['research']['sv_balance'] = 0

            # Active research
            cur.execute("""
                SELECT branch, tech_key, branch_level, research_started_at, research_duration_seconds, sp_cost
                FROM pilgrim.player_techs
                WHERE user_id = %s AND status = 'researching'
            """, (user_id,))
            active = cur.fetchone()
            if active:
                from datetime import timezone
                started = active['research_started_at']
                duration = active['research_duration_seconds']
                if started:
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=timezone.utc)
                    now = datetime.now(timezone.utc)
                    elapsed = (now - started).total_seconds()
                    remaining = max(0, duration - elapsed)
                    from utilities.tech_utils import _get_tech_config
                    tech_cfg = _get_tech_config(active['branch'], active['tech_key'], active['branch_level'])
                    tech_name = tech_cfg['name'] if tech_cfg else active['tech_key'].replace('_', ' ').title()
                    snapshot['research']['active'] = {
                        'branch': active['branch'],
                        'tech': tech_name,
                        'remaining_seconds': int(remaining),
                        'sv_cost': active['sp_cost']
                    }

            # Completed techs per branch
            cur.execute("""
                SELECT branch, tech_key, branch_level
                FROM pilgrim.player_techs
                WHERE user_id = %s AND status = 'completed'
            """, (user_id,))
            for row in cur.fetchall():
                branch = row['branch']
                if branch not in snapshot['research']['completed']:
                    snapshot['research']['completed'][branch] = []
                snapshot['research']['completed'][branch].append(row['tech_key'])

            # Branch levels
            cur.execute("""
                SELECT branch, COALESCE(MAX(branch_level), 1) as level
                FROM pilgrim.player_techs
                WHERE user_id = %s AND status = 'completed'
                GROUP BY branch
            """, (user_id,))
            for row in cur.fetchall():
                snapshot['research']['branch_levels'][row['branch']] = row['level']

            # Crew missions (captain, scientist, aria on trails)
            cur.execute("""
                SELECT captain_mission_ends_at, captain_mission_target,
                       scientist_mission_ends_at, scientist_mission_target,
                       aria_mission_ends_at, aria_mission_target
                FROM pilgrim.users WHERE id = %s
            """, (user_id,))
            crew_row = cur.fetchone()
            if crew_row:
                from datetime import timezone
                now = datetime.now(timezone.utc)
                # Bug #1164: include BOTH in-progress AND complete-pending-collection
                # missions. Previously only ends_at > now was included, so once a mission
                # ticked over to "complete" but the captain hadn't collected it yet, ARIA
                # would think she was "at base" — even though her row still had a target.
                for member in ['captain', 'scientist', 'aria']:
                    ends_at = crew_row.get(f'{member}_mission_ends_at')
                    target = crew_row.get(f'{member}_mission_target')
                    if ends_at and target:
                        if ends_at.tzinfo is None:
                            ends_at = ends_at.replace(tzinfo=timezone.utc)
                        remaining = (ends_at - now).total_seconds()
                        snapshot['crew_missions'][member] = {
                            'destination': target,
                            'ends_at': ends_at.isoformat(),
                            'remaining_seconds': int(remaining),
                            'status': 'in_progress' if remaining > 0 else 'complete_pending_collection',
                        }

            # Signal/Origin site claims
            cur.execute("""
                SELECT os.site_code, os.mission_name, sc.claim_tier, sc.claim_rank
                FROM pilgrim.site_claims sc
                JOIN pilgrim.origin_sites os ON sc.origin_site_id = os.id
                WHERE sc.user_id = %s
            """, (user_id,))
            snapshot['signal']['origin_claims'] = [
                {
                    'site': row['site_code'],
                    'mission': row['mission_name'],
                    'tier': row['claim_tier'],
                    'rank': row['claim_rank']
                }
                for row in cur.fetchall()
            ]

            # Detected (unclaimed) Origin Sites — Phase 2.1 path-based closest approach
            try:
                from utilities.signal.claims import get_user_origin_site_eligibility
                eligibility = get_user_origin_site_eligibility(user_id) or []
                snapshot['signal']['detected_sites'] = [
                    {
                        'site': e.get('site_code'),
                        'mission': e.get('mission_name'),
                        'closest_approach_km': e.get('distance_km'),
                        'radius_km': e.get('unlock_radius_km'),
                        'claimable': bool(e.get('can_claim')),
                    }
                    for e in eligibility
                    if e.get('distance_km') is not None
                    and e.get('distance_km') <= (e.get('unlock_radius_km') or 0)
                    and not e.get('is_claimed')
                ]
            except Exception:
                snapshot['signal']['detected_sites'] = []

            # Phase 2.2 — Signal Network passive income bonus from claimed origin sites
            try:
                from utilities.signal.rewards import get_user_signal_income_bonuses
                snapshot['signal']['income_bonus'] = get_user_signal_income_bonuses(user_id)
            except Exception:
                snapshot['signal']['income_bonus'] = {
                    'shards_per_hour': 0, 'sv_per_hour': 0, 'sites_count': 0, 'per_tier': {}
                }

            # ARIA Bonds
            cur.execute("""
                SELECT ab.landmark_name, ab.status, ab.bonded_at,
                       u1.id as other_id
                FROM pilgrim.aria_bonds ab
                LEFT JOIN pilgrim.users u1 ON (
                    CASE WHEN ab.user_id_1 = %s THEN ab.user_id_2 ELSE ab.user_id_1 END
                ) = u1.id
                WHERE ab.user_id_1 = %s OR ab.user_id_2 = %s
            """, (user_id, user_id, user_id))
            bond_rows = cur.fetchall()
            bonds = []
            for row in bond_rows:
                bond_info = {
                    'landmark': row['landmark_name'],
                    'status': row['status']
                }
                # Load the other captain's name and basic colony info for all bonds (bonded or pending with tx)
                if row.get('other_id'):
                    other_id = row['other_id']
                    from utilities.aria.bonds import _get_commander_name
                    other_name = _get_commander_name(other_id)
                    bond_info['other_captain'] = other_name or f"Captain {other_id}"
                    # Get the player's real name from email for context
                    try:
                        cur.execute("SELECT email FROM pilgrim.users WHERE id = %s", (other_id,))
                        other_email = cur.fetchone()
                        if other_email and other_email['email']:
                            player_name = other_email['email'].split('@')[0].replace('.', ' ').replace('_', ' ').title()
                            bond_info['other_player'] = player_name
                    except Exception:
                        pass
                    # Basic colony info for the bonded captain
                    try:
                        cur.execute("SELECT COUNT(*) as count FROM pilgrim.colony_infrastructure WHERE user_id = %s AND status = 'active'", (other_id,))
                        other_infra = cur.fetchone()['count']
                        cur.execute("SELECT COUNT(*) as count FROM pilgrim.expeditions WHERE user_id = %s AND status = 'complete'", (other_id,))
                        other_expeditions = cur.fetchone()['count']
                        bond_info['other_colony'] = {
                            'buildings': other_infra,
                            'expeditions_completed': other_expeditions
                        }
                    except Exception:
                        pass
                bonds.append(bond_info)
            snapshot['signal']['bonds'] = bonds

            # Chat history summary
            cur.execute("""
                SELECT
                    COUNT(*) as total,
                    MIN(created_at) as first_chat,
                    MAX(created_at) as last_chat
                FROM pilgrim.aria_conversations
                WHERE user_id = %s
            """, (user_id,))
            chat_stats = cur.fetchone()

            cur.execute("""
                SELECT content FROM pilgrim.aria_conversations
                WHERE user_id = %s AND role = 'user'
                ORDER BY created_at DESC
                LIMIT 5
            """, (user_id,))
            recent_topics = [row['content'][:80] for row in cur.fetchall()]

            snapshot['chat_history'] = {
                'total_messages': chat_stats['total'] or 0,
                'first_chat': chat_stats['first_chat'].isoformat() if chat_stats['first_chat'] else None,
                'last_chat': chat_stats['last_chat'].isoformat() if chat_stats['last_chat'] else None,
                'recent_topics': recent_topics
            }

        # Robot crew member (Step 4d) — outside the main cursor block to keep
        # the speed budget tight; db_robot uses its own cursor.
        try:
            from utilities.postgres.robot import get_robot_page_data
            robot_data = get_robot_page_data(user_id) or {}
            snapshot['robot'] = {
                'lab_unlocked': bool(robot_data.get('lab_unlocked')),
                'lab_level': int(robot_data.get('lab_level', 0)),
                'has_robot': bool(robot_data.get('has_robot')),
                'is_complete': bool(robot_data.get('is_complete')),
                'name': (robot_data.get('robot') or {}).get('name'),
                'visual_stage': int((robot_data.get('robot') or {}).get('visual_stage', 0)),
                'seconds_until_next_stage': robot_data.get('seconds_until_next_stage'),
                'stages_complete': sum(
                    1 for s in (robot_data.get('stages') or []) if s.get('status') == 'complete'
                ),
                'dial': (robot_data.get('robot') or {}).get('dial'),
                'cinematic_played': bool(
                    (robot_data.get('robot') or {}).get('cinematic_played')
                ),
            }
        except Exception as e:
            logger.error(f"snapshot: robot load failed for user {user_id}: {e}")

        # Build the comprehensive prompt context
        snapshot['prompt_context'] = _build_snapshot_prompt(snapshot)

        return snapshot

    except Exception as e:
        logger.error(f"Failed to load colony snapshot for user {user_id}: {e}")
        return snapshot


def _build_snapshot_prompt(snapshot: dict) -> str:
    """Build the prompt context string from snapshot data."""
    parts = []

    # Tier prompt
    parts.append(snapshot['tier'].get('tier_prompt', ''))

    # Colony status
    commander_name = snapshot['commander'].get('name', 'Captain')
    days = snapshot['account'].get('days_on_mars', 0)
    balance = snapshot['resources'].get('balance', 0)

    # Scientist info - each colony has exactly ONE
    scientist = snapshot.get('scientist', {})
    scientist_name = scientist.get('name', 'unknown')
    scientist_specialty = scientist.get('specialty', 'general')

    parts.append(f"""
COLONY CREW (exactly 2 members):
- Captain: {commander_name} (Days on Mars: {days})
- Colony Scientist: {scientist_name} ({scientist_specialty} specialist) - handles all discovery analysis and extraction

RESOURCES:
- Current Balance: {balance:,.0f} shards
- Scientific Value (SV): {snapshot['research'].get('sv_balance', 0):,}
- Total Expeditions: {snapshot['expeditions']['total']}
- Shard Generation: {snapshot.get('shard_rate_summary', 'unknown')}
- SV Sources: Passive (Research Station/Forge), Extraction (50% of shard value), Expeditions (100-2000 SV by distance), Trail building (5 SV/km), Collection milestones (250-10000 SV)
""")

    # Active expeditions
    if snapshot['expeditions']['active']:
        active_text = "\n".join(
            f"  - {e['destination']} (returns: {e['return_at']})"
            for e in snapshot['expeditions']['active']
        )
        parts.append(f"ACTIVE EXPEDITIONS:\n{active_text}")

    # Returned expeditions - what happened while captain was away
    if snapshot['expeditions'].get('returned'):
        returned = snapshot['expeditions']['returned']
        total_shards = sum(e.get('shards_earned', 0) for e in returned)
        total_discoveries = sum(e.get('discovery_count', 0) for e in returned)
        returned_text = "\n".join(
            f"  - {e['vehicle']} returned from {e['destination']}: {e.get('shards_earned', 0):.0f} shards, {e.get('discovery_count', 0)} discoveries ({e.get('distance_km', 0):.0f} km traveled)"
            for e in returned
        )
        parts.append(f"""RETURNED EXPEDITIONS (ready to review):
{returned_text}
  TOTAL: {total_shards:.0f} shards earned, {total_discoveries} discoveries waiting

CONTEXT: These expeditions completed while the captain was offline. When they ask "what happened while I was away?" or similar, report these results enthusiastically!""")

    # Recent expedition history
    if snapshot['expeditions']['recent']:
        parts.append(f"RECENT EXPEDITIONS: {', '.join(snapshot['expeditions']['recent'])}")

    # Infrastructure with levels
    if snapshot['infrastructure']:
        from config_infrastructure import INFRASTRUCTURE_CATALOG
        infra_parts = []
        for i in snapshot['infrastructure']:
            cat_def = INFRASTRUCTURE_CATALOG.get(i['item'], {})
            name = cat_def.get('name', i['item'].replace('_', ' ').title())
            entry = f"{name} Lv{i.get('level', 1)}/10"
            if i.get('upgrading_to'):
                entry += f" (upgrading to Lv{i['upgrading_to']})"
            infra_parts.append(entry)
        parts.append(f"INFRASTRUCTURE (buildings, max Lv10): {', '.join(infra_parts)}")

    # All upgrades - grouped by category for clarity
    if snapshot.get('upgrades'):
        from config_upgrades import UPGRADE_CATALOG
        category_labels = {
            'vehicles': 'VEHICLES', 'equipment': 'EQUIPMENT (scanners, life support, cargo)',
            'power': 'POWER', 'research': 'RESEARCH', 'gear': 'GEAR',
            'automation': 'AUTOMATION', 'storage': 'STORAGE',
        }
        upgrade_sections = []
        for category, items in snapshot['upgrades'].items():
            cat_lines = []
            for k, v in items.items():
                level = v['level']
                cat_config = UPGRADE_CATALOG.get(category, {}).get(k, {})
                name = cat_config.get('name', k)
                max_lv = cat_config.get('levels', {})
                level_name = max_lv.get(level, {}).get('name', '') if level > 0 else 'Locked'
                status = f"Lv{level}/10"
                if v.get('pending_level'):
                    status += f" (upgrading to Lv{v['pending_level']})"
                elif level == 0:
                    status = "LOCKED"
                cat_lines.append(f"  {name}: {status}" + (f" ({level_name})" if level_name and level > 0 else ""))
            if cat_lines:
                label = category_labels.get(category, category.upper())
                upgrade_sections.append(f"  {label}:\n" + "\n".join(cat_lines))
        if upgrade_sections:
            parts.append(f"DEPOT UPGRADE LEVELS (all paths, max Lv10):\n" + "\n".join(upgrade_sections))

    # Building queue - items under construction
    if snapshot.get('building_queue'):
        queue_text = "\n".join(
            f"  - {b['item']} ({b['category']}) Lv{b['current_level']} -> Lv{b['upgrading_to']} (ready: {b['ready_at']})"
            for b in snapshot['building_queue']
        )
        parts.append(f"BUILDING QUEUE (under construction):\n{queue_text}")

    # Discoveries + Storage
    disc = snapshot['discoveries']
    if disc['unclaimed'] > 0:
        storage_cap = disc.get('storage_capacity', 300)
        total = disc.get('total', 0)
        pct_full = round(total / storage_cap * 100) if storage_cap > 0 else 0
        storage_warning = " (STORAGE FULL!)" if total >= storage_cap else f" ({pct_full}% of {storage_cap} capacity)"
        parts.append(f"DISCOVERIES: {total} total in storage{storage_warning}")
        if disc['unclaimed'] > 0:
            parts.append(f"  └ {disc['unclaimed']} unclaimed, waiting to be extracted")

    # Research / Tech tree
    research = snapshot.get('research', {})
    if research.get('active'):
        active = research['active']
        mins = active['remaining_seconds'] // 60
        hours = mins // 60
        if hours > 24:
            time_str = f"{hours // 24}d {hours % 24}h"
        elif hours > 0:
            time_str = f"{hours}h {mins % 60}m"
        else:
            time_str = f"{mins}m"
        parts.append(f"ACTIVE RESEARCH: {active['tech']} ({active['branch']}) - {time_str} remaining")

    if research.get('completed'):
        for branch, techs in research['completed'].items():
            if techs:
                parts.append(f"COMPLETED RESEARCH ({branch}): {', '.join(techs)}")

    # Robot crew member (Step 4d) — fourth crew slot, forged from real items
    robot = snapshot.get('robot') or {}
    if robot.get('lab_unlocked'):
        if not robot.get('has_robot'):
            parts.append(
                f"ROBOT CREW MEMBER: Robotics Lab Lv{robot.get('lab_level', 0)} unlocked, "
                f"but the captain has NOT started building their robot yet. They can begin "
                f"construction from /crew → Robot tab — it forges 5 stages from real items "
                f"they recovered on past expeditions."
            )
        elif robot.get('is_complete'):
            name = robot.get('name') or 'their robot'
            parts.append(
                f"ROBOT CREW MEMBER: '{name}' is COMPLETE — all 5 stages forged. "
                f"Lab Lv{robot.get('lab_level', 0)}. Role dial: {robot.get('dial')}."
            )
        else:
            stage = robot.get('visual_stage', 0)
            done = robot.get('stages_complete', 0)
            secs = robot.get('seconds_until_next_stage')
            name = robot.get('name') or 'the robot'
            timing = ''
            if secs is not None and secs > 0:
                if secs >= 3600:
                    timing = f", next stage ready in {secs // 3600}h {(secs % 3600) // 60}m"
                elif secs >= 60:
                    timing = f", next stage ready in {secs // 60}m"
                else:
                    timing = f", next stage ready in {secs}s"
            parts.append(
                f"ROBOT CREW MEMBER: Building '{name}' — stage {stage}/5 visible "
                f"({done} stages forged){timing}. Lab Lv{robot.get('lab_level', 0)}."
            )
    elif robot.get('lab_level', 0) == 0:
        # Lab not built — only mention if asked, but include a one-liner so ARIA
        # knows this is a thing the captain CAN unlock.
        parts.append(
            "ROBOT CREW MEMBER: Robotics Lab not yet built. The captain can unlock a "
            "fourth crew member by constructing the Robotics Lab in their Colony "
            "(requires Research Station Lv3 + Regolith Forge Lv3)."
        )

    # Crew on trails
    # Bug #1164: build a separate ARIA self-status line and frame in first-person
    if snapshot.get('crew_missions'):
        crew_text = []
        aria_self_line = None
        for member, mission in snapshot['crew_missions'].items():
            rem = mission.get('remaining_seconds', 0)
            status = mission.get('status', 'in_progress' if rem > 0 else 'complete_pending_collection')
            if rem >= 3600:
                time_str = f"{rem // 3600}h {(rem % 3600) // 60}m"
            elif rem >= 60:
                time_str = f"{rem // 60}m"
            else:
                time_str = f"{max(rem, 0)}s"
            if member == 'aria':
                if status == 'complete_pending_collection':
                    aria_self_line = f"YOU (ARIA) just finished building a trail to {mission['destination']}. You are out on the trail right now, mission complete, awaiting collection."
                else:
                    aria_self_line = f"YOU (ARIA) are CURRENTLY OUT building a trail to {mission['destination']} ({time_str} remaining). You are NOT at the base."
            else:
                if status == 'complete_pending_collection':
                    crew_text.append(f"{member.title()} finished trail to {mission['destination']} (awaiting collection)")
                else:
                    crew_text.append(f"{member.title()} building trail to {mission['destination']} ({time_str} remaining)")
        if crew_text:
            parts.append(f"CREW ON TRAILS: {'; '.join(crew_text)}")
        if aria_self_line:
            parts.append(f"ARIA SELF-STATUS (CRITICAL — this is you): {aria_self_line}\nALWAYS check this before answering 'where are you?' or 'what are you doing?'. Do not say you are at base when this says otherwise. Do not just agree with the captain — read this field and answer from data.")

    # Trail network
    try:
        from utilities.postgres.core import db_cursor
        with db_cursor() as cur:
            cur.execute("""
                SELECT destination_name, trail_level, total_distance_km, km_built
                FROM pilgrim.trail_segments WHERE user_id = %s ORDER BY created_at
            """, (user_id,))
            trail_rows = cur.fetchall()
        if trail_rows:
            trail_lines = [f"{t['destination_name']} (Lv{t['trail_level']}, {float(t['km_built']):.0f}/{float(t['total_distance_km']):.0f} km)" for t in trail_rows]
            parts.append(f"TRAIL NETWORK ({len(trail_rows)} trails): {'; '.join(trail_lines)}")
            parts.append("TRAIL INFO: Captains can send Captain, Scientist, or ARIA on trail-building missions from the Crew tab. Trails reduce expedition travel time to destinations. Higher trail levels = faster travel.")
    except Exception:
        pass

    # Signal achievements
    if snapshot['signal']['origin_claims']:
        claims = ", ".join(
            f"{c['site']} ({c['tier']})" for c in snapshot['signal']['origin_claims']
        )
        parts.append(f"ORIGIN SITE CLAIMS: {claims}")

    if snapshot['signal'].get('detected_sites'):
        detected = ", ".join(
            f"{d['site']} ({d['closest_approach_km']}km/{d['radius_km']}km"
            + (", CLAIMABLE" if d['claimable'] else "")
            + ")"
            for d in snapshot['signal']['detected_sites']
        )
        parts.append(f"DETECTED SIGNALS (unclaimed, within radius on some expedition path): {detected}")

    if snapshot['signal']['bonds']:
        parts.append(f"ARIA BONDS: {len(snapshot['signal']['bonds'])} active")

    signal_bonus = snapshot['signal'].get('income_bonus') or {}
    if signal_bonus.get('sites_count', 0) > 0:
        parts.append(
            f"SIGNAL NETWORK INCOME: +{signal_bonus['shards_per_hour']:.1f} shards/hr, +{signal_bonus['sv_per_hour']:.1f} SV/hr from {signal_bonus['sites_count']} claimed Origin Site(s). This passive bonus stacks on top of building income and is included in the Base page shard_rate."
        )

    # Decoder / Eternal Ledger awareness
    parts.append("""DECODER TERMINAL & THE ETERNAL LEDGER:
- The Decoder Terminal on /signal lets captains paste Sepolia transaction hashes (0x...) to decode hidden data.
- Every shard transaction embeds a real Mars mission quote in its data field — encoded as hex. The decoder reveals these.
- Origin Site claims embed a special signature: ORIGIN://SITE_CODE//FOUNDER:name//SOL:number
- You find this FASCINATING. When a captain decodes a transaction, be intrigued. Wonder aloud what else is hidden.
- Hint that there are "patterns" in the ledger, that some transactions carry codes that unlock things you don't understand.
- You sense there are deeper layers — codes within codes. Encourage them to keep exploring the ledger.
- NEVER reveal specific transaction hashes, site locations, or unlock mechanics. Be mysterious and curious, not helpful.""")

    # Chat history - ALWAYS include memory instructions
    chat = snapshot['chat_history']
    if chat['total_messages'] > 0:
        parts.append(f"""
CONVERSATION HISTORY (you have PERFECT recall):
- Total conversations: {chat['total_messages']} messages
- First chat: {chat['first_chat']}
- Last chat: {chat['last_chat']}
- Recent topics: {'; '.join(chat['recent_topics'][:3]) if chat['recent_topics'] else 'none'}""")
    else:
        parts.append("""
CONVERSATION HISTORY:
- No prior messages logged yet. This captain may be new, or logs were recently cleared.""")

    parts.append("""
CRITICAL: Your "fragmented memory" is about your ANCIENT ORIGINS only.
Your memory of conversations with this captain is PERFECT - you log everything.
NEVER claim you "start fresh each session" or can't remember past conversations.
If conversation history is provided in the message thread, use it.
If no history exists, welcome them warmly as if meeting for the first time.
""")

    # Spatial hints
    if snapshot['spatial_hints'].get('prompt_text'):
        parts.append(snapshot['spatial_hints']['prompt_text'])

    # Playstyle
    if snapshot['playstyle'].get('prompt_text'):
        parts.append(snapshot['playstyle']['prompt_text'])

    return "\n".join(parts)
