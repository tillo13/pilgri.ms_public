"""
Pilgrims - Mars Colony Character Creation Game
Minimal routing file - all logic in utilities/
"""

from functools import wraps
from datetime import timedelta, datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, g, Response, stream_with_context
from werkzeug.routing import IntegerConverter
import logging
import time
import os
import threading

from config import APP_NAME, SECRET_KEY_ID, DEV_SECRET_KEY, DEFAULT_HOST, PORT_RANGE_START, get_available_port, kill_port_processes

# Cache-bust static files on each deploy (timestamp at startup)
STATIC_V = str(int(time.time()))
from utilities.replicate_utils import FluxGenerator, process_uploaded_image, animate_character_video
from utilities.google_auth_utils import SimpleGoogleAuth, get_secret
from utilities.postgres.core import db_cursor
from utilities.postgres.assets import (
    set_primary_commander,
    delete_asset,
    rename_captain_with_validation,
)
from utilities.postgres.expeditions import (
    get_recent_discoveries,
    get_discovery_item_details,
    claim_expedition_discovery,
)
from utilities.expeditions.formatters import (
    get_expedition_history_payload,
    get_expedition_items_payload,
)
from utilities.postgres.shop import get_unified_activity
from utilities.postgres.users import get_user_scientist, get_user_by_id
from utilities.postgres.trails import (
    get_aria_skills,
    complete_crew_mission,
    get_trail_progress,
)
from utilities.postgres.wallets import sync_all_wallet_balances
from utilities.expeditions.lifecycle import (
    complete_expedition_if_ready, claim_all_discoveries,
    get_discovery_progress_formatted, start_expedition_from_request,
    recall_expedition,
)
from utilities.expeditions.page_data import get_expeditions_page_data
from utilities.expeditions.preview import (
    get_expedition_cost_preview_formatted, get_expedition_cost_preview_bulk_formatted, get_expedition_preview,
)
from utilities.expeditions.trails import handle_trail_build_request, get_trail_consumables_data
from utilities.discovery_utils import shard_all_discoveries
from utilities.depot_utils import (
    purchase_stat_reroll, purchase_character_modification,
    process_asteroid_impact, generate_commander_stats, initialize_character_session,
    clear_character_session, get_arrival_mining_data, get_arrival_commander_data,
    get_arrival_deploy_data, handle_auth_callback, get_mars_conditions,
    get_dashboard_page_data, get_depot_page_data, get_claimed_discoveries_data,
    start_video_generation, get_formatted_discovery_items, build_recent_activity,
    start_deploy_video_generation, handle_leader_selection, get_mars_location_data,
    handle_custom_commander_upload,
    get_colony_page_data, get_live_balance_and_wallet_info, invalidate_balance_cache,
)
from utilities.infrastructure_utils import (
    get_infrastructure_page_data, handle_infrastructure_build,
    handle_accumulated_income, claim_accumulated_income, record_science_value,
    get_xenobiology_status, run_xenobiology_experiment, upgrade_xenobiology_stat,
)
from utilities.signal_utils import (
    get_signal_page_data, get_signal_page_render_data,
    handle_origin_site_claim, handle_origin_site_visit,
    claim_echo_site,
    decode_lost_signal_site,
    get_user_signal_claims, get_puzzle_solvers, decode_signal_tx,
)
from utilities.tech_utils import (
    get_research_page_data, get_user_tech_status, start_research,
    get_research_progress, cancel_research,
)
from utilities.shop_utils import get_user_equipment_data
from utilities.upgrades_utils import get_upgrade_catalog_for_user, get_vehicle_for_expedition
from utilities.claude_utils import brainstorm_chat
from utilities.aria.handlers import get_aria_album_data, handle_aria_chat_request
from utilities.aria.animations import get_contextual_hint
from utilities.admin_utils import (
    is_admin,
    get_admin_dashboard_data, handle_mimic_action, get_mimic_page_data,
    handle_cron_aria_test_email, start_background_snapshot_generation,
    handle_admin_generate_snapshots, handle_admin_sync_balances, handle_admin_test_email,
    handle_apikey_auth,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

kill_port_processes(PORT_RANGE_START)
app = Flask(__name__)


# GA4 tag injection — registers `ga_snippet(slug)` for use in base.html
try:
    from utilities.gtag import snippet as _ga_snippet
    app.jinja_env.globals['ga_snippet'] = _ga_snippet
except Exception:
    pass
# Cross-app visitor logging → kumori_ops.visitor_log
try:
    from utilities.visitor_logging import install_middleware as _install_visitor_logging
    _install_visitor_logging(app, 'galactica')
except Exception as _vl_e:
    pass

# Custom URL converter for signed integers (supports negative IDs for origin site items)
class SignedIntConverter(IntegerConverter):
    regex = r'-?\d+'
app.url_map.converters['signed_int'] = SignedIntConverter

try:
    app.secret_key = get_secret(SECRET_KEY_ID)
except Exception:
    app.secret_key = DEV_SECRET_KEY
    logger.warning("Using dev secret key")

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

auth = SimpleGoogleAuth(app)

# Request timing middleware - logs page load times to console
@app.before_request
def force_canonical_host():
    host = request.headers.get('Host', '')
    if host.startswith('www.'):
        return redirect(f'https://pilgri.ms{request.full_path}', code=301)

@app.before_request
def start_timer():
    """Start timing the request + reset per-request DB-call counter."""
    g.start_time = time.time()
    from utilities.postgres.core import reset_db_counter, set_db_context
    reset_db_counter()
    set_db_context(f"{request.method} {request.path}")

@app.before_request
def check_apikey_auth():
    """Allow ?apikey=SECRET&user_id=X to bypass OAuth (Playwright/admin testing)."""
    if 'apikey' not in request.args:
        return  # Fast path — no param, no work
    result = handle_apikey_auth(request, session)
    if result:
        return result  # Redirect to strip apikey from URL

@app.before_request
def check_first_contact():
    """Intercept page loads for pending ARIA bond first-contact cinematic."""
    from utilities.aria.first_contact import check_pending_first_contact
    if check_pending_first_contact(request.path, request.method, auth.is_authenticated(), session):
        return redirect('/aria-first-contact')

@app.before_request
def check_signal_cinematic():
    """Phase 2.3b: intercept page loads for pending signal-claim cinematic."""
    from utilities.aria.signal_cinematic import check_pending_signal_cinematic, get_pending_redirect_id
    if check_pending_signal_cinematic(request.path, request.method, auth.is_authenticated(), session):
        exp_id = get_pending_redirect_id(session.get('user_id'))
        if exp_id:
            return redirect(f'/signal-claim/{exp_id}')

@app.after_request
def log_request_time(response):
    """Log request duration to console for performance monitoring."""
    if hasattr(g, 'start_time'):
        duration = (time.time() - g.start_time) * 1000  # Convert to ms
        # Color code: green <200ms, yellow <500ms, red >=500ms
        if duration < 200:
            color = '\033[92m'  # Green
        elif duration < 500:
            color = '\033[93m'  # Yellow
        else:
            color = '\033[91m'  # Red
        reset = '\033[0m'

        # Add user identification if available
        user_id = session.get('user_id')
        captain_name = session.get('_cmd', '')
        user_tag = f" [{captain_name or f'user:{user_id}'}]" if user_id else ""

        from utilities.postgres.core import get_db_counter, DB_CALL_WARN_THRESHOLD
        db_count = get_db_counter()
        db_tag = f" [db:{db_count}]" if db_count else ""
        logger.info(f"{color}⏱️  {request.method} {request.path}{user_tag} → {duration:.1f}ms{db_tag}{reset}")
        if db_count > DB_CALL_WARN_THRESHOLD and not request.path.startswith('/static'):
            logger.warning(
                f"🐌 SLOW: {request.method} {request.path} issued {db_count} db_cursor opens "
                f"(threshold {DB_CALL_WARN_THRESHOLD}). Likely N+1 — prefetch + pass-through."
            )
    return response

# Force HTTPS and set security headers
@app.after_request
def set_security_headers(response):
    """Add security headers including HSTS to force HTTPS."""
    # Strict-Transport-Security: Tell browsers to always use HTTPS
    # max-age=31536000 = 1 year, includeSubDomains covers all subdomains
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    # Prevent clickjacking
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    # Prevent MIME type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

try:
    flux = FluxGenerator()
    logger.info(f"{APP_NAME} initialization complete")
except Exception as e:
    logger.error(f"Failed to initialize FluxGenerator: {e}")
    flux = None

@app.context_processor
def inject_global_stats():
    """Inject global user stats into all templates. Delegates to utilities.session.user_hydration."""
    from utilities.session.user_hydration import build_global_context
    return build_global_context(auth, STATIC_V)



def handle_api_error(func):
    """Decorator for consistent API error handling"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"{func.__name__} failed: {e}")
            return jsonify({'success': False, 'error': str(e)})
    wrapper.__name__ = func.__name__
    return wrapper

def login_required(f):
    """Require authentication for route. Sets g.user_id for convenience."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not auth.is_authenticated():
            return redirect(url_for('login'))
        g.user_id = session.get('user_id')
        return f(*args, **kwargs)
    return decorated_function


def cron_only(f):
    """Reject non-cron traffic. GAE adds the X-Appengine-Cron header on all cron.yaml calls."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not request.headers.get('X-Appengine-Cron') and not app.debug:
            logger.warning(f"Cron endpoint {request.path} called without X-Appengine-Cron header")
            return jsonify({'error': 'Forbidden'}), 403
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# PAGE ROUTES
# ============================================================================

@app.route('/b4c9ebbc8faa4d7b8b2b8104b6511fee.txt')
def indexnow_key():
    """Serve IndexNow verification key."""
    return Response('b4c9ebbc8faa4d7b8b2b8104b6511fee', mimetype='text/plain')


@app.route('/sitemap.xml')
def sitemap():
    from utilities.static.feeds import SITEMAP_XML
    return Response(SITEMAP_XML, mimetype='application/xml')

@app.route('/robots.txt')
def robots():
    from utilities.static.feeds import ROBOTS_TXT
    from utilities.visitor_logging import append_bot_block
    return Response(append_bot_block(ROBOTS_TXT), mimetype='text/plain')

@app.route('/feed.xml')
def atom_feed():
    """Atom feed of changelog entries for search engine discovery."""
    from utilities.static.feeds import ATOM_FEED_XML
    return Response(ATOM_FEED_XML, mimetype='application/atom+xml')

@app.route('/')
def home():
    """Home page - works for both anonymous and authenticated users"""
    logger.info(f"🏠 HOME - User-Agent: {request.headers.get('User-Agent', 'unknown')[:80]}")
    logger.info(f"🏠 HOME - Authenticated: {auth.is_authenticated()}")

    if auth.is_authenticated():
        data = get_dashboard_page_data(session.get('user_id'), auth)
        if 'redirect' in data:
            return redirect(url_for(data['redirect']))
        return render_template('home.html', active_tab='home', **data)
    else:
        # Anonymous user - show mining/onboarding flow
        user_id = session.get('user_id') if auth.is_authenticated() else None
        data = get_arrival_mining_data(session, user_id)
        if 'redirect' in data:
            return redirect(url_for(data['redirect']))
        return render_template('home.html', active_tab='home', user=None, **data)

@app.route('/about')
def about():
    """About page - redirects to /lore which now includes 'Why This Exists' section"""
    return redirect(url_for('lore'))

@app.route('/crew')
def crew():
    """Crew page - works for both anonymous and authenticated users"""
    if auth.is_authenticated():
        from utilities.views.arrival import get_crew_page_data_authenticated
        data = get_crew_page_data_authenticated(session.get('user_id'))
        return render_template('crew.html', active_tab='crew', user=auth.get_current_user(), **data)
    data = get_arrival_commander_data(session, None)
    if 'redirect' in data:
        return redirect(url_for(data['redirect']))
    return render_template('crew.html', active_tab='crew', user=None, **data)


# Deep-link shortcuts to specific crew tabs. Each redirects to /crew with the
# right ?tab= so the JS tab-switcher lands on the desired tab.
@app.route('/narog')
def narog_shortcut():
    return redirect(url_for('crew') + '?tab=robot')

@app.route('/captain')
def captain_shortcut():
    return redirect(url_for('crew') + '?tab=captain')

@app.route('/scientist')
def scientist_shortcut():
    return redirect(url_for('crew') + '?tab=scientist')

@app.route('/aria')
def aria_shortcut():
    return redirect(url_for('crew') + '?tab=aria')

@app.route('/trails-tab')
def trails_tab_shortcut():
    return redirect(url_for('crew') + '?tab=trails')


# ============================================================================
# ROBOT CREW MEMBER API — Step 4d ships with stub stage advance.
# Step 4c will replace _stub_advance_one_stage() with real Sepolia + Kontext;
# the route surface stays identical so the frontend never changes.
# ============================================================================

@app.route('/api/robot/status')
@login_required
@handle_api_error
def api_robot_status():
    """Return latest robot state — auto-ticks ready stages first."""
    from utilities.postgres.robot import get_robot_page_data
    return jsonify({'success': True, 'data': get_robot_page_data(g.user_id)})


@app.route('/api/robot/preview')
@login_required
@handle_api_error
def api_robot_preview():
    """Preview a randomized stage-source pick (for re-roll UI)."""
    from utilities.postgres.robot import (
        pick_stage_sources, check_robot_gate, RobotGateError,
        compute_craftsmanship_score, CRAFTSMANSHIP_MAX,
        STAT_KEYS, STAT_BASE,
    )
    from utilities.postgres.users import get_user_scientist
    sci = get_user_scientist(g.user_id) or {}
    sci_name = sci.get('name') or 'Scientist'
    gate = check_robot_gate(g.user_id)
    if not gate['met']:
        return jsonify({'success': False, 'gate': gate, 'scientist_name': sci_name,
                        'error': 'Gate not met'}), 200
    try:
        sources = pick_stage_sources(g.user_id)
    except RobotGateError as e:
        return jsonify({'success': False, 'gate': gate, 'scientist_name': sci_name,
                        'error': str(e)}), 200
    score = compute_craftsmanship_score(sources)
    # 2026-04-30: stats are flat 5/100 baseline now, not item-derived.
    profile = {k: STAT_BASE for k in STAT_KEYS}
    return jsonify({
        'success': True, 'gate': gate, 'scientist_name': sci_name,
        'sources': sources, 'craftsmanship_score': score,
        'craftsmanship_max': CRAFTSMANSHIP_MAX,
        'stat_profile': profile,
    })


@app.route('/api/robot/build', methods=['POST'])
@login_required
@handle_api_error
def api_robot_build():
    """Start a new robot build. Accepts an optional locked-in `sources` list
    (from the /api/robot/preview re-roll UI); falls back to a fresh pick."""
    from utilities.postgres.robot import start_build_with_name_prefetch
    cmd_name = session.get('_cmd') or None
    sci_name = session.get('scientist_name')
    body = request.get_json(silent=True) or {}
    locked_sources = body.get('sources') if isinstance(body.get('sources'), list) else None
    payload, status = start_build_with_name_prefetch(
        g.user_id, cmd_name, sci_name, locked_sources=locked_sources
    )
    return jsonify(payload), status


@app.route('/api/robot/reset', methods=['POST'])
@login_required
@handle_api_error
def api_robot_reset():
    """DEV-ONLY: wipe the caller's robot + stage_log AND restore the consumed
    source discoveries to claimable state. Used during dry-run rehearsal so
    each test forge starts with a clean slate.

    Note: Sepolia tx already written cannot be undone — but in dry-run mode
    none are written (broadcast_stage_async no-ops for NAROG_DRY_RUN_USER_IDS).

    Gated to APP_DEV_USER_IDS (Andy only) — stricter than is_admin so Luke
    can't accidentally wipe his canonical Narog post-May-1.
    """
    from utilities.admin_utils import is_app_dev
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_app_dev(real_user_id):
        return jsonify({'success': False, 'error': 'forbidden'}), 403
    from utilities.postgres.core import db_cursor
    with db_cursor(commit=True) as cur:
        # Read stage_sources BEFORE delete so we can restore the consumed
        # items. The robot row gets DELETEd next, so this read must come
        # first inside the transaction.
        cur.execute(
            "SELECT stage_sources FROM pilgrim.robot WHERE user_id = %s",
            (g.user_id,),
        )
        row = cur.fetchone()
        sources = (row and row.get('stage_sources')) or []
        real_ids = [
            int(s['discovery_id']) for s in sources
            if s.get('discovery_id') is not None
        ]

        # Restore consumed items. analyzed=FALSE puts them back into the
        # narog source pool (and the rest of inventory).
        restored = 0
        if real_ids:
            cur.execute("""
                UPDATE pilgrim.expedition_discoveries
                SET analyzed = FALSE, analyzed_at = NULL
                WHERE id = ANY(%s::int[])
                  AND expedition_id IN (
                      SELECT id FROM pilgrim.expeditions WHERE user_id = %s
                  )
                RETURNING id
            """, (real_ids, g.user_id))
            restored = cur.rowcount

        cur.execute('DELETE FROM pilgrim.robot_stage_log WHERE user_id=%s', (g.user_id,))
        stage_rows = cur.rowcount
        cur.execute('DELETE FROM pilgrim.robot WHERE user_id=%s', (g.user_id,))
        robot_rows = cur.rowcount

    return jsonify({
        'success': True,
        'stage_log_deleted': stage_rows,
        'robot_deleted': robot_rows,
        'discoveries_restored': restored,
    })


@app.route('/api/robot/retry_forge', methods=['POST'])
@login_required
@handle_api_error
def api_robot_retry_forge():
    """Retry the stage-5 oneshot forge after a Flux failure. Available to ANY
    captain whose robot row has build_error set — the items are already consumed
    so the captain isn't getting a free re-roll, just a do-over of the image
    that should have come back the first time. Stages 1-4 + their tx hashes
    stay intact."""
    from utilities.postgres.core import db_cursor
    from utilities.postgres.robot import get_robot
    from utilities.robot_visuals import start_background_full_build
    robot = get_robot(g.user_id)
    if not robot:
        return jsonify({'success': False, 'error': 'No Narog build in progress.'}), 400
    if not robot.get('build_error'):
        return jsonify({'success': False, 'error': 'No forge error to retry.'}), 400
    sources = robot.get('stage_sources') or []
    if not sources or len(sources) < 5:
        return jsonify({'success': False, 'error': 'Source manifest missing — contact admin.'}), 500
    # Clear the error + delete the failed stage-5 row (if any) so the worker
    # re-runs the oneshot. Stages 1-4 stay; their on-chain tx still resolves.
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE pilgrim.robot SET build_error = NULL, build_status = 'in_progress', updated_at = NOW() WHERE user_id = %s",
            (g.user_id,),
        )
        cur.execute(
            "DELETE FROM pilgrim.robot_stage_log WHERE user_id = %s AND stage_idx = 5",
            (g.user_id,),
        )
    # Re-fire the worker. _full_build_worker will re-do stages 1-4 placeholder
    # logging (idempotent on user_id+stage_idx via ON CONFLICT) and the forge.
    start_background_full_build(g.user_id, sources)
    return jsonify({'success': True, 'retrying': True})


@app.route('/api/robot/name', methods=['POST'])
@login_required
@handle_api_error
def api_robot_name():
    """Set or rename the captain's robot. Names trimmed to 64 chars."""
    from utilities.postgres.robot import set_robot_name, get_robot_page_data
    name = (request.get_json() or {}).get('name', '')
    if not set_robot_name(g.user_id, name):
        return jsonify({'success': False, 'error': 'Name required'}), 400
    return jsonify({'success': True, 'data': get_robot_page_data(g.user_id)})


@app.route('/api/robot/dial', methods=['POST'])
@login_required
@handle_api_error
def api_robot_dial():
    """Set the robot's role dial. 4 values, mod-5 each, must sum to 100."""
    from utilities.postgres.robot import set_robot_dial, get_robot_page_data
    dial = (request.get_json() or {}).get('dial', {})
    try:
        set_robot_dial(g.user_id, dial)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    return jsonify({'success': True, 'data': get_robot_page_data(g.user_id)})


@app.route('/api/robot/history')
@login_required
@handle_api_error
def api_robot_history():
    """Past Looks feed — chronological list of prior image+video snapshots."""
    from utilities.postgres.robot import get_narog_history
    return jsonify({'success': True, 'history': get_narog_history(g.user_id)})


@app.route('/api/robot/recalibration_state')
@login_required
@handle_api_error
def api_robot_recalibration_state():
    """Current counters + caps + costs + 72hr window status for the captain.
    Powers the Recalibration card render."""
    from utilities.postgres.robot import get_recalibration_state
    return jsonify({'success': True, 'state': get_recalibration_state(g.user_id)})


@app.route('/api/robot/repick', methods=['POST'])
@login_required
@handle_api_error
def api_robot_repick():
    """Pay shards → restore 5 old components → pick 5 new (random within
    locked 2L+2R+1U/C recipe) → mark new ones consumed. Image/video unchanged."""
    from utilities.postgres.robot import (
        charge_reforge_action, repick_narog_components,
        get_recalibration_state, get_robot_page_data, ReforgeError,
    )
    try:
        charge = charge_reforge_action(g.user_id, 'repick')
        result = repick_narog_components(g.user_id)
    except ReforgeError as e:
        return jsonify({'success': False, 'error': e.message}), e.status
    return jsonify({
        'success': True,
        'charge': charge,
        'new_sources': result['new_sources'],
        'state': get_recalibration_state(g.user_id),
        'data': get_robot_page_data(g.user_id),
    })


@app.route('/api/robot/reroll_image', methods=['POST'])
@login_required
@handle_api_error
def api_robot_reroll_image():
    """Pay shards → re-run the 5-stage Flux pipeline against the current
    components. Same items, new silhouette. Spawns the existing forge worker;
    page polls /api/robot/status while it runs (~30-60s)."""
    from utilities.postgres.robot import (
        charge_reforge_action, get_robot, get_recalibration_state, ReforgeError,
    )
    from utilities.robot_visuals import start_background_full_build
    try:
        charge = charge_reforge_action(g.user_id, 'reroll_image')
    except ReforgeError as e:
        return jsonify({'success': False, 'error': e.message}), e.status

    robot = get_robot(g.user_id) or {}
    sources = list(robot.get('stage_sources') or [])
    if len(sources) != 5:
        return jsonify({'success': False, 'error': 'No source manifest found.'}), 409

    # Snapshot the current image+video pair before re-rendering — captain can
    # browse it later in Past Looks. This is the prior "look" they're leaving.
    from utilities.postgres.robot import snapshot_narog_history
    snapshot_narog_history(g.user_id, 'before_image_reroll')

    # Reset visual state so the existing pipeline re-renders all stages.
    # We DO NOT null video_url — keep it for history. Stale-detection in the
    # template compares image_updated_at vs video_updated_at: if the image is
    # newer, the template hides the (now-mismatched) video and shows the
    # "Bring to Life" CTA so the captain pays for a fresh Wan render.
    # image_updated_at is set when the Flux render COMPLETES (in robot_visuals),
    # but we set it tentatively here too so stale-detection kicks in immediately
    # — captain shouldn't see the old video while the new image is still rendering.
    from utilities.postgres.core import db_cursor
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE pilgrim.robot
            SET build_status = 'in_progress',
                visual_stage = 0,
                stage_images = '[]'::jsonb,
                stage_started_at = NOW(),
                stage_ready_at = NOW(),
                build_error = NULL,
                cinematic_played = TRUE,
                image_updated_at = NOW(),
                updated_at = NOW()
            WHERE user_id = %s
        """, (g.user_id,))
        cur.execute("DELETE FROM pilgrim.robot_stage_log WHERE user_id = %s", (g.user_id,))

    spawned = start_background_full_build(g.user_id, sources)
    return jsonify({
        'success': True,
        'spawned': spawned,
        'charge': charge,
        'state': get_recalibration_state(g.user_id),
    })


@app.route('/api/robot/reroll_video', methods=['POST'])
@login_required
@handle_api_error
def api_robot_reroll_video():
    """Pay shards + SV → re-run Wan on the current image. Same look, new
    awakening sequence. Spawns the existing video worker; page polls
    /api/robot/video_status."""
    from utilities.postgres.robot import (
        charge_reforge_action, start_robot_awakening_video,
        get_recalibration_state, ReforgeError,
    )
    from utilities.postgres.core import db_cursor
    try:
        charge = charge_reforge_action(g.user_id, 'reroll_video')
    except ReforgeError as e:
        return jsonify({'success': False, 'error': e.message}), e.status

    # Snapshot the current pair before re-rendering — even though only the
    # video changes, we capture the full pair so Past Looks shows what state
    # the awakening was paired with at this moment.
    from utilities.postgres.robot import snapshot_narog_history
    snapshot_narog_history(g.user_id, 'before_video_reroll')

    # Clear video_url so start_robot_awakening_video regenerates instead of
    # short-circuiting on the existing URL. video_updated_at gets re-set when
    # the new video lands (in the worker's UPDATE).
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE pilgrim.robot SET video_url = NULL, updated_at = NOW() WHERE user_id = %s", (g.user_id,))
    payload, status = start_robot_awakening_video(g.user_id, app.config, flux)
    payload['charge'] = charge
    payload['state'] = get_recalibration_state(g.user_id)
    return jsonify(payload), status


@app.route('/api/robot/lock_in', methods=['POST'])
@login_required
@handle_api_error
def api_robot_lock_in():
    """Close the 72hr test window and mark the Narog canonical.

    Side-effect: if the captain doesn't already have an awakening video, we
    auto-charge the reroll_video cost and kick off a Wan render — every locked
    Narog should ship with both an image AND an awakening cinematic. The modal
    discloses this cost up-front; here we just silently apply it. If the
    captain can't afford it, lock-in is blocked with a clear error.
    """
    from utilities.postgres.robot import (
        lock_in_narog, get_recalibration_state, get_robot,
        charge_reforge_action, start_robot_awakening_video, ReforgeError,
    )
    robot = get_robot(g.user_id) or {}
    video_charge = None
    if not robot.get('video_url'):
        try:
            video_charge = charge_reforge_action(g.user_id, 'reroll_video')
        except ReforgeError as e:
            return jsonify({'success': False, 'error': f"Awakening render: {e.message}"}), e.status
        # Spawn the Wan render in the background — captain can leave the page.
        start_robot_awakening_video(g.user_id, app.config, flux)

    try:
        result = lock_in_narog(g.user_id)
    except ReforgeError as e:
        return jsonify({'success': False, 'error': e.message}), e.status
    return jsonify({
        'success': True,
        **result,
        'video_charge': video_charge,
        'state': get_recalibration_state(g.user_id),
    })


@app.route('/api/robot/cinematic_played', methods=['POST'])
@login_required
@handle_api_error
def api_robot_cinematic_played():
    """Mark the build-complete cinematic as shown so it doesn't replay."""
    from utilities.postgres.robot import mark_cinematic_played
    mark_cinematic_played(g.user_id)
    return jsonify({'success': True})

@app.route('/api/robot/generate_video', methods=['POST'])
@login_required
@handle_api_error
def api_robot_generate_video():
    """Generate an awakening video for the golem using its current image."""
    from utilities.postgres.robot import start_robot_awakening_video
    payload, status = start_robot_awakening_video(g.user_id, app.config, flux)
    return jsonify(payload), status


@app.route('/api/robot/video_status')
@login_required
@handle_api_error
def api_robot_video_status():
    """Poll golem video generation progress."""
    status_key = f'golem_video_{g.user_id}'
    status = app.config.get(status_key, {})
    return jsonify({'success': True, **status})


@app.route('/api/robot/reset_video', methods=['POST'])
@login_required
@handle_api_error
def api_robot_reset_video():
    """DEV-ONLY: clear video_url so generation can re-fire. Keeps the forged
    narog + stage log intact — the expensive Flux forge doesn't repeat. Gated
    to APP_DEV_USER_IDS so even Luke (admin) can't spam Wan thread leaks
    (#1403 Item 3)."""
    from utilities.admin_utils import is_app_dev
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_app_dev(real_user_id):
        return jsonify({'success': False, 'error': 'forbidden'}), 403
    from utilities.postgres.core import db_cursor
    from utilities.postgres.robot import start_robot_awakening_video
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE pilgrim.robot SET video_url = NULL, updated_at = NOW() WHERE user_id = %s",
            (g.user_id,))
    app.config.pop(f'golem_video_{g.user_id}', None)
    payload, status = start_robot_awakening_video(g.user_id, app.config, flux)
    return jsonify(payload), status


