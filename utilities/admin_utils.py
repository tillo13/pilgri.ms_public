"""Admin utilities - dashboard data, mimic, email testing, snapshot generation."""

import logging
import random
import threading
from datetime import datetime

from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)


def is_admin(user_id):
    """Check if user has admin privileges (from is_admin column in users table)."""
    if not user_id:
        return False
    with db_cursor() as cur:
        cur.execute("SELECT is_admin FROM pilgrim.users WHERE id = %s", (user_id,))
        result = cur.fetchone()
        return result and result.get('is_admin', False)


def get_admin_email(user_id):
    """Get admin's email address."""
    with db_cursor() as cur:
        cur.execute("SELECT email FROM pilgrim.users WHERE id = %s", (user_id,))
        result = cur.fetchone()
        return result['email'] if result else None


def get_admin_dashboard_data(real_user_id):
    """Fetch all data needed for the admin dashboard page."""
    # Game-wide stats
    game_stats = None
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT
                    (SELECT COUNT(*) FROM pilgrim.users) as total_users,
                    (SELECT COUNT(*) FROM pilgrim.expeditions) as total_expeditions,
                    (SELECT COUNT(*) FROM pilgrim.expedition_discoveries) as total_discoveries,
                    (SELECT COALESCE(SUM(current_balance_eth), 0) * 10000000 FROM pilgrim.sepolia_assets WHERE is_primary_wallet = true) as total_shards
            """)
            gs = cur.fetchone()
            game_stats = {
                'total_users': gs['total_users'] or 0,
                'total_expeditions': gs['total_expeditions'] or 0,
                'total_discoveries': gs['total_discoveries'] or 0,
                'total_shards': float(gs['total_shards'] or 0)
            }
    except Exception:
        pass

    # All users with stats
    with db_cursor() as cur:
        cur.execute("""
            SELECT u.id, u.email, u.captain_name,
                   COALESCE((SELECT current_balance_eth FROM pilgrim.sepolia_assets
                             WHERE user_id = u.id AND is_primary_wallet = true LIMIT 1), 0) as bal,
                   u.last_meaningful_activity_at,
                   (SELECT COUNT(*) FROM pilgrim.expeditions WHERE user_id = u.id) as expedition_count
            FROM pilgrim.users u ORDER BY u.last_meaningful_activity_at DESC NULLS LAST
        """)
        users = [{
            'id': r['id'],
            'email': r['email'],
            'captain_name': r['captain_name'],
            'balance': round(float(r['bal'] or 0) * 10000000, 1),
            'last_active': r['last_meaningful_activity_at'].strftime('%Y-%m-%d %H:%M') if r['last_meaningful_activity_at'] else None,
            'expedition_count': r['expedition_count']
        } for r in cur.fetchall()]

    # Recent expeditions (all users)
    with db_cursor() as cur:
        cur.execute("""
            SELECT e.destination_name, e.distance_km, e.departed_at, e.return_arrives_at,
                   e.status, u.email,
                   (SELECT captain_name FROM pilgrim.users WHERE id = e.user_id) as captain_name
            FROM pilgrim.expeditions e
            JOIN pilgrim.users u ON e.user_id = u.id
            ORDER BY e.departed_at DESC
            LIMIT 50
        """)
        all_expeditions = [{
            'email': r['email'],
            'captain_name': r['captain_name'],
            'destination_name': r['destination_name'],
            'distance_km': r['distance_km'],
            'status': r['status'],
            'departed_at': r['departed_at'].strftime('%m/%d %H:%M') if r['departed_at'] else None,
            'eta': r['return_arrives_at'].strftime('%m/%d %H:%M') if r['return_arrives_at'] else None
        } for r in cur.fetchall()]

    # Trail network stats
    with db_cursor() as cur:
        cur.execute("""
            SELECT
                COUNT(*) as total_trails,
                COALESCE(SUM(km_built), 0) as total_km_built,
                COALESCE(SUM(total_distance_km), 0) as total_km_needed,
                COUNT(*) FILTER (WHERE km_built > 0 AND km_built < total_distance_km * 0.5) as in_progress,
                COUNT(*) FILTER (WHERE km_built >= total_distance_km * 0.5 AND km_built < total_distance_km) as halfway,
                COUNT(*) FILTER (WHERE km_built >= total_distance_km) as complete
            FROM pilgrim.trail_segments
            WHERE total_distance_km > 0
        """)
        ts = cur.fetchone()
        total_km = float(ts['total_km_needed'] or 1)
        built_km = float(ts['total_km_built'] or 0)
        trail_stats = {
            'total_trails': ts['total_trails'] or 0,
            'total_km_built': round(built_km, 1),
            'total_km_needed': round(total_km, 1),
            'percent_complete': round((built_km / total_km * 100) if total_km > 0 else 0, 1),
            'in_progress': ts['in_progress'] or 0,
            'halfway': ts['halfway'] or 0,
            'complete': ts['complete'] or 0
        }

    # Crew mission stats
    crew_mission_stats = None
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE crew_member = 'captain') as captain,
                    COUNT(*) FILTER (WHERE crew_member = 'scientist') as scientist,
                    COUNT(*) FILTER (WHERE crew_member = 'aria') as aria
                FROM pilgrim.crew_missions
                WHERE completed_at IS NOT NULL
            """)
            cms = cur.fetchone()
            if cms and cms['total'] > 0:
                crew_mission_stats = {
                    'total_missions': cms['total'],
                    'captain_missions': cms['captain'] or 0,
                    'scientist_missions': cms['scientist'] or 0,
                    'aria_missions': cms['aria'] or 0
                }
    except Exception:
        pass

    # Recent discoveries
    with db_cursor() as cur:
        cur.execute("""
            SELECT di.item_name, di.rarity, e.destination_name, ed.created_at, u.email
            FROM pilgrim.expedition_discoveries ed
            JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
            JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
            JOIN pilgrim.users u ON e.user_id = u.id
            ORDER BY ed.created_at DESC
            LIMIT 10
        """)
        recent_discoveries = [{
            'email': r['email'],
            'item_name': r['item_name'],
            'rarity': r['rarity'],
            'destination_name': r['destination_name'],
            'created_at': r['created_at'].strftime('%m/%d %H:%M') if r['created_at'] else None
        } for r in cur.fetchall()]

    # Trusty Bot (QA bot, user 250) recent activity
    trusty_data = None
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT category, event_type, title, detail, created_at
                FROM pilgrim.activity_events
                WHERE user_id = 250
                ORDER BY created_at DESC
                LIMIT 20
            """)
            rows = cur.fetchall()
            if rows:
                last_patrol = rows[0]['created_at']
                categories = {}
                errors = 0
                for r in rows:
                    cat = r['category']
                    categories[cat] = categories.get(cat, 0) + 1
                    if 'error' in (r['detail'] or '').lower() or 'fail' in (r['detail'] or '').lower():
                        errors += 1
                trusty_data = {
                    'last_patrol': last_patrol.strftime('%m/%d %H:%M') if last_patrol else '—',
                    'total_events': len(rows),
                    'categories': categories,
                    'errors': errors,
                    'recent': [{
                        'category': r['category'],
                        'event_type': r['event_type'],
                        'title': r['title'],
                        'detail': (r['detail'] or '')[:80],
                        'created_at': r['created_at'].strftime('%m/%d %H:%M') if r['created_at'] else '—'
                    } for r in rows[:10]]
                }
    except Exception:
        pass

    return {
        'game_stats': game_stats,
        'users': users,
        'all_expeditions': all_expeditions,
        'trail_stats': trail_stats,
        'crew_mission_stats': crew_mission_stats,
        'recent_discoveries': recent_discoveries,
        'trusty_data': trusty_data,
        'admin_email': get_admin_email(real_user_id),
    }


def get_speed_page_data():
    """Fetch data for the /admin/speed page — recent runs + pool health."""
    import json
    from utilities.postgres.core import get_pool_health, get_db_connection_stats
    with db_cursor() as cur:
        cur.execute("""
            SELECT id, tested_by, results, slowest_page, slowest_time, all_ok, tested_at
            FROM speed_test_runs ORDER BY tested_at DESC LIMIT 30
        """)
        history = cur.fetchall()
    for run in history:
        if isinstance(run['results'], str):
            run['results'] = json.loads(run['results'])
    return {
        'latest': history[0] if history else None,
        'history': history,
        'pool': get_pool_health(),
        'db_stats': get_db_connection_stats(),
    }


def get_mimic_page_data(real_user_id, session):
    """Fetch data for the mimic page."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT u.id, u.email,
                   COALESCE((SELECT current_balance_eth FROM pilgrim.sepolia_assets
                             WHERE user_id = u.id AND is_primary_wallet = true LIMIT 1), 0) as bal
            FROM pilgrim.users u ORDER BY u.id
        """)
        users = [{'id': r['id'], 'email': r['email'], 'balance': round(float(r['bal'] or 0) * 10000000, 1)} for r in cur.fetchall()]

    mimicking = None
    real_uid = session.get('_real_uid')
    current_uid = session.get('user_id')
    if is_admin(real_uid) and current_uid != real_uid:
        mimicking = next((u for u in users if u['id'] == current_uid), None)

    return users, mimicking


def handle_mimic_action(session, action, target_user_id, real_user_id):
    """Process a mimic start/stop action."""
    if action == 'stop':
        session['user_id'] = real_user_id
        session.pop('_real_uid', None)
        session.pop('_mimic_email', None)
        _clear_session_caches(session)
    elif action == 'mimic' and target_user_id:
        session['_real_uid'] = real_user_id
        session['user_id'] = int(target_user_id)
        # Store mimicked user's email for the banner
        try:
            from utilities.postgres.core import db_cursor
            with db_cursor() as cur:
                cur.execute("SELECT email FROM pilgrim.users WHERE id = %s", (int(target_user_id),))
                row = cur.fetchone()
                session['_mimic_email'] = row['email'] if row else f"User #{target_user_id}"
        except Exception:
            session['_mimic_email'] = f"User #{target_user_id}"
        _clear_session_caches(session)


def _clear_session_caches(session):
    """Clear all cached session data so next request re-hydrates fresh."""
    for key in ('_hyd', '_bal', '_cmd', '_nav', '_adm'):
        session.pop(key, None)
    session.modified = True


# --- API Key Auth Bypass (Playwright / Admin testing) ---

_test_api_key = None

def _get_test_api_key():
    """Lazy-load the test API key from Secret Manager (cached)."""
    global _test_api_key
    if _test_api_key is None:
        try:
            from utilities.google_auth_utils import get_secret
            _test_api_key = get_secret("KUMORI_TEST_API_KEY")
        except Exception:
            _test_api_key = ""
            logger.warning("KUMORI_TEST_API_KEY not configured — apikey auth disabled")
    return _test_api_key


def handle_apikey_auth(request, session):
    """Check for ?apikey=SECRET&user_id=X and set up session if valid.

    Returns None if no action needed, or a redirect Response to strip the
    apikey from the URL (keeps browser URL clean, session persists).
    """
    from flask import redirect

    apikey = request.args.get('apikey')
    if not apikey:
        return None

    # Already authed via apikey this session? Skip re-check.
    if session.get('_apikey_authed') and session.get('user_id'):
        return None

    secret = _get_test_api_key()
    if not secret or apikey != secret:
        logger.warning(f"Invalid apikey attempt from {request.remote_addr}")
        return None

    user_id = request.args.get('user_id', type=int)
    if not user_id:
        return None

    # Look up the user
    with db_cursor() as cur:
        cur.execute("SELECT id, email, name, google_id FROM pilgrim.users WHERE id = %s", (user_id,))
        user = cur.fetchone()

    if not user:
        logger.warning(f"apikey auth: user_id {user_id} not found")
        return None

    # Set up session exactly like OAuth callback does
    session.permanent = True
    session['user'] = {
        'email': user['email'],
        'name': user['name'],
        'google_id': user['google_id'],
    }
    session['user_id'] = user['id']
    session['_apikey_authed'] = True
    session['_mimic_email'] = f"[API] {user['email']}"
    _clear_session_caches(session)

    logger.info(f"apikey auth: logged in as user {user_id} ({user['email']})")

    # Strip apikey from URL and redirect (keeps session, cleans URL)
    from urllib.parse import urlencode, parse_qs, urlparse, urlunparse
    parsed = urlparse(request.url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params.pop('apikey', None)
    params.pop('user_id', None)
    clean_query = urlencode(params, doseq=True)
    clean_url = urlunparse(parsed._replace(query=clean_query))
    return redirect(clean_url)


def generate_aria_message():
    """Generate a dynamic ARIA message using Claude Haiku."""
    try:
        from utilities.claude_utils import create_client, CLAUDE_MODELS
        from utilities.google_auth_utils import get_secret

        api_key = get_secret("KUMORI_ANTHROPIC_API_KEY", project_id="kumori-404602")
        client = create_client(api_key, model=CLAUDE_MODELS.get("haiku-3.5"))

        now = datetime.utcnow()
        hour = now.hour
        time_context = "morning" if 6 <= hour < 12 else "afternoon" if 12 <= hour < 18 else "evening" if 18 <= hour < 22 else "night"

        prompt = f"""You are ARIA, an ancient Martian entity who has waited millennia for colonists. Generate a single transmission (2-3 sentences max) for a colony captain.