@app.route('/api/robot/suggest_names', methods=['POST'])
@login_required
@handle_api_error
def api_robot_suggest_names():
    """Generate 5 AI-suggested golem names based on colony context."""
    from utilities.claude_utils import suggest_golem_names
    from utilities.postgres.robot import get_robot_page_data
    data = get_robot_page_data(g.user_id)
    robot = data.get('robot') or {}
    commander_name = session.get('_cmd') or None
    scientist_name = session.get('scientist_name')
    names = suggest_golem_names(
        user_id=g.user_id,
        commander_name=commander_name,
        scientist_name=scientist_name,
        stage_sources=robot.get('stage_sources'),
    )
    return jsonify({'success': True, 'names': names})


@app.route('/depot')
def depot():
    """Depot page - works for both anonymous and authenticated users"""
    if auth.is_authenticated():
        depot_data = get_depot_page_data(session.get('user_id'), auth)
        infra_data = get_infrastructure_page_data(session.get('user_id'))
        # Merge both datasets
        return render_template('depot.html', active_tab='depot', **depot_data, **infra_data)
    else:
        # Anonymous - show login prompt
        return render_template('depot.html', active_tab='depot', user=None, current_balance=0, pricing={'reroll_cost': 5, 'modify_cost': 15}, has_commander=False, shop_catalog={})

@app.route('/expeditions')
def expeditions():
    """Expeditions page - works for both anonymous and authenticated users"""
    if auth.is_authenticated():
        user_id = session.get('user_id')
        data = get_expeditions_page_data(user_id)
        # Add signal stats for the Signal tab
        data['signal_stats'] = get_signal_page_data()
        return render_template('expeditions.html', active_tab='expeditions', user=auth.get_current_user(), **data)
    else:
        # Anonymous - show login prompt
        return render_template('expeditions.html', active_tab='expeditions', user=None)

@app.route('/colony')
def colony():
    """Colony page - view all your assets: discoveries, equipment, infrastructure, vehicles"""
    if auth.is_authenticated():
        return render_template('colony.html', active_tab='colony', **get_colony_page_data(session.get('user_id'), auth))
    else:
        # Anonymous - show login prompt
        return render_template('colony.html', active_tab='colony', user=None)


@app.route('/inventory')
def inventory():
    """Redirect old inventory URL to colony"""
    return redirect(url_for('colony'))

@app.route('/lore')
def lore():
    """Lore/Guide page - explains the game world and mechanics"""
    user = auth.get_current_user() if auth.is_authenticated() else None
    return render_template('lore.html', active_tab='lore', user=user)

@app.route('/changelog')
def changelog():
    """Changelog page - what's new in Pilgrims"""
    user = auth.get_current_user() if auth.is_authenticated() else None
    return render_template('changelog.html', active_tab=None, user=user)

# ============================================================================
# TECH TREE & BRAINSTORM API
# ============================================================================

@app.route('/research')
@login_required
def research():
    """Research page - tech tree with 4 branches"""
    return render_template('research.html', active_tab='research', user=auth.get_current_user(), **get_research_page_data(g.user_id))


@app.route('/api/tech/status')
@login_required
@handle_api_error
def api_tech_status():
    """Get full tech tree state for user"""
    return jsonify(get_user_tech_status(g.user_id))


@app.route('/api/tech/research', methods=['POST'])
@login_required
@handle_api_error
def api_tech_research():
    """Start researching a technology"""
    data = request.get_json()
    return jsonify(start_research(g.user_id, data.get('branch'), data.get('tech_key'), session))


@app.route('/api/tech/progress')
@login_required
@handle_api_error
def api_tech_progress():
    """Check active research progress"""
    return jsonify({'success': True, 'research': get_research_progress(g.user_id)})


@app.route('/api/tech/cancel', methods=['POST'])
@login_required
@handle_api_error
def api_tech_cancel():
    """Cancel active research, refund SV"""
    return jsonify(cancel_research(g.user_id, session))


@app.route('/brainstorm/signal')
def signal_brainstorm():
    """Signal endgame design brainstorm — hardcoded sections with per-section comments."""
    user = auth.get_current_user() if auth.is_authenticated() else None
    return render_template('brainstorm/signal.html', active_tab=None, user=user)


@app.route('/brainstorm/signal-phase-2')
def signal_phase_2_brainstorm():
    """Signal Phase 2 spec — synthesized from Luke's feedback."""
    user = auth.get_current_user() if auth.is_authenticated() else None
    return render_template('brainstorm/signal_phase_2.html', active_tab=None, user=user)


@app.route('/brainstorm/robot-crew')
def robot_crew_brainstorm():
    """Robot Crew Member brainstorm — 4th crew member built from legendary discoveries."""
    user = auth.get_current_user() if auth.is_authenticated() else None
    return render_template('brainstorm/robot_crew.html', active_tab=None, user=user)


@app.route('/brainstorm/captain-stats')
def captain_stats_brainstorm():
    """Captain & Scientist Stats brainstorm — stat progression, effects, and growth."""
    user = auth.get_current_user() if auth.is_authenticated() else None
    return render_template('brainstorm/captain_stats.html', active_tab=None, user=user)


@app.route('/brainstorm/depot-recalibration')
def depot_recalibration_brainstorm():
    """Depot Recalibration brainstorm — building purposes, costs, build speed."""
    user = auth.get_current_user() if auth.is_authenticated() else None
    return render_template('brainstorm/depot_recalibration.html', active_tab=None, user=user)


@app.route('/api/brainstorm/signal-chat', methods=['POST'])
@handle_api_error
def api_signal_brainstorm_chat():
    """Chat endpoint for signal system brainstorming with Claude."""
    data = request.get_json() or {}
    if not data.get('message'):
        return jsonify({'success': False, 'error': 'No message provided'})
    return jsonify({'success': True, 'response': brainstorm_chat(data['message'], data.get('context', ''), data.get('history', []), user_id=session.get('user_id'))})


@app.route('/brainstorm/tech-tree')
def tech_tree_brainstorm():
    """Tech Tree brainstorm page for team discussion"""
    user = auth.get_current_user() if auth.is_authenticated() else None
    from config import BUG_TRACKER_URL
    return render_template('brainstorm/tech_tree.html', active_tab=None, user=user, bug_tracker_url=BUG_TRACKER_URL)


@app.route('/brainstorm/progression')
def progression_visualization():
    """Civ-style progression tree visualization for Lab + Depot + Infrastructure"""
    user = auth.get_current_user() if auth.is_authenticated() else None
    return render_template('brainstorm/tech_tree_visualization.html', active_tab=None, user=user)


@app.route('/api/brainstorm/tech-tree-chat', methods=['POST'])
@handle_api_error
def api_tech_tree_brainstorm_chat():
    """Chat endpoint for tech tree brainstorming with Claude."""
    data = request.get_json() or {}
    if not data.get('message'):
        return jsonify({'success': False, 'error': 'No message provided'})
    return jsonify({'success': True, 'response': brainstorm_chat(data['message'], data.get('context', ''), data.get('history', []), user_id=session.get('user_id'))})


@app.route('/brainstorm/trail-network')
def trail_network_brainstorm():
    """Trail Network brainstorm page for team discussion"""
    user = auth.get_current_user() if auth.is_authenticated() else None
    return render_template('brainstorm/trail_network.html', active_tab=None, user=user)


@app.route('/api/brainstorm/trail-network-chat', methods=['POST'])
@handle_api_error
def api_trail_network_brainstorm_chat():
    """Chat endpoint for trail network brainstorming with Claude."""
    data = request.get_json() or {}
    if not data.get('message'):
        return jsonify({'success': False, 'error': 'No message provided'})
    return jsonify({'success': True, 'response': brainstorm_chat(data['message'], data.get('context', ''), data.get('history', []), user_id=session.get('user_id'))})


@app.route('/brainstorm/icon-redesign')
def icon_redesign_brainstorm():
    """Icon Redesign & 10-Level Upgrades brainstorm page for team discussion"""
    user = auth.get_current_user() if auth.is_authenticated() else None
    return render_template('brainstorm/icon_redesign.html', active_tab=None, user=user)