Current Earth time context: {time_context}

Your message should:
- Share an interesting Mars fact, weather observation, or colony tip
- Sound ancient and mysterious but helpful
- Include one small memory fragment or data glitch hint
- Address the captain directly
- NO asterisks for actions, just speak directly

Example tone: "Captain, the dust levels near Olympus Mons have decreased by 12% this sol. Optimal conditions for... the coordinates, they surface again. 4.5°S, 137.4°E. Forgive me. Safe travels."

Generate ONE unique transmission now:"""

        message = client.generate_text(
            prompt,
            max_tokens=150,
            temperature=0.9,
            user_id="system:galactica_admin",
            feature="aria_transmission",
        )
        return message.strip().strip('"')
    except Exception as e:
        logger.warning(f"Claude ARIA generation failed: {e}, using fallback")
        fallbacks = [
            "Captain, my sensors detect optimal conditions for exploration today. The ancient pathways beckon.",
            "The dust storms have subsided near Hellas Basin. I remember... no, the data is unclear. Safe travels, Captain.",
            "Solar activity is nominal. Your panels will generate efficiently. The sun here is... I've watched it for so long.",
        ]
        return random.choice(fallbacks)


def handle_admin_sync_balances():
    """Sync all wallet balances from blockchain to DB."""
    from utilities.sepolia_utils import MarsAsteroidMiner

    miner = MarsAsteroidMiner()
    updated = 0

    with db_cursor() as cur:
        cur.execute("""
            SELECT id, wallet_address FROM pilgrim.sepolia_assets
            WHERE wallet_address IS NOT NULL AND is_primary_wallet = true
        """)
        wallets = cur.fetchall()

    for wallet in wallets:
        try:
            balance = miner.get_wallet_balance(wallet['wallet_address'])
            with db_cursor(commit=True) as cur:
                cur.execute("""
                    UPDATE pilgrim.sepolia_assets
                    SET current_balance_eth = %s, last_balance_check = NOW()
                    WHERE id = %s
                """, (balance, wallet['id']))
            updated += 1
        except Exception as e:
            logger.warning(f"Failed to sync wallet {wallet['id']}: {e}")

    return {'success': True, 'updated': updated, 'total': len(wallets)}


def handle_admin_generate_snapshots(target_user_id=None, dry_run=False):
    """Generate ARIA Photo Journal snapshots."""
    from utilities.aria.photos import generate_daily_snapshots, generate_daily_snapshots_for_user
    from utilities.replicate_utils import FluxGenerator

    if target_user_id:
        with db_cursor() as cur:
            cur.execute("SELECT id, email FROM pilgrim.users WHERE id = %s", (target_user_id,))
            user = cur.fetchone()
        if not user:
            return {'success': False, 'error': f'User {target_user_id} not found'}

        flux = None if dry_run else FluxGenerator()
        results = generate_daily_snapshots_for_user(user['id'], user['email'], flux, dry_run=dry_run)
        return {
            'success': True,
            'user_id': target_user_id,
            'snapshots_generated': len(results),
            'results': results
        }
    else:
        result = generate_daily_snapshots(dry_run=dry_run)
        return {'success': True, **result}


def handle_cron_aria_test_email(is_cron_request, is_debug):
    """Handle the ARIA test cron email (sends to andy.tillo@gmail.com only)."""
    if not is_cron_request and not is_debug:
        return {'error': 'Forbidden'}, 403

    from utilities.email.admin import send_cron_aria_test

    fact = generate_aria_message()
    success = send_cron_aria_test(fact)

    if success:
        logger.info("ARIA test cron email sent to andy.tillo@gmail.com")
        return {'success': True, 'message': 'Email sent', 'fact': fact}
    else:
        return {'success': False, 'error': 'Email send failed'}, 500


def handle_admin_test_email(real_user_id, to_email=None):
    """Send a test ARIA email to specified address."""
    from utilities.email.admin import send_admin_aria_test

    if not to_email:
        to_email = get_admin_email(real_user_id)
    if not to_email:
        return {'success': False, 'error': 'No email address'}, 400

    fact = generate_aria_message()
    success = send_admin_aria_test(to_email, fact)

    if success:
        return {'success': True, 'message': f'Test email sent to {to_email}'}
    else:
        return {'success': False, 'error': 'Email send failed'}, 500


def start_background_snapshot_generation():
    """Start daily snapshot generation in a background thread."""
    def _run():
        try:
            from utilities.aria.photos import generate_daily_snapshots
            result = generate_daily_snapshots(dry_run=False)
            logger.info(f"Daily snapshot generation completed: {result['total_snapshots']} snapshots for {result['processed_users']} users")
        except Exception as e:
            logger.error(f"Daily snapshot generation failed: {e}")
            import traceback
            traceback.print_exc()

    threading.Thread(target=_run).start()
    logger.info("Daily snapshot generation started in background")