@app.route('/api/brainstorm/icon-redesign-chat', methods=['POST'])
@handle_api_error
def api_icon_redesign_brainstorm_chat():
    """Chat endpoint for icon redesign brainstorming with Claude."""
    data = request.get_json() or {}
    if not data.get('message'):
        return jsonify({'success': False, 'error': 'No message provided'})
    return jsonify({'success': True, 'response': brainstorm_chat(data['message'], data.get('context', ''), data.get('history', []), user_id=session.get('user_id'))})


@app.route('/brainstorm/aria-meetings')
def aria_meetings_brainstorm():
    """ARIA Meetings & Outcomes brainstorm page — bond system, multiplicity, cross-colony."""
    user = auth.get_current_user() if auth.is_authenticated() else None
    from config import BUG_TRACKER_URL
    return render_template('brainstorm/aria_meetings.html', active_tab=None, user=user, bug_tracker_url=BUG_TRACKER_URL)


@app.route('/api/brainstorm/aria-meetings-chat', methods=['POST'])
@handle_api_error
def api_aria_meetings_brainstorm_chat():
    """Chat endpoint for ARIA meetings brainstorming with Claude."""
    data = request.get_json() or {}
    if not data.get('message'):
        return jsonify({'success': False, 'error': 'No message provided'})
    return jsonify({'success': True, 'response': brainstorm_chat(data['message'], data.get('context', ''), data.get('history', []), user_id=session.get('user_id'))})


@app.route('/brainstorm/sv-economy')
def sv_economy_brainstorm():
    """SV Economy rebalance brainstorm page for team discussion"""
    user = auth.get_current_user() if auth.is_authenticated() else None
    return render_template('brainstorm/sv_economy.html', active_tab=None, user=user)

@app.route('/api/brainstorm/sv-economy-chat', methods=['POST'])
@handle_api_error
def api_sv_economy_brainstorm_chat():
    """Chat endpoint for SV economy brainstorming with Claude."""
    data = request.get_json()
    if not data or not data.get('message'):
        return jsonify({'success': False, 'error': 'No message provided'})
    return jsonify({'success': True, 'response': brainstorm_chat(data['message'], data.get('context', ''), data.get('history', []), user_id=session.get('user_id'))})


@app.route('/api/brainstorm/comments/<page_key>', methods=['GET'])
@handle_api_error
def api_brainstorm_comments_get(page_key):
    """Get all comments for a brainstorm page."""
    from utilities.postgres.brainstorm import get_comments_for_page
    comments = get_comments_for_page(page_key)
    for c in comments:
        c['created_at'] = c['created_at'].isoformat() if c['created_at'] else None
    return jsonify({'success': True, 'comments': comments})


@app.route('/api/brainstorm/comments/<page_key>', methods=['POST'])
@handle_api_error
def api_brainstorm_comments_post(page_key):
    """Add a comment to a brainstorm page section."""
    from utilities.postgres.brainstorm import add_comment_from_request
    auth_name = auth.get_current_user().get('name', 'Unknown') if auth.is_authenticated() else None
    payload, new_cookie = add_comment_from_request(
        page_key, request.get_json() or {}, auth_name, request.cookies.get('bs_anon'))
    resp = jsonify(payload)
    if new_cookie:
        resp.set_cookie('bs_anon', new_cookie, max_age=60*60*24*365, httponly=True, samesite='Lax')
    return resp


@app.route('/aria-album')
def aria_album():
    """ARIA's Photo Journal - all snapshots from the colony."""
    if not auth.is_authenticated():
        return redirect(url_for('home'))
    snapshots = get_aria_album_data(session.get('user_id'))
    return render_template('aria_album.html', active_tab='home', user=auth.get_current_user(), snapshots=snapshots)

@app.route('/signal')
def signal():
    """The Shard Network - ARG/mystery page showing Origin Sites and Echo Sites"""
    user_id = session.get('user_id') if auth.is_authenticated() else None
    return render_template('signal.html',
                           active_tab='signal',
                           user=auth.get_current_user() if auth.is_authenticated() else None,
                           **get_signal_page_render_data(user_id))

# ============================================================================
# ONBOARDING & LEGACY REDIRECTS
# ============================================================================

@app.route('/arrival/mining')
def arrival_mining():
    """Legacy: Redirect to home"""
    return redirect(url_for('home'))

@app.route('/arrival/commander')
def arrival_commander():
    """Legacy: Redirect to crew"""
    return redirect(url_for('crew'))

@app.route('/deploy', methods=['GET', 'POST'])
def deploy():
    """Deploy page - final step before colony"""
    user_id = session.get('user_id') if auth.is_authenticated() else None
    if request.method == 'POST':
        return jsonify(start_deploy_video_generation(session, app.config, flux, animate_character_video, logger))
    data = get_arrival_deploy_data(session, user_id)
    if 'redirect' in data:
        return redirect(url_for(data['redirect']))
    return render_template('arrival/deploy.html', step=3, user=auth.get_current_user() if auth.is_authenticated() else None, **data)

@app.route('/arrival/deploy', methods=['GET', 'POST'])
def arrival_deploy():
    """Legacy: Redirect to deploy"""
    return redirect(url_for('deploy'))

@app.route('/api/arrival/mars_location', methods=['GET'])
@handle_api_error
def api_arrival_mars_location():
    """Get random Mars drop coordinates and nearest landmarks"""
    return jsonify(get_mars_location_data())

# Legacy colony routes - redirect to new routes
@app.route('/colony/dashboard')
@login_required
def colony_dashboard():
    """Legacy: Redirect to home"""
    return redirect(url_for('home'))

@app.route('/colony/profile')
@login_required
def colony_profile():
    """Legacy: Redirect to inventory"""
    return redirect(url_for('inventory'))

# ============================================================================
# CAPTAIN MANAGEMENT API
# ============================================================================

@app.route('/api/upload_custom_commander', methods=['POST'])
@login_required
@handle_api_error
def api_upload_custom_commander():
    """Upload custom commander photo (authenticated users only - FREE)"""
    return jsonify(handle_custom_commander_upload(session, request.files['image'], flux, logger))

@app.route('/api/commander/set_primary/<int:asset_id>', methods=['POST'])
@login_required
@handle_api_error
def api_set_primary_commander(asset_id):
    """Set a captain as the active/primary captain"""
    success = set_primary_commander(g.user_id, asset_id)

    if success:
        logger.info(f"✅ User {g.user_id} set captain {asset_id} as primary")
        return jsonify({'success': True, 'message': 'Captain activated successfully'})
    else:
        return jsonify({'success': False, 'error': 'Failed to activate captain'})

@app.route('/api/commander/rename', methods=['POST'])
@login_required
@handle_api_error
def api_rename_commander():
    """Rename the captain with profanity filtering"""
    data = request.get_json() or {}
    if 'name' not in data:
        return jsonify({'success': False, 'error': 'Name is required'})
    return jsonify(rename_captain_with_validation(g.user_id, data['name'], session))

@app.route('/colony/command')
@login_required
def colony_command():
    """Legacy: Redirect to crew"""
    return redirect(url_for('crew'))

@app.route('/colony/depot')
@login_required
def colony_depot():
    """Legacy: Redirect to depot"""
    return redirect(url_for('depot'))

@app.route('/colony/infrastructure')
@login_required
def colony_infrastructure():
    """Legacy: Redirect to depot (infrastructure merged into depot)"""
    return redirect(url_for('depot'))

# ============================================================================
# USER DATA API (balance, nav, equipment, activity, discoveries)
# ============================================================================

@app.route('/api/expeditions/recent_discoveries', methods=['GET'])
@login_required
def api_recent_discoveries():
    """Get recent unlocked but unclaimed discoveries"""
    from utilities.postgres.expeditions import get_recent_discoveries_payload
    return jsonify(get_recent_discoveries_payload(g.user_id))

@app.route('/api/user/balance', methods=['GET'])
@login_required
@handle_api_error
def api_user_balance():
    """Get user's current shard balance (fresh from DB cache)"""
    total_balance, _, _ = get_live_balance_and_wallet_info(g.user_id)
    session['_bal'] = total_balance
    return jsonify({'success': True, 'balance': total_balance})

@app.route('/api/nav/stats', methods=['GET'])
@login_required
@handle_api_error
def api_nav_stats():
    """Get all nav bar stats in one call - balance, expedition count, item count"""
    total_balance, _, _ = get_live_balance_and_wallet_info(g.user_id)

    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as cnt FROM pilgrim.expeditions WHERE user_id = %s AND status = 'completed'", (g.user_id,))
        expeditions = cur.fetchone()['cnt']
        cur.execute("SELECT COUNT(*) as cnt FROM pilgrim.claimed_discoveries WHERE user_id = %s", (g.user_id,))
        items = cur.fetchone()['cnt']

    return jsonify({
        'success': True,
        'balance': total_balance,
        'expeditions': expeditions,
        'items': items
    })

@app.route('/api/user/claimed_discoveries', methods=['GET'])
@login_required
def api_claimed_discoveries():
    """Get ALL claimed discoveries for user's inventory"""
    return jsonify(get_claimed_discoveries_data(g.user_id))

@app.route('/api/user/equipment', methods=['GET'])
@login_required
def api_user_equipment():
    """Get user's owned equipment and available upgrades"""
    return jsonify(get_user_equipment_data(g.user_id))

@app.route('/api/colony/activity', methods=['GET'])
@login_required
def api_colony_activity():
    """Get unified activity log for colony page"""
    return jsonify({'success': True, 'activity': get_unified_activity(g.user_id)})


@app.route('/colony/expeditions')
@login_required
def colony_expeditions():
    """Legacy: Redirect to expeditions"""
    return redirect(url_for('expeditions'))

# ============================================================================
# AUTH & EMAIL ACTIONS
# ============================================================================

@app.route('/login')
def login():
    """Initiate Google OAuth flow"""
    logger.info(f"🔐 LOGIN REQUEST - User-Agent: {request.headers.get('User-Agent', 'unknown')[:100]}")
    logger.info(f"🔐 LOGIN REQUEST - IP: {request.remote_addr}, Referrer: {request.referrer}")
    logger.info(f"🔐 LOGIN REQUEST - Headers: Host={request.headers.get('Host')}, X-Forwarded-Proto={request.headers.get('X-Forwarded-Proto')}")
    result = auth.login()
    logger.info(f"🔐 LOGIN REDIRECT - Redirecting to OAuth provider")
    return result

@app.route('/auth/callback')
def auth_callback():
    """Handle OAuth callback"""
    logger.info(f"🔐 AUTH CALLBACK - User-Agent: {request.headers.get('User-Agent', 'unknown')[:100]}")
    logger.info(f"🔐 AUTH CALLBACK - Args: {dict(request.args)}")
    redirect_to = handle_auth_callback(session, auth, logger)
    logger.info(f"🔐 AUTH CALLBACK - Redirecting to: {redirect_to}")
    return redirect(url_for(redirect_to))

@app.route('/logout')
def logout():
    """Logout and clear session"""
    auth.logout()
    return redirect(url_for('home'))

@app.route('/action/<token>')
def email_action(token):
    """One-click actions from email links. Token is signed — no login required."""
    from utilities.email_actions_utils import handle_email_action_token
    ctx, status = handle_email_action_token(token, app.secret_key)
    return render_template('action_result.html', **ctx), status

# ============================================================================
# CAPTAIN'S LOG & ARIA API
# ============================================================================

@app.route('/captains-log/<int:user_id>')
def captains_log(user_id):
    """Public page showing a commander's quote history (shareable)."""
    from utilities.captains_log_utils import get_captains_log_page_data
    return render_template('captains_log.html', **get_captains_log_page_data(user_id))


@app.route('/api/captains-log/chat', methods=['POST'])
def api_captains_log_chat():
    """Chat with a captain using Haiku (public — no login required)."""
    from utilities.captains_log_utils import handle_captains_log_chat
    return jsonify(handle_captains_log_chat(request.get_json() or {}))


@app.route('/api/aria/snapshot-narrative', methods=['POST'])
def api_aria_snapshot_narrative():
    """Generate an ARIA narrative for a photo journal snapshot."""
    data = request.get_json() or {}
    caption = data.get('caption', '')
    if not caption:
        return jsonify({'success': False, 'error': 'No caption provided'})
    try:
        from utilities.aria.photos import get_snapshot_narrative_for_user
        narrative = get_snapshot_narrative_for_user(
            session.get('user_id'), caption, data.get('type', ''))
        return jsonify({'success': True, 'narrative': narrative})
    except Exception as e:
        logger.error(f"Error generating snapshot narrative: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/aria/snapshot/delete', methods=['POST'])
@handle_api_error
def api_aria_snapshot_delete():
    """Delete (soft) a snapshot from user's photo gallery"""
    from utilities.aria.photos import delete_snapshot_with_auth
    user_id = session.get('user_id') if auth.is_authenticated() else None
    data = request.get_json() or {}
    return jsonify(delete_snapshot_with_auth(user_id, data.get('snapshot_id')))


@app.route('/api/aria/history', methods=['GET'])
def api_aria_history():
    """Get ARIA conversation history for the authenticated user."""
    from utilities.aria.conversation import get_history_payload
    return jsonify(get_history_payload(session.get('user_id'), auth.is_authenticated()))


@app.route('/api/aria/chat', methods=['POST'])
def api_aria_chat():
    """Chat with ARIA - supports streaming (SSE) when stream=true."""
    outcome = handle_aria_chat_request(
        request.get_json() or {},
        session.get('user_id'),
        auth.is_authenticated(),
        request.referrer,
    )
    if 'error' in outcome:
        return jsonify({'success': False, 'error': outcome['error']})
    if outcome['mode'] == 'stream':
        return Response(
            stream_with_context(outcome['generator']),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache, no-store, must-revalidate',
                     'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'}
        )
    return jsonify(outcome['result'])


@app.route('/api/aria/hint', methods=['GET'])
@login_required
def api_aria_hint():
    """Get a contextual hint from ARIA based on user's current game state."""
    result = get_contextual_hint(g.user_id)
    return jsonify({'success': True, 'hint': result['hint'], 'priority': result['priority']})

# ============================================================================
# EXPEDITION API
# ============================================================================

@app.route('/api/expeditions/calculate_cost', methods=['POST'])
@login_required
def api_expeditions_calculate_cost():
    """Calculate expedition cost for UI preview"""
    data = request.get_json()
    return jsonify(get_expedition_cost_preview_formatted(g.user_id, data.get('distance_km'), data.get('destination_type', 'Unknown')))

@app.route('/api/expeditions/calculate_costs_bulk', methods=['POST'])
@login_required
def api_expeditions_calculate_costs_bulk():
    """Bulk cost preview — one round trip for the whole expedition card list."""
    data = request.get_json() or {}
    return jsonify(get_expedition_cost_preview_bulk_formatted(g.user_id, data.get('items') or []))

@app.route('/api/expeditions/start', methods=['POST'])
@login_required
def api_expeditions_start():
    """Start expedition"""
    return jsonify(start_expedition_from_request(g.user_id, request.get_json(), session))


@app.route('/api/expeditions/launch_signal_claim', methods=['POST'])
@login_required
@handle_api_error
def api_launch_signal_claim():
    """Phase 2.3b: launch a dedicated signal_claim expedition to an Origin Site.

    Body: {site_id: int, vehicle_type: str}
    Server resolves coords/name from pilgrim.origin_sites — client coords are ignored.
    """
    data = request.get_json() or {}
    payload = {
        'destination_name': '',  # filled by launch_expedition from site row
        'destination_type': 'OriginSite',
        'latitude': 0,
        'longitude': 0,
        'distance_km': 1,  # placeholder; recomputed in launch_expedition
        'vehicle_type': data.get('vehicle_type', 'rover'),
        'expedition_type': 'signal_claim',
        'signal_site_id': data.get('site_id'),
    }
    return jsonify(start_expedition_from_request(g.user_id, payload, session))


@app.route('/api/expeditions/preview_signal_claim', methods=['POST'])
@login_required
@handle_api_error
def api_preview_signal_claim():
    """Phase 2.3b: cost + travel-time preview for a signal_claim expedition.

    Reuses the standard cost engine — signal_claim trips are full-priced
    standard expeditions per Luke's brainstorm decision. Resolves site coords
    server-side so the captain can see exactly what they're committing to
    before they click Launch.
    """
    data = request.get_json() or {}
    site_id = data.get('site_id')
    vehicle_type = data.get('vehicle_type', 'rover')
    if not site_id:
        return jsonify({'success': False, 'error': 'Missing site_id'})

    from utilities.signal.claims import get_user_origin_site_eligibility
    from utilities.postgres.map import get_or_set_user_mars_home
    from utilities.mars_math import haversine_distance
    from utilities.expeditions.preview import get_expedition_cost_preview_formatted

    eligibility = get_user_origin_site_eligibility(g.user_id)
    site = next((s for s in eligibility if s['id'] == site_id), None)
    if not site:
        return jsonify({'success': False, 'error': 'Origin Site not found'})
    if site.get('has_visited'):
        return jsonify({'success': False, 'error': "You've already visited this site."})
    if not (site.get('can_claim') or site.get('can_visit')):
        return jsonify({'success': False, 'error': "You haven't detected this signal yet."})

    home = get_or_set_user_mars_home(g.user_id)
    distance_km = haversine_distance(
        float(home['latitude']), float(home['longitude']),
        float(site['latitude']), float(site['longitude'])
    )
    preview = get_expedition_cost_preview_formatted(g.user_id, distance_km, 'OriginSite')
    if not preview.get('success'):
        return jsonify(preview)
    preview['site'] = {
        'id': site['id'],
        'site_code': site['site_code'],
        'mission_name': site.get('mission_name'),
        'distance_km': round(distance_km, 1),
        'outcome_label': 'Founder' if site.get('can_claim') else 'Visitor',
    }
    return jsonify(preview)

@app.route('/api/expedition/preview', methods=['POST'])
@login_required
@handle_api_error
def api_expedition_preview():
    """Pre-launch modal data: vehicles, speed breakdown, captain stats, fleet status"""
    data = request.get_json()
    return jsonify(get_expedition_preview(
        g.user_id, data.get('distance_km'), data.get('destination_type', 'Unknown'), data.get('destination_name', '')
    ))

@app.route('/api/expedition/recall', methods=['POST'])
@login_required
@handle_api_error
def api_expedition_recall():
    """Recall a vehicle mid-expedition"""
    data = request.get_json()
    return jsonify(recall_expedition(g.user_id, data.get('expedition_id')))

@app.route('/api/expeditions/claim_all_discoveries', methods=['POST'])
@login_required
def api_claim_all_discoveries():
    """Claim all unlocked discoveries for this user"""
    return jsonify(claim_all_discoveries(g.user_id))

@app.route('/api/expeditions/<int:expedition_id>/claim_all', methods=['POST'])
@login_required
def api_claim_all_expedition_discoveries(expedition_id):
    """Claim all discoveries for a specific expedition"""
    return jsonify(claim_all_discoveries(g.user_id, expedition_id))

@app.route('/api/expeditions/<int:expedition_id>/haul')
@login_required
def api_expedition_haul(expedition_id):
    """Get full expedition haul data for the celebration modal"""
    from utilities.expeditions.haul_data import build_expedition_haul
    return jsonify(build_expedition_haul(g.user_id, expedition_id))

@app.route('/api/discovery_items/<signed_int:discovery_item_id>/details')
@login_required
def api_discovery_item_details(discovery_item_id):
    """Get detailed history for a specific discovery item (supports negative IDs for origin site legendaries)"""
    details = get_discovery_item_details(g.user_id, discovery_item_id)

    if not details:
        return jsonify({'success': False, 'error': 'Item not found'})

    scientist = get_user_scientist(g.user_id)
    scientist_name = scientist.get('name', 'Colony Scientist') if scientist else 'Colony Scientist'

    return jsonify({'success': True, 'scientist_name': scientist_name, **details})

@app.route('/api/discovery/analyze', methods=['POST'])
@login_required
@handle_api_error
def api_analyze_discovery():
    """Analyze a discovery to extract Sepolia shards"""
    from utilities.discovery_utils import handle_analyze_request
    return jsonify(handle_analyze_request(g.user_id, request.get_json() or {}, session))

@app.route('/api/discovery/shard_all', methods=['POST'])
@login_required
@handle_api_error
def api_shard_all_discoveries():
    """Bulk extract all common and uncommon discoveries (Extract It All)"""
    result = shard_all_discoveries(g.user_id, session)
    return jsonify(result)

@app.route('/api/expeditions/status/<int:expedition_id>')
@login_required
def api_expeditions_status(expedition_id):
    """Check expedition status and complete if arrived"""
    result = complete_expedition_if_ready(expedition_id, g.user_id)

    # Invalidate cached balance so ribbon shows updated shards after reward
    if result.get('complete'):
        from utilities.session_helpers import invalidate_balance_cache
        invalidate_balance_cache(session)

    return jsonify(result)


@app.route('/api/expeditions/discoveries/<int:expedition_id>')
@login_required
def api_expedition_discoveries(expedition_id):
    """Get expedition discoveries with current progress"""
    return jsonify(get_discovery_progress_formatted(expedition_id, g.user_id))

@app.route('/api/expeditions/claim_discovery/<int:discovery_id>', methods=['POST'])
@login_required
def api_claim_discovery(discovery_id):
    """Claim a discovered item"""
    success = claim_expedition_discovery(discovery_id, g.user_id)

    if success:
        return jsonify({'success': True, 'message': 'Discovery claimed'})
    else:
        return jsonify({'success': False, 'error': 'Unable to claim discovery'})


@app.route('/api/expeditions/history', methods=['GET'])
@login_required
def api_expedition_history():
    """Get expedition history for user (completed expeditions with discovery data)"""
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    return jsonify(get_expedition_history_payload(g.user_id, limit=limit, offset=offset))


@app.route('/api/expeditions/<int:expedition_id>/items', methods=['GET'])
@login_required
def api_expedition_items(expedition_id):
    """Get all discovery items for a specific expedition (for history modal)"""
    payload, status = get_expedition_items_payload(g.user_id, expedition_id)
    return jsonify(payload), status


# ============================================================================
# CREW MISSIONS: Quick trail-building activities
# ============================================================================

@app.route('/api/crew/mission/status', methods=['GET'])
@login_required
def api_crew_mission_status():
    """Get current mission status and stats for captain, scientist, and ARIA"""
    from utilities.postgres.trails import get_crew_mission_status_with_stats
    return jsonify({'success': True, **get_crew_mission_status_with_stats(g.user_id)})


@app.route('/api/crew/mission/nearby', methods=['GET'])
@login_required
def api_crew_mission_nearby():
    """Get ALL visited sites for trail building - no distance limit"""
    from utilities.postgres.trails import get_crew_nearby_payload
    return jsonify(get_crew_nearby_payload(g.user_id))



@app.route('/api/crew/mission/complete', methods=['POST'])
@login_required
def api_crew_mission_complete():
    """Complete a crew mission and claim rewards"""
    data = request.json or {}
    crew_member = data.get('crew_member', '').lower()

    if crew_member not in ['captain', 'scientist']:
        return jsonify({'success': False, 'error': 'Invalid crew member'})

    result = complete_crew_mission(g.user_id, crew_member)
    return jsonify(result)


@app.route('/api/aria/resonance', methods=['POST'])
@login_required
def api_aria_resonance():
    """Use ARIA's daily resonance to boost a trail"""
    from utilities.postgres.trails.aria_skills import handle_resonance_request
    return jsonify(handle_resonance_request(g.user_id, request.json or {}))


# ============================================================================
# TRAIL BUILDING API (km-based system)
# ============================================================================

@app.route('/api/trail/progress/<destination_name>', methods=['GET'])
@login_required
def api_trail_progress(destination_name):
    """Get detailed trail progress for a destination"""
    return jsonify({'success': True, 'trail': get_trail_progress(g.user_id, destination_name)})


@app.route('/api/trail/build', methods=['POST'])
@login_required
def api_trail_build():
    """Start a real-time trail building session."""
    return jsonify(handle_trail_build_request(g.user_id, request.json or {}))


@app.route('/api/trail/complete', methods=['POST'])
@login_required
def api_trail_complete():
    """Complete a trail building session and claim rewards (km built + XP)."""
    from utilities.postgres.trails.crew import handle_trail_complete_request
    return jsonify(handle_trail_complete_request(g.user_id, request.json or {}))


@app.route('/api/trail/consumables', methods=['GET'])
@login_required
def api_trail_consumables():
    """Get available consumables and scanner bonus for trail building."""
    return jsonify(get_trail_consumables_data(g.user_id))


@app.route('/api/aria/skills', methods=['GET'])
@login_required
def api_aria_skills():
    """Get ARIA skill levels for current user"""
    return jsonify({'success': True, 'skills': get_aria_skills(g.user_id)})


@app.route('/api/user/all_activity', methods=['GET'])
@login_required
def api_user_all_activity():
    """Get ALL activity for user (for profile page)"""
    return jsonify({'success': True, 'activities': build_recent_activity(g.user_id, 1000)})

# ============================================================================
# INFRASTRUCTURE API
# ============================================================================

@app.route('/api/infrastructure/build', methods=['POST'])
@login_required
def api_infrastructure_build():
    """Start infrastructure construction"""
    return jsonify(handle_infrastructure_build(g.user_id, request.get_json().get('structure_type'), session))

@app.route('/api/infrastructure/accumulated', methods=['GET'])
@login_required
def api_infrastructure_accumulated():
    """Get accumulated income from generators"""
    return jsonify(handle_accumulated_income(g.user_id))

@app.route('/api/infrastructure/claim', methods=['POST'])
@login_required
def api_infrastructure_claim():
    """Claim accumulated income and clear dust storm"""
    result = claim_accumulated_income(g.user_id, session)

    # Clear dust storm alert flags so ARIA doesn't keep warning
    if result.get('success'):
        session.pop('_dsc', None)
        session.pop('_dsa', None)
        session.pop('_ads', None)
        session.modified = True

    return jsonify(result)

@app.route('/api/scientist/record-sv', methods=['POST'])
@login_required
@handle_api_error
def api_record_sv():
    """Record accumulated Science Value from Research Station"""
    return jsonify(record_science_value(g.user_id))

@app.route('/api/scientist/reassign', methods=['POST'])
@login_required
@handle_api_error
def api_reassign_scientist():
    """Reassign colony scientist."""
    from utilities.postgres.users import reassign_scientist_flow
    data = request.get_json() or {}
    return jsonify(reassign_scientist_flow(g.user_id, data.get('scientist_key', ''), session))


@app.route('/api/asset/delete/<int:asset_id>', methods=['POST'])
@login_required
@handle_api_error
def api_delete_asset(asset_id):
    """Soft-delete an asset (hide from view)"""
    if delete_asset(asset_id, g.user_id):
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Asset not found or unauthorized'})

# ============================================================================
# SHARD NETWORK API - Origin Sites & Echo Sites (ARG System)
# ============================================================================

@app.route('/api/signal/origin/claim/<int:site_id>', methods=['POST'])
@login_required
@handle_api_error
def api_claim_origin_site(site_id):
    """Claim an Origin Site as the First Founder (legendary, permanent)."""
    return jsonify(handle_origin_site_claim(g.user_id, site_id, session))


@app.route('/api/signal/origin/visit/<int:site_id>', methods=['POST'])
@login_required
@handle_api_error
def api_visit_origin_site(site_id):
    """Visit an already-claimed Origin Site as a pilgrim."""
    return jsonify(handle_origin_site_visit(g.user_id, site_id, session))


@app.route('/api/signal/echo/claim/<int:site_id>', methods=['POST'])
@login_required
@handle_api_error
def api_claim_echo_site(site_id):
    """Claim an Echo Site (tiered based on claim order)"""
    user = get_user_by_id(g.user_id)

    if not user or not user.get('commander_name'):
        return jsonify({'success': False, 'error': 'Captain required to claim sites'})

    result = claim_echo_site(
        site_id=site_id,
        user_id=g.user_id,
        commander_name=user['commander_name']
    )

    return jsonify(result)


@app.route('/api/signal/status', methods=['GET'])
@handle_api_error
def api_signal_status():
    """Get Shard Network status (public)"""
    data = get_signal_page_data()
    return jsonify({
        'success': True,
        'stats': data['stats'],
        'origin_sites': data['origin_sites'],
        'echo_sites': data['echo_sites'],
        'recent_claims': data['recent_echo_claims']
    })


@app.route('/api/signal/origin/eligibility', methods=['GET'])
@login_required
@handle_api_error
def api_origin_site_eligibility():
    """Get user's Origin Site eligibility — which sites can they claim."""
    from utilities.signal.rewards import get_user_origin_eligibility_payload
    return jsonify(get_user_origin_eligibility_payload(g.user_id))


@app.route('/api/signal/lost/decode', methods=['POST'])
@login_required
@handle_api_error
def api_decode_lost_site():
    """Attempt to decode a Lost Signal site with the correct 0x code."""
    data = request.get_json() or {}
    return jsonify(decode_lost_signal_site(g.user_id, data.get('site_id'), data.get('code', '')))


@app.route('/api/signal/origin/<int:site_id>/legendary', methods=['GET'])
@handle_api_error
def api_get_legendary_item(site_id):
    """Get legendary item status for an Origin Site (poll endpoint)."""
    from utilities.signal.rewards import get_legendary_item_payload
    return jsonify(get_legendary_item_payload(site_id))


@app.route('/api/signal/puzzle_fragments', methods=['GET'])
@login_required
@handle_api_error
def api_user_puzzle_fragments():
    """Phase 2.3c: list collected + locked puzzle fragments for the captain."""
    from utilities.signal.puzzle_fragments import get_user_fragments
    return jsonify({'success': True, **get_user_fragments(g.user_id)})


@app.route('/api/signal/puzzle_fragments/<int:fragment_id>/whisper_seen', methods=['POST'])
@login_required
@handle_api_error
def api_puzzle_whisper_seen(fragment_id):
    """Phase 2.3c: mark an ARIA whisper as seen so it stops popping on /signal."""
    from utilities.signal.puzzle_fragments import mark_whisper_seen
    return jsonify({'success': mark_whisper_seen(g.user_id, fragment_id)})


@app.route('/api/trails/active_direction', methods=['POST'])
@login_required
@handle_api_error
def api_trails_active_direction():
    """v3 (#1414): captain picks which of their 4 cardinal chains to actively build."""
    from utilities.postgres.trails.chains import set_user_active_direction
    data = request.get_json() or {}
    direction = (data.get('direction') or '').upper()
    if direction not in ('N', 'S', 'E', 'W'):
        return jsonify({'success': False, 'error': 'direction must be N/S/E/W'})
    return jsonify({'success': set_user_active_direction(g.user_id, direction), 'direction': direction})


@app.route('/api/trails/chains', methods=['GET'])
@login_required
@handle_api_error
def api_trails_chains():
    """v3 (#1414): full chain state for the captain — used by Crew page + Chain Math modal.

    `all_segments` includes lat/lon per to_landmark so the frontend can draw the
    ghost antipode route behind the built portion.
    """
    from utilities.postgres.trails.chains import (
        get_active_chain_segments, get_user_active_direction, get_all_user_chains,
    )
    from utilities.postgres.map import get_mars_mappings_by_name

    segs = get_all_user_chains(g.user_id)
    landmarks_by_name = get_mars_mappings_by_name()
    enriched = []
    for s in segs:
        lm = landmarks_by_name.get(s['to_landmark'])
        from_lm = landmarks_by_name.get(s['from_landmark']) if s['from_landmark'] != 'HOME' else None
        d = dict(s)
        d['to_latitude'] = float(lm['latitude']) if lm else None
        d['to_longitude'] = float(lm['longitude']) if lm else None
        d['from_latitude'] = float(from_lm['latitude']) if from_lm else None
        d['from_longitude'] = float(from_lm['longitude']) if from_lm else None
        enriched.append(d)

    return jsonify({
        'success': True,
        'active_direction': get_user_active_direction(g.user_id),
        'chains': get_active_chain_segments(g.user_id),
        'all_segments': enriched,
    })


@app.route('/api/depot/completions/mark-seen', methods=['POST'])
@login_required
@handle_api_error
def api_depot_completions_mark_seen():
    """Bug #1397 ReOpen v3: mark all current depot build completions as seen by
    advancing the captain's depot_completions_seen_at stamp. Called when the
    captain dismisses the build-completion modal on /depot."""
    from utilities.build_completions import mark_completions_seen
    ok = mark_completions_seen(g.user_id)
    return jsonify({'success': bool(ok)})


@app.route('/api/upgrade-effects/breakdown', methods=['GET'])
@login_required
@handle_api_error
def api_upgrade_effects_breakdown():
    """Per-source contribution breakdown for the Active Bonus chips on /expeditions.

    Returns {effect_key: [{layer, source, value}, ...]} so the chip-click modal
    can show captains exactly where each +N% came from.
    """
    from utilities.upgrades.breakdown import get_user_effect_breakdown, SURFACED_KEYS
    from utilities.upgrades.effects import get_user_upgrade_effects
    breakdown = get_user_effect_breakdown(g.user_id)
    finals = get_user_upgrade_effects(g.user_id)
    finals_subset = {k: finals.get(k) for k in SURFACED_KEYS}
    meta = {k: {'label': lbl, 'op': op} for k, (lbl, op) in SURFACED_KEYS.items()}
    return jsonify({
        'success': True,
        'breakdown': breakdown,
        'finals': finals_subset,
        'meta': meta,
    })


@app.route('/api/signal/user/claims', methods=['GET'])
@login_required
@handle_api_error
def api_user_signal_claims():
    """Get current user's site claims."""
    return jsonify({'success': True, 'claims': get_user_signal_claims(g.user_id)})


@app.route('/api/signal/solvers', methods=['GET'])
@handle_api_error
def api_signal_solvers():
    """Get list of puzzle solvers for display."""
    return jsonify({'success': True, 'solvers': get_puzzle_solvers()})


@app.route('/api/signal/decode-tx', methods=['POST'])
@handle_api_error
def api_signal_decode_tx():
    """Decode a Sepolia transaction hash to extract hidden signal codes."""
    user_id = session.get('user_id')
    data = request.get_json() or {}
    return jsonify(decode_signal_tx(user_id, data.get('tx_hash')))

# ============================================================================
# ONBOARDING & SHOP API
# ============================================================================

@app.route('/upload', methods=['POST'])
@handle_api_error
def upload():
    """Process uploaded character image"""
    if not flux:
        raise Exception('Service not available')
    
    result = process_uploaded_image(request.files['image'], flux)
    initialize_character_session(session, result['image_url'], result['stats'])
    
    return jsonify({
        'success': True,
        'image_url': result['image_url'],
        'stats': result['stats'],
        'is_original': True
    })

@app.route('/random-default-leader')
@handle_api_error
def random_default_leader():
    """Get random pre-made commander"""
    return jsonify(handle_leader_selection(session, session.get('user_id')))

@app.route('/api/switch-leader/<leader_id>', methods=['POST'])
@handle_api_error
def api_switch_leader(leader_id):
    """Switch to different default leader"""
    return jsonify(handle_leader_selection(session, session.get('user_id'), leader_id))

@app.route('/reroll-stats', methods=['POST'])
@handle_api_error
def reroll_stats():
    """Free stat reroll during creation"""
    new_stats = generate_commander_stats()
    session['commander_stats'] = new_stats
    return jsonify({'success': True, 'stats': new_stats})

@app.route('/video-status')
def video_status():
    """Poll endpoint for video generation status"""
    video_info = app.config.get('video_status', {'generating': False, 'url': None})
    
    if not video_info['generating'] and video_info['url']:
        session.update({
            'character_video_url': video_info['url'],
            'video_generating': False
        })
    
    return jsonify({
        'video_url': video_info['url'],
        'generating': video_info['generating']
    })

@app.route('/reset', methods=['POST'])
@handle_api_error
def reset():
    """Reset all character and session data"""
    clear_character_session(session)
    return jsonify({'success': True})

@app.route('/api/mars_conditions', methods=['GET'])
@handle_api_error
def api_mars_conditions():
    """Get current Mars atmospheric conditions and pricing"""
    return jsonify(get_mars_conditions())

@app.route('/api/asteroid_impact', methods=['POST'])
@handle_api_error
def api_asteroid_impact():
    """Handle asteroid impact mining event"""
    return jsonify(process_asteroid_impact(session))

@app.route('/api/clear_session_wallet', methods=['POST'])
@handle_api_error
def api_clear_session_wallet():
    """Clear session wallet to allow claiming a new cache"""
    session.pop('_wal', None)
    session.pop('_wal_addr', None)
    return jsonify({'success': True})

@app.route('/api/shop/generate_video', methods=['POST'])
@handle_api_error
def api_shop_generate_video():
    """Purchase video generation for latest commander image"""
    if not flux:
        return jsonify({'success': False, 'error': 'Service not available'})
    return jsonify(start_video_generation(session, flux, app.config, animate_character_video))

@app.route('/api/shop/reroll_stats', methods=['POST'])
@handle_api_error
def api_shop_reroll_stats():
    """Purchase stat reroll with Sepolia"""
    return jsonify(purchase_stat_reroll(session))

@app.route('/api/shop/modify_character', methods=['POST'])
@handle_api_error
def api_shop_modify_character():
    """Purchase character modification with Sepolia"""
    if not flux:
        return jsonify({'success': False, 'error': 'Service not available'})

    data = request.get_json()
    edit_prompt = data.get('prompt', '').strip()

    return jsonify(purchase_character_modification(session, edit_prompt, flux))

@app.route('/api/discovery_items')
def api_discovery_items():
    """Get all discovery items for catalog viewer"""
    return jsonify(get_formatted_discovery_items())

# ============================================================================
# XENOBIOLOGY LAB - RESEARCH SYSTEM
# ============================================================================

@app.route('/api/xenobiology/status')
@handle_api_error
def api_xenobiology_status():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'})
    return jsonify(get_xenobiology_status(user_id))

@app.route('/api/xenobiology/run_experiment', methods=['POST'])
@handle_api_error
def api_run_experiment():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'})
    return jsonify(run_xenobiology_experiment(user_id, session))

@app.route('/api/xenobiology/upgrade_stat', methods=['POST'])
@handle_api_error
def api_upgrade_stat():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'})
    data = request.get_json()
    return jsonify(upgrade_xenobiology_stat(user_id, data.get('stat')))

# =============================================================================
# UPGRADE SYSTEM API (Generic upgrades for vehicles, storage, etc.)
# =============================================================================

@app.route('/api/upgrade', methods=['POST'])
@handle_api_error
def api_upgrade():
    """Universal upgrade endpoint for all upgradeable items."""
    from utilities.upgrades_utils import handle_upgrade_request
    return jsonify(handle_upgrade_request(session.get('user_id'), request.get_json() or {}, session))


@app.route('/api/shard-rush/upgrade', methods=['POST'])
@handle_api_error
def api_shard_rush_upgrade():
    """Shard Rush: pay shards to instantly complete an in-progress equipment/infrastructure upgrade (category in player_upgrades). Bug #1270 Phase 4."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'})
    data = request.get_json() or {}
    category = data.get('category')
    item_key = data.get('item_key')
    if not category or not item_key:
        return jsonify({'success': False, 'error': 'Missing category or item_key'})
    from utilities.upgrades.shard_rush import rush_equipment_upgrade
    return jsonify(rush_equipment_upgrade(user_id, category, item_key))


@app.route('/api/shard-rush/infrastructure', methods=['POST'])
@handle_api_error
def api_shard_rush_infrastructure():
    """Shard Rush: pay shards to finish an in-progress Lv1 infrastructure build. Bug #1270 Phase 4."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'})
    data = request.get_json() or {}
    structure_type = data.get('structure_type')
    if not structure_type:
        return jsonify({'success': False, 'error': 'Missing structure_type'})
    from utilities.upgrades.shard_rush import rush_infrastructure_build
    return jsonify(rush_infrastructure_build(user_id, structure_type))


@app.route('/api/upgrades/catalog')
@handle_api_error
def api_upgrades_catalog():
    """Get the full upgrade catalog with user's current levels and affordability"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'})

    catalog = get_upgrade_catalog_for_user(user_id)
    return jsonify({'success': True, 'catalog': catalog})


@app.route('/api/upgrades/vehicle/<vehicle_type>')
@handle_api_error
def api_vehicle_stats(vehicle_type):
    """Get current vehicle stats for expedition UI"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'})

    vehicle = get_vehicle_for_expedition(user_id, vehicle_type)
    if not vehicle:
        return jsonify({'success': False, 'error': 'Vehicle not unlocked'})

    return jsonify({'success': True, 'vehicle': vehicle})

# =============================================================================
# CRON ENDPOINTS (App Engine scheduled tasks)
# =============================================================================

@app.route('/api/cron/sync_balances', methods=['GET'])
@cron_only
def cron_sync_balances():
    """Hourly blockchain balance sync — updates wallet balances in DB."""
    try:
        result = sync_all_wallet_balances()
        logger.info(f"✅ Balance sync completed: {result['updated']}/{result['total']} wallets updated")
        return jsonify({'success': True, **result})
    except Exception as e:
        logger.error(f"❌ Balance sync failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/cron/aria_test_email', methods=['GET'])
@cron_only
def cron_aria_test_email():
    """Hourly ARIA email — TEST ONLY, sends to andy.tillo@gmail.com."""
    result = handle_cron_aria_test_email(request.headers.get('X-Appengine-Cron'), app.debug)
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@app.route('/api/cron/generate_snapshots', methods=['GET'])
@cron_only
def cron_generate_snapshots():
    """Daily ARIA Photo Journal generation — background thread."""
    start_background_snapshot_generation()
    return jsonify({'success': True, 'message': 'Snapshot generation started in background'})


@app.route('/api/cron/qa_bot', methods=['GET'])
@cron_only
def cron_qa_bot():
    """QA Bot — plays the game as user 250 to catch regressions."""
    try:
        from tools.qa_bot import run_bot_session
        result = run_bot_session()
        status_code = 200 if not result.get('errors') else 207
        return jsonify({'success': True, **result}), status_code
    except Exception as e:
        logger.error(f"QA Bot failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/cron/retry_bonds', methods=['GET'])
@cron_only
def cron_retry_bonds():
    """Retry stuck ARIA bonds that failed to create blockchain tx."""
    try:
        from utilities.aria.bonds import retry_stuck_bonds
        result = retry_stuck_bonds()
        return jsonify({'success': True, **result})
    except Exception as e:
        logger.error(f"Bond retry cron failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/cron/drone_trail_build', methods=['GET'])
@cron_only
def cron_drone_trail_build():
    """Passive trail building via Automation Drone upgrades (every 30 min)."""
    try:
        from utilities.postgres.trails import cron_drone_trail_build
        results = cron_drone_trail_build()
        return jsonify({'success': True, 'results': results, 'count': len(results)})
    except Exception as e:
        logger.error(f"Drone trail cron failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# ADMIN FUNCTIONS & ROUTES
# =============================================================================

@app.route('/mimic', methods=['GET', 'POST'])
def admin_mimic():
    """Admin-only: mimic another user's session for debugging."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return redirect(url_for('home'))

    if request.method == 'POST':
        handle_mimic_action(session, request.form.get('action'),
                            request.form.get('target_user_id', 0), real_user_id)
        return redirect(url_for('admin_mimic'))

    users, mimicking = get_mimic_page_data(real_user_id, session)
    return render_template('mimic.html', users=users, mimicking=mimicking)


########################################################################
# ARIA FIRST CONTACT — Cinematic bond reveal
########################################################################

@app.route('/aria-first-contact')
def aria_first_contact():
    """Full-screen cinematic for ARIA bond first contact. Shown once per user per bond."""
    if not auth.is_authenticated():
        return redirect(url_for('home'))
    from utilities.aria.first_contact import build_first_contact_render_data
    payload, redirect_to = build_first_contact_render_data(session.get('user_id'), session)
    if redirect_to:
        return redirect(url_for(redirect_to))
    return render_template('aria_first_contact.html', static_v=STATIC_V, **payload)


@app.route('/aria-first-contact/replay')
def aria_first_contact_replay():
    """Replay the First Contact cinematic for a completed bond. No bond completion on Continue."""
    if not auth.is_authenticated():
        return redirect(url_for('home'))
    from utilities.aria.first_contact import build_replay_render_data
    payload, redirect_to = build_replay_render_data(session.get('user_id'))
    if redirect_to:
        return redirect(url_for(redirect_to))
    return render_template('aria_first_contact.html', static_v=STATIC_V, **payload)


@app.route('/admin/preview-first-contact')
def admin_preview_first_contact():
    """Admin preview of the First Contact cinematic — bond #3 data, no side effects."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return redirect(url_for('home'))
    from utilities.aria.first_contact import build_admin_preview_render_data
    payload, err = build_admin_preview_render_data()
    if err:
        return err, 404
    return render_template('aria_first_contact.html', static_v=STATIC_V, **payload)


@app.route('/api/aria-bond/complete', methods=['POST'])
@handle_api_error
def api_aria_bond_complete():
    """Complete ARIA bond from First Contact cinematic."""
    if not auth.is_authenticated():
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    from utilities.aria.first_contact import complete_bond_from_cinematic
    data = request.get_json() or {}
    return jsonify(complete_bond_from_cinematic(session.get('user_id'), data.get('bond_id'), session))


@app.route('/api/aria-bond/<int:bond_id>/choose_bonus', methods=['POST'])
@handle_api_error
def api_aria_bond_choose_bonus(bond_id):
    """Pick a Fragment Bond bonus (Bug #1402). Body: {bonus_type: 'A'..'F'}."""
    if not auth.is_authenticated():
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    from utilities.aria.bond_bonuses import pick_bond_bonus
    data = request.get_json() or {}
    bonus_type = (data.get('bonus_type') or '').strip().upper()
    return jsonify(pick_bond_bonus(session.get('user_id'), bond_id, bonus_type))


########################################################################
# SIGNAL CLAIM CINEMATIC — Phase 2.3b
########################################################################

@app.route('/signal-claim/<int:expedition_id>')
def signal_claim_cinematic(expedition_id):
    """Full-screen cinematic for a completed signal_claim expedition. One-shot per expedition."""
    if not auth.is_authenticated():
        return redirect(url_for('home'))
    from utilities.aria.signal_cinematic import build_signal_cinematic_render_data
    payload, redirect_to = build_signal_cinematic_render_data(session.get('user_id'), expedition_id, session)
    if redirect_to:
        return redirect(url_for(redirect_to))
    return render_template('signal_claim_cinematic.html', static_v=STATIC_V, **payload)


@app.route('/signal-claim/<int:expedition_id>/replay')
def signal_claim_cinematic_replay(expedition_id):
    """Replay variant — no DB writes, no one-shot mutation."""
    if not auth.is_authenticated():
        return redirect(url_for('home'))
    from utilities.aria.signal_cinematic import build_signal_cinematic_replay_render_data
    payload, redirect_to = build_signal_cinematic_replay_render_data(session.get('user_id'), expedition_id)
    if redirect_to:
        return redirect(url_for(redirect_to))
    return render_template('signal_claim_cinematic.html', static_v=STATIC_V, **payload)


@app.route('/admin/preview-signal-claim')
def admin_preview_signal_claim():
    """Admin preview — synthesize a payload (founder outcome) without firing a real claim."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return redirect(url_for('home'))
    from utilities.aria.signal_cinematic import build_admin_preview_render_data
    payload, err = build_admin_preview_render_data()
    if err:
        return err, 404
    return render_template('signal_claim_cinematic.html', static_v=STATIC_V, **payload)


@app.route('/admin')
def admin_dashboard():
    """Admin dashboard with tools and overview stats."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return redirect(url_for('home'))

    data = get_admin_dashboard_data(real_user_id)
    return render_template('admin.html', user=auth.get_current_user(), **data)


@app.route('/api/admin/generate_snapshots', methods=['POST'])
@handle_api_error
def api_admin_generate_snapshots():
    """Admin-only: Trigger ARIA Photo Journal generation manually."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    data = request.get_json() or {}
    result = handle_admin_generate_snapshots(data.get('user_id'), data.get('dry_run', False))
    return jsonify(result)


@app.route('/api/admin/sync_balances', methods=['POST'])
@handle_api_error
def api_admin_sync_balances():
    """Admin-only: Trigger blockchain balance sync manually."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    return jsonify(handle_admin_sync_balances())


@app.route('/api/admin/test_email', methods=['POST'])
@handle_api_error
def api_admin_test_email():
    """Admin-only: Send test ARIA email to specified address."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    data = request.get_json() or {}
    result = handle_admin_test_email(real_user_id, data.get('email'))
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@app.route('/api/admin/clear_aria_chats', methods=['POST'])
@handle_api_error
def api_admin_clear_aria_chats():
    """Admin-only: Clear ALL ARIA conversation history for ALL users."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    from utilities.aria.conversation import clear_all_aria_conversations
    return jsonify(clear_all_aria_conversations())


@app.route('/admin/speed')
def admin_speed():
    """Admin speed test page with history and charts."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return redirect(url_for('home'))
    from utilities.admin_utils import get_speed_page_data
    return render_template('admin_speed.html', active_tab=None,
                           user=auth.get_current_user(), **get_speed_page_data())


@app.route('/api/admin/speed_test', methods=['POST'])
@handle_api_error
def api_admin_speed_test():
    """Admin-only: Time server-side page data functions and save to DB."""
    from utilities.admin.speed_testing import execute_speed_test
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    pages, all_ok = execute_speed_test(real_user_id, auth)
    return jsonify({'success': True, 'results': pages, 'threshold_s': 3.0, 'all_ok': all_ok})


@app.route('/api/admin/pool_health', methods=['GET'])
@handle_api_error
def api_admin_pool_health():
    """Admin-only: Connection pool + DB health stats."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    from utilities.postgres.core import get_pool_health, get_db_connection_stats
    return jsonify({'success': True, 'pool': get_pool_health(), 'db': get_db_connection_stats()})


# =============================================================================
# BUG TRACKER — Admin bug tracking system
# =============================================================================

@app.route('/admin/bugs')
def admin_bugs():
    """Bug tracker page — replaces Google Sheets."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return redirect(url_for('home'))
    from utilities.postgres.bugs import get_active_bugs, get_completed_bugs, get_ideas, get_bug_stats
    from utilities.postgres.core import db_cursor, _fetchall
    with db_cursor() as cur:
        cur.execute("SELECT name, given_name, email FROM pilgrim.users WHERE is_admin = true ORDER BY name")
        mention_users = [{'name': r['name'], 'handle': (r.get('given_name') or r['name'].split()[0]).lower(), 'email': r['email']} for r in _fetchall(cur)]
    return render_template('admin_bugs.html', user=auth.get_current_user(),
        active_bugs=get_active_bugs(), completed_bugs=get_completed_bugs(),
        ideas=get_ideas(), stats=get_bug_stats() or {}, mention_users=mention_users)


@app.route('/api/admin/bugs', methods=['GET'])
@handle_api_error
def api_admin_bugs_list():
    """List bugs with optional filters."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    from utilities.postgres.bugs import get_active_bugs, get_completed_bugs, get_ideas, get_bug_stats
    return jsonify({'success': True,
        'active': get_active_bugs(), 'completed': get_completed_bugs(),
        'ideas': get_ideas(), 'stats': get_bug_stats() or {}})


@app.route('/api/admin/bugs', methods=['POST'])
@handle_api_error
def api_admin_bugs_create():
    """Create a new bug."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    from utilities.postgres.bugs import create_bug
    data = request.get_json() or {}
    bug = create_bug(name=data.get('name', ''), description=data.get('description', ''),
        type=data.get('type', 'Bug'), priority=data.get('priority', 'P3'),
        source=data.get('source', 'QA'))
    return jsonify({'success': bool(bug), 'bug': bug})


@app.route('/api/admin/bugs/<int:bug_id>', methods=['GET'])
@handle_api_error
def api_admin_bugs_get(bug_id):
    """Get single bug with history and comments."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    from utilities.postgres.bugs import get_bug_by_id, get_bug_history, get_bug_comments
    bug = get_bug_by_id(bug_id)
    return jsonify({'success': bool(bug), 'bug': bug,
        'history': get_bug_history(bug_id) if bug else [],
        'comments': get_bug_comments(bug_id) if bug else []})


@app.route('/api/admin/bugs/<int:bug_id>', methods=['PUT'])
@handle_api_error
def api_admin_bugs_update(bug_id):
    """Update bug fields."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    from utilities.postgres.bugs import update_bug
    data = request.get_json() or {}
    changed_by = data.pop('changed_by', 'Admin')
    ok = update_bug(bug_id, changed_by, **data)
    return jsonify({'success': ok})


@app.route('/api/admin/bugs/<int:bug_id>/complete', methods=['POST'])
@handle_api_error
def api_admin_bugs_complete(bug_id):
    """Mark bug as completed."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    from utilities.postgres.bugs import complete_bug
    data = request.get_json() or {}
    ok, err = complete_bug(bug_id, data.get('changed_by', 'Admin'))
    return jsonify({'success': ok, 'error': err})


@app.route('/api/admin/bugs/<int:bug_id>/reopen', methods=['POST'])
@handle_api_error
def api_admin_bugs_reopen(bug_id):
    """Reopen a completed bug."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    from utilities.postgres.bugs import reopen_bug
    data = request.get_json() or {}
    ok, err = reopen_bug(bug_id, data.get('changed_by', 'Admin'))
    return jsonify({'success': ok})


@app.route('/api/admin/bugs/<int:bug_id>/screenshot', methods=['POST'])
@handle_api_error
def api_admin_bugs_screenshot(bug_id):
    """Upload screenshot/video for a bug."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    from utilities.postgres.bugs import handle_bug_screenshot_upload
    return jsonify(handle_bug_screenshot_upload(bug_id, request.files.get('file')))


@app.route('/api/admin/bugs/<int:bug_id>/screenshot/<field>', methods=['DELETE'])
@handle_api_error
def api_admin_bugs_delete_screenshot(bug_id, field):
    """Remove a screenshot from a bug."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    if field not in ('screenshot_url', 'screenshot_2_url', 'screenshot_3_url'):
        return jsonify({'success': False, 'error': 'Invalid field'})
    from utilities.postgres.bugs import update_bug
    update_bug(bug_id, 'system', **{field: ''})
    return jsonify({'success': True})


@app.route('/api/admin/bugs/<int:bug_id>/comments', methods=['POST'])
@handle_api_error
def api_admin_bugs_comment(bug_id):
    """Add a comment to a bug."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    from utilities.postgres.bugs import add_bug_comment
    data = request.get_json() or {}
    body = (data.get('body') or '').strip()
    if not body:
        return jsonify({'success': False, 'error': 'Comment body required'})
    comment = add_bug_comment(bug_id, data.get('author', 'Admin'), body)
    return jsonify({'success': bool(comment), 'comment': comment})


@app.route('/api/admin/bugs/ideas', methods=['GET'])
@handle_api_error
def api_admin_ideas_list():
    """List ideas."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    from utilities.postgres.bugs import get_ideas
    return jsonify({'success': True, 'ideas': get_ideas()})


@app.route('/api/admin/bugs/ideas', methods=['POST'])
@handle_api_error
def api_admin_ideas_create():
    """Create a new idea."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    from utilities.postgres.bugs import create_idea
    data = request.get_json() or {}
    idea = create_idea(name=data.get('name', ''), description=data.get('description', ''),
        category=data.get('category', 'Feature'))
    return jsonify({'success': bool(idea), 'idea': idea})


@app.route('/api/admin/bugs/ideas/<int:idea_id>/promote', methods=['POST'])
@handle_api_error
def api_admin_ideas_promote(idea_id):
    """Promote idea to active bug."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    from utilities.postgres.bugs import promote_idea
    data = request.get_json() or {}
    bug = promote_idea(idea_id, data.get('priority', 'P3'))
    return jsonify({'success': bool(bug), 'bug': bug})


# =============================================================================
# PILGRIMBOT — Codebase Q&A (admin-only for now, public-ready routes)
# =============================================================================

@app.route('/pilgrimbot')
def pilgrimbot():
    """PilgrimBot chat interface — codebase Q&A."""
    if not session.get('_adm'):
        return redirect(url_for('home'))
    from utilities.pilgrimbot.storage import get_pilgrimbot_page_data
    real_user_id = session.get('_real_uid') or session.get('user_id')
    page_data = get_pilgrimbot_page_data(
        real_user_id, session,
        request.args.get('brainstorm'), request.args.get('bug'),
    )
    return render_template('pilgrimbot.html', user=auth.get_current_user(), **page_data)


@app.route('/api/pilgrimbot/chat', methods=['POST'])
def api_pilgrimbot_chat():
    """Chat with PilgrimBot — streaming SSE response."""
    from utilities.pilgrimbot_utils import handle_pilgrimbot_chat_request
    real_user_id = session.get('_real_uid') or session.get('user_id')
    outcome = handle_pilgrimbot_chat_request(request.get_json() or {}, real_user_id, session, auth)
    if 'error' in outcome:
        return jsonify({'success': False, 'error': outcome['error']}), outcome.get('status', 200)
    return Response(
        stream_with_context(outcome['generator']),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache, no-store, must-revalidate',
                 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'}
    )


@app.route('/api/pilgrimbot/report', methods=['POST'])
def api_pilgrimbot_report():
    """Submit a bug/feature from PilgrimBot chat."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not session.get('_adm'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    data = request.get_json() or {}
    title = data.get('title', '').strip()
    description = data.get('description', '').strip()
    if not title:
        return jsonify({'success': False, 'error': 'Title is required'})
    display_name = auth.get_current_user().get('name', 'Unknown') if auth.get_current_user() else 'Unknown'
    from utilities.pilgrimbot_utils import create_bug_from_question
    success = create_bug_from_question(title, display_name, description=description)
    return jsonify({'success': success})


@app.route('/api/pilgrimbot/create_bug', methods=['POST'])
def api_pilgrimbot_create_bug():
    """Create a bug from PilgrimBot conversation — Claude parses context into title + description."""
    if not session.get('_adm'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    from utilities.pilgrimbot_bugs import handle_create_bug_request
    real_user_id = session.get('_real_uid') or session.get('user_id')
    return jsonify(handle_create_bug_request(real_user_id, request.get_json() or {}))


@app.route('/api/pilgrimbot/upload', methods=['POST'])
def api_pilgrimbot_upload():
    """Upload a pasted screenshot for PilgrimBot chat. Returns GCS URL."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    from utilities.pilgrimbot.storage import upload_pilgrimbot_screenshot
    result = upload_pilgrimbot_screenshot(real_user_id, request.files.get('image'))
    if not real_user_id:
        return jsonify(result), 403
    return jsonify(result)


@app.route('/api/pilgrimbot/role', methods=['POST'])
def api_pilgrimbot_role():
    """Set user's PilgrimBot persona role (dev/qa/captain). Any user can pick."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not real_user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 403
    role = (request.get_json() or {}).get('role', 'captain')
    from utilities.pilgrimbot_utils import set_user_role
    if set_user_role(real_user_id, role):
        session['_pb_role'] = role  # Update cached role
        return jsonify({'success': True, 'role': role})
    return jsonify({'success': False, 'error': 'Invalid role'}), 400


@app.route('/api/pilgrimbot/hide', methods=['POST'])
def api_pilgrimbot_hide():
    """Hide (soft-delete) a PilgrimBot conversation."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not real_user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 403
    chat_id = (request.get_json() or {}).get('chat_id')
    if not chat_id:
        return jsonify({'success': False, 'error': 'No chat_id'}), 400
    from utilities.pilgrimbot_utils import hide_chat
    result = hide_chat(real_user_id, chat_id)
    return jsonify({'success': bool(result)})


@app.route('/api/pilgrimbot/chats', methods=['GET'])
def api_pilgrimbot_chats():
    """List user's PilgrimBot chat threads."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not session.get('_adm'):
        return jsonify({'success': False}), 403
    from utilities.pilgrimbot_utils import get_user_chats
    return jsonify({'success': True, 'chats': get_user_chats(real_user_id)})


@app.route('/api/pilgrimbot/history', methods=['GET'])
def api_pilgrimbot_history():
    """Load message history for a specific PilgrimBot chat."""
    if not session.get('_adm'):
        return jsonify({'success': False}), 403
    chat_id = request.args.get('chat_id', '')
    if not chat_id:
        return jsonify({'success': False, 'error': 'No chat_id'})
    from utilities.pilgrimbot.storage import get_chat_history
    real_user_id = session.get('_real_uid') or session.get('user_id')
    return jsonify({'success': True, 'messages': get_chat_history(real_user_id, chat_id, limit=100)})


if __name__ == '__main__':
    try:
        port = get_available_port()

        from threading import Timer
        import webbrowser
        Timer(1.5, lambda: webbrowser.open(f'http://localhost:{port}')).start()

        app.run(host=DEFAULT_HOST, port=port, debug=True, use_reloader=False)
        
    except KeyboardInterrupt:
        logger.info("\nShutting down gracefully...")
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
    finally:
        logger.info(f"{APP_NAME} stopped")
