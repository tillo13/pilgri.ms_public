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

from config import APP_NAME, SECRET_KEY_ID, DEV_SECRET_KEY, DEFAULT_HOST, PORT_RANGE_START, get_available_port, kill_port_processes, UI_ICONS

# Cache-bust static files on each deploy (timestamp at startup)
STATIC_V = str(int(time.time()))
from utilities.replicate_utils import FluxGenerator, process_uploaded_image, animate_character_video
from utilities.google_auth_utils import SimpleGoogleAuth, get_secret
from utilities.postgres.core import db_cursor
from utilities.postgres.assets import (
    set_primary_commander,
    delete_asset,
    update_commander_name,
    get_user_commander,
)
from utilities.postgres.expeditions import (
    get_recent_discoveries,
    get_discovery_item_details,
    claim_expedition_discovery,
    get_total_unclaimed_discoveries_count,
)
from utilities.expeditions.formatters import (
    get_expedition_history_payload,
    get_expedition_items_payload,
)
from utilities.postgres.shop import get_unified_activity
from utilities.postgres.notifications import get_commander_quotes, get_commander_quote_count, get_user_fomo_data
from utilities.postgres.users import get_user_scientist, hydrate_user_session, get_user_by_id
from utilities.postgres.trails import (
    get_crew_mission_status,
    get_aria_skills,
    get_visited_sites_for_trails,
    start_crew_mission,
    complete_crew_mission,
    use_aria_resonance,
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
    get_expedition_cost_preview_formatted, get_expedition_preview,
)
from utilities.expeditions.trails import handle_trail_build_request, get_trail_consumables_data
from utilities.discovery_utils import analyze_discovery, shard_all_discoveries
from utilities.depot_utils import (
    purchase_stat_reroll, purchase_character_modification, get_command_page_data,
    process_asteroid_impact, generate_commander_stats, initialize_character_session,
    clear_character_session, get_arrival_mining_data, get_arrival_commander_data,
    get_arrival_deploy_data, handle_auth_callback, get_mars_conditions,
    get_dashboard_page_data, get_profile_page_data, get_depot_page_data, get_claimed_discoveries_data,
    start_video_generation, get_formatted_discovery_items, build_recent_activity,
    start_deploy_video_generation, handle_leader_selection, get_mars_location_data,
    handle_custom_commander_upload, check_content_filter,
    get_colony_page_data, get_live_balance_and_wallet_info, invalidate_balance_cache,
)
from utilities.infrastructure_utils import (
    get_infrastructure_page_data, handle_infrastructure_build,
    handle_accumulated_income, claim_accumulated_income, record_science_value,
    get_xenobiology_status, run_xenobiology_experiment, upgrade_xenobiology_stat,
)
from utilities.signal_utils import (
    get_signal_page_data, get_closest_pilgrim_to_origin,
    handle_origin_site_claim, handle_origin_site_visit,
    claim_echo_site, get_user_origin_site_eligibility,
    decode_lost_signal_site, get_origin_site_legendary_item,
    get_user_signal_claims, get_puzzle_solvers, decode_signal_tx,
)
from utilities.tech_utils import (
    get_research_page_data, get_user_tech_status, start_research,
    get_research_progress, cancel_research,
)
from utilities.shop_utils import get_user_equipment_data
from utilities.upgrades_utils import perform_upgrade, get_upgrade_catalog_for_user, get_vehicle_for_expedition
from utilities.claude_utils import brainstorm_chat, generate_aria_snapshot_narrative
from utilities.aria.handlers import (
    get_aria_album_data, _build_aria_user_context,
    handle_aria_chat_streaming, handle_aria_chat_sync,
)
from utilities.aria.animations import get_contextual_hint
from utilities.aria.conversation import get_aria_conversation_history
from utilities.aria.greetings import get_aria_greeting
from utilities.aria.snapshot import load_colony_snapshot
from utilities.captains_log_utils import chat_with_captain
from utilities.admin_utils import (
    is_admin, get_admin_email, generate_aria_message,
    get_admin_dashboard_data, handle_mimic_action, get_mimic_page_data,
    handle_cron_aria_test_email, start_background_snapshot_generation,
    handle_admin_generate_snapshots, handle_admin_sync_balances, handle_admin_test_email,
    handle_apikey_auth,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

kill_port_processes(PORT_RANGE_START)
app = Flask(__name__)

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
    """Start timing the request."""
    g.start_time = time.time()

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
    """Intercept page loads for pending ARIA bond first-contact cinematic.
    Server-side check — browser cache doesn't matter, the HTML response changes."""
    # Only for authenticated users on HTML page routes
    if not auth.is_authenticated():
        return
    path = request.path
    if path.startswith(('/static/', '/api/', '/admin/', '/aria-first-contact', '/auth')):
        return
    if request.method != 'GET':
        return
    # Session flag: skip check once ALL pending cinematics have been shown this session
    # Stores set of bond IDs already shown
    if session.get('_fc_shown_all'):
        return
    user_id = session.get('user_id')
    if not user_id:
        return
    try:
        from utilities.aria.bonds import get_pending_first_contact
        bond = get_pending_first_contact(user_id)
        if bond:
            return redirect('/aria-first-contact')
        else:
            # No more pending cinematics — stop checking this session
            session['_fc_shown_all'] = True
            session.modified = True
    except Exception as e:
        logger.warning(f"First contact check failed: {e}")

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

        logger.info(f"{color}⏱️  {request.method} {request.path}{user_tag} → {duration:.1f}ms{reset}")
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
    return Response(ROBOTS_TXT, mimetype='text/plain')

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
        # Authenticated user - show their commander profile (same data as command page)
        data = get_command_page_data(session.get('user_id'))
        # Captain services pricing (Shard Infusion, Modify Appearance, Video Briefing)
        from utilities.depot_utils import get_pricing_info
        data['pricing'] = get_pricing_info(session.get('user_id'))
        # Robot tab data — auto-advances any ready stages on every render
        from utilities.postgres.robot import get_robot_page_data
        data['robot_data'] = get_robot_page_data(session.get('user_id'))
        return render_template('crew.html', active_tab='crew', user=auth.get_current_user(), **data)
    else:
        # Anonymous user - show commander selection (onboarding step 2)
        data = get_arrival_commander_data(session, None)
        if 'redirect' in data:
            return redirect(url_for(data['redirect']))
        return render_template('crew.html', active_tab='crew', user=None, **data)


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


@app.route('/api/robot/build', methods=['POST'])
@login_required
@handle_api_error
def api_robot_build():
    """Start a new robot build."""
    from utilities.postgres.robot import start_build_with_name_prefetch
    cmd_name = session.get('_cmd', {}).get('name') if session.get('_cmd') else None
    sci_name = session.get('scientist_name')
    payload, status = start_build_with_name_prefetch(g.user_id, cmd_name, sci_name)
    return jsonify(payload), status


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
    import threading
    from utilities.postgres.robot import get_robot
    robot = get_robot(g.user_id)
    if not robot or robot.get('build_status') != 'complete':
        return jsonify({'success': False, 'error': 'Golem must be fully built.'}), 400
    if robot.get('video_url'):
        return jsonify({'success': True, 'video_url': robot['video_url'], 'already_exists': True})

    image_url = robot.get('current_image_url')
    if not image_url:
        return jsonify({'success': False, 'error': 'No golem image found.'}), 400

    uid = g.user_id
    status_key = f'golem_video_{uid}'
    app.config[status_key] = {'generating': True, 'url': None}

    def _gen():
        try:
            video_url = animate_character_video(image_url, flux, user_id=uid)
            app.config[status_key].update({'url': video_url, 'generating': False})
            from utilities.postgres.core import db_cursor
            with db_cursor(commit=True) as cur:
                cur.execute("UPDATE pilgrim.robot SET video_url = %s, updated_at = NOW() WHERE user_id = %s",
                            (video_url, uid))
        except Exception as e:
            logger.error(f"Golem video gen failed: {e}")
            app.config[status_key].update({'url': None, 'generating': False, 'error': str(e)})

    threading.Thread(target=_gen, daemon=True).start()
    return jsonify({'success': True, 'status_key': status_key, 'generating': True})


@app.route('/api/robot/video_status')
@login_required
@handle_api_error
def api_robot_video_status():
    """Poll golem video generation progress."""
    status_key = f'golem_video_{g.user_id}'
    status = app.config.get(status_key, {})
    return jsonify({'success': True, **status})


@app.route('/api/robot/suggest_names', methods=['POST'])
@login_required
@handle_api_error
def api_robot_suggest_names():
    """Generate 5 AI-suggested golem names based on colony context."""
    from utilities.claude_utils import suggest_golem_names
    from utilities.postgres.robot import get_robot_page_data
    data = get_robot_page_data(g.user_id)
    robot = data.get('robot') or {}
    commander_name = session.get('_cmd', {}).get('name') if session.get('_cmd') else None
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
    from utilities.postgres.brainstorm import add_comment
    data = request.get_json() or {}
    text = (data.get('text') or '').strip()
    if not text or len(text) > 2000:
        return jsonify({'success': False, 'error': 'Comment must be 1-2000 characters'})
    section_idx = data.get('section_idx')
    if section_idx is None or not isinstance(section_idx, int):
        return jsonify({'success': False, 'error': 'Missing section_idx'})

    if auth.is_authenticated():
        author_name = auth.get_current_user().get('name', 'Unknown')
        author_type = 'user'
    else:
        anon_id = request.cookies.get('bs_anon')
        if not anon_id:
            import random, string
            anon_id = 'anon_' + ''.join(random.choices(string.digits, k=5))
        author_name = anon_id
        author_type = 'anon'

    comment = add_comment(page_key, section_idx, author_name, author_type, text)
    comment['created_at'] = comment['created_at'].isoformat() if comment['created_at'] else None
    resp = jsonify({'success': True, 'comment': comment})
    if author_type == 'anon':
        resp.set_cookie('bs_anon', author_name, max_age=60*60*24*365, httponly=True, samesite='Lax')
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
    user = auth.get_current_user() if auth.is_authenticated() else None

    # Get all signal page data
    signal_data = get_signal_page_data()

    # Reuse origin_sites from signal_data (avoid duplicate DB call)
    closest_pilgrim = get_closest_pilgrim_to_origin(origin_sites=signal_data.get('origin_sites'))

    # Check for ARIA bonds to show on Signal page
    bond_fragment_hint = None
    signal_bonds = []
    if auth.is_authenticated():
        try:
            from utilities.aria.bonds import get_bonds_for_display
            signal_bonds = get_bonds_for_display(session.get('user_id'))
            if signal_bonds:
                bond_fragment_hint = signal_bonds[0]['bond_tx_hash']
        except Exception:
            pass

    return render_template('signal.html',
                           active_tab='signal',
                           user=user,
                           closest_pilgrim=closest_pilgrim,
                           bond_fragment_hint=bond_fragment_hint,
                           signal_bonds=signal_bonds,
                           **signal_data)

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
    data = request.get_json()

    if not data or 'name' not in data:
        return jsonify({'success': False, 'error': 'Name is required'})

    new_name = data['name'].strip()

    if len(new_name) < 2:
        return jsonify({'success': False, 'error': 'Name must be at least 2 characters'})
    if len(new_name) > 30:
        return jsonify({'success': False, 'error': 'Name must be 30 characters or less'})

    is_clean, error_msg = check_content_filter(new_name)
    if not is_clean:
        return jsonify({'success': False, 'error': 'Please choose an appropriate name'})

    success = update_commander_name(g.user_id, new_name)

    if success:
        session.pop('_cmd', None)
        session.modified = True
        logger.info(f"✅ User {g.user_id} renamed captain to '{new_name}'")
        return jsonify({'success': True, 'message': 'Captain renamed successfully', 'new_name': new_name})
    else:
        return jsonify({'success': False, 'error': 'Failed to rename captain'})

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
    try:
        discoveries = get_recent_discoveries(g.user_id, limit=3)
        total_unclaimed = get_total_unclaimed_discoveries_count(g.user_id)

        return jsonify({
            'success': True,
            'discoveries': discoveries,
            'count': len(discoveries),
            'total_unclaimed': total_unclaimed
        })
        
    except Exception as e:
        logger.error(f"Failed to get recent discoveries: {e}")
        return jsonify({'success': False, 'error': str(e)})

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
    """
    Public page showing a commander's quote history (Captain's Log).
    Anyone can view this - it's meant to be shareable.
    """
    fomo_data = get_user_fomo_data(user_id)
    commander = fomo_data.get('commander') if fomo_data else None
    quotes = get_commander_quotes(user_id, limit=100)
    quote_count = get_commander_quote_count(user_id)

    if not commander:
        return render_template('captains_log.html',
            commander=None,
            quotes=[],
            quote_count=0,
            user_id=user_id
        )

    return render_template('captains_log.html',
        commander=commander,
        quotes=quotes,
        quote_count=quote_count,
        user_id=user_id,
        expedition_stats=fomo_data.get('expedition_stats', {}),
        discovery_stats=fomo_data.get('discovery_stats', {})
    )


@app.route('/api/captains-log/chat', methods=['POST'])
def api_captains_log_chat():
    """
    Chat with a captain using Haiku.
    Public endpoint - no login required (anyone viewing the log can chat).
    """
    data = request.get_json() or {}
    user_id = data.get('user_id')
    message = data.get('message', '').strip()
    conversation_history = data.get('conversation_history', [])

    if not user_id:
        return jsonify({'success': False, 'error': 'No user_id provided'})
    if not message:
        return jsonify({'success': False, 'error': 'No message provided'})

    result = chat_with_captain(
        user_id=user_id,
        message=message,
        conversation_history=conversation_history
    )

    return jsonify(result)


@app.route('/api/aria/snapshot-narrative', methods=['POST'])
def api_aria_snapshot_narrative():
    """
    Generate an ARIA narrative for a photo journal snapshot.
    Like an Instagram caption - ARIA describes what's happening in the image.
    Uses Claude to generate a short, in-character response.
    """
    data = request.get_json() or {}
    snapshot_id = data.get('snapshot_id')
    caption = data.get('caption', '')
    snapshot_type = data.get('type', '')
    image_url = data.get('image_url', '')

    if not caption:
        return jsonify({'success': False, 'error': 'No caption provided'})

    user_id = session.get('user_id')
    commander_name = None

    # Get commander name for personalization
    if user_id:
        try:
            commander = get_user_commander(user_id)
            if commander:
                commander_name = commander.get('name')
        except Exception:
            pass

    try:
        narrative = generate_aria_snapshot_narrative(
            caption=caption,
            snapshot_type=snapshot_type,
            commander_name=commander_name,
            user_id=user_id,
        )
        return jsonify({
            'success': True,
            'narrative': narrative
        })
    except Exception as e:
        logger.error(f"Error generating snapshot narrative: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/aria/snapshot/delete', methods=['POST'])
@handle_api_error
def api_aria_snapshot_delete():
    """Delete (soft) a snapshot from user's photo gallery"""
    if not auth.is_authenticated():
        return jsonify({'success': False, 'error': 'Not logged in'})

    user_id = session.get('user_id')
    data = request.get_json() or {}
    snapshot_id = data.get('snapshot_id')

    if not snapshot_id:
        return jsonify({'success': False, 'error': 'Missing snapshot_id'})

    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE pilgrim.generated_images
            SET is_active = false
            WHERE id = %s AND user_id = %s AND category = 'aria_snapshot'
            RETURNING id
        """, (snapshot_id, user_id))
        result = cur.fetchone()

    if result:
        return jsonify({'success': True, 'deleted_id': snapshot_id})
    else:
        return jsonify({'success': False, 'error': 'Snapshot not found'})


@app.route('/api/aria/history', methods=['GET'])
def api_aria_history():
    """
    Get ARIA conversation history for the authenticated user.
    Returns the last 20 messages from the database.
    """
    if not auth.is_authenticated():
        return jsonify({'success': True, 'history': [], 'authenticated': False})

    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': True, 'history': [], 'authenticated': False})

    history = get_aria_conversation_history(user_id, limit=20)

    return jsonify({
        'success': True,
        'history': history,
        'authenticated': True
    })


@app.route('/api/aria/chat', methods=['POST'])
def api_aria_chat():
    """Chat with ARIA - supports streaming (SSE) when stream=true."""
    data = request.get_json() or {}
    message = data.get('message', '').strip()
    if not message:
        return jsonify({'success': False, 'error': 'No message provided'})

    user_id = session.get('user_id')
    is_authenticated = auth.is_authenticated()

    # Load colony snapshot for authenticated users
    aria_snapshot = None
    if is_authenticated and user_id:
        try:
            aria_snapshot = load_colony_snapshot(user_id)
        except Exception as e:
            logger.warning(f"Failed to load ARIA snapshot: {e}")

    user_context = _build_aria_user_context(user_id, is_authenticated,
                                             data.get('page_context', {}), request.referrer)

    if data.get('stream', False):
        generator = handle_aria_chat_streaming(
            message, data.get('history', []), user_context,
            user_id, is_authenticated, aria_snapshot)
        return Response(
            stream_with_context(generator),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache, no-store, must-revalidate',
                     'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'}
        )

    result = handle_aria_chat_sync(message, data.get('history', []), user_context,
                                    user_id, is_authenticated, aria_snapshot)
    return jsonify(result)


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

@app.route('/api/expeditions/start', methods=['POST'])
@login_required
def api_expeditions_start():
    """Start expedition"""
    return jsonify(start_expedition_from_request(g.user_id, request.get_json(), session))

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
    data = request.get_json()
    discovery_item_id = data.get('discovery_item_id')
    extract_all = data.get('extract_all', True)
    quantity_to_extract = data.get('quantity_to_extract')  # Bug #1125: optional N for "Shard Some"

    if not discovery_item_id:
        return jsonify({'success': False, 'error': 'Missing discovery_item_id'})

    if quantity_to_extract is not None:
        try:
            quantity_to_extract = int(quantity_to_extract)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'quantity_to_extract must be an integer'})
        if quantity_to_extract < 1:
            return jsonify({'success': False, 'error': 'quantity_to_extract must be at least 1'})

    result = analyze_discovery(g.user_id, discovery_item_id, session, extract_all=extract_all, quantity_to_extract=quantity_to_extract)
    return jsonify(result)

@app.route('/api/discovery/shard_all', methods=['POST'])
@login_required
@handle_api_error
def api_shard_all_discoveries():
    """Bulk extract all common and uncommon discoveries (Shard It All)"""
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
    status = get_crew_mission_status(g.user_id)

    with db_cursor() as cur:
        cur.execute("""
            SELECT captain_logistics_xp, scientist_navigation_xp
            FROM pilgrim.users WHERE id = %s
        """, (g.user_id,))
        row = cur.fetchone()
        if row:
            logistics_xp = row.get('captain_logistics_xp') or 0
            nav_xp = row.get('scientist_navigation_xp') or 0
            # Captain: Base × (1 + logistics_xp/1000)
            status['captain']['stat_value'] = logistics_xp
            status['captain']['stat_multiplier'] = round(1.0 + (logistics_xp / 1000), 2)
            status['captain']['stat_desc'] = f"Logistics {logistics_xp} XP"
            # Scientist: Base × (1 + navigation_xp/1500)
            if status.get('scientist'):
                status['scientist']['stat_value'] = nav_xp
                status['scientist']['stat_multiplier'] = round(1.0 + (nav_xp / 1500), 2)
                status['scientist']['stat_desc'] = f"Navigation {nav_xp} XP"

    # ARIA: Base × (1 + resonance_level/100)
    aria_skills = get_aria_skills(g.user_id)
    resonance_level = aria_skills.get('resonance_level') or 1
    if status.get('aria'):
        status['aria']['stat_value'] = resonance_level
        status['aria']['stat_multiplier'] = round(1.0 + (resonance_level / 100), 2)
        status['aria']['stat_desc'] = f"Resonance Lv{resonance_level}"

    return jsonify({'success': True, **status})


@app.route('/api/crew/mission/nearby', methods=['GET'])
@login_required
def api_crew_mission_nearby():
    """Get ALL visited sites for trail building - no distance limit"""
    trails = get_visited_sites_for_trails(g.user_id)

    base_coords = None
    try:
        with db_cursor() as cur:
            cur.execute("SELECT home_mars_lat, home_mars_lon FROM pilgrim.users WHERE id = %s", (g.user_id,))
            user = cur.fetchone()
            if user and user['home_mars_lat']:
                base_coords = {'latitude': float(user['home_mars_lat']), 'longitude': float(user['home_mars_lon'])}
    except Exception:
        pass

    formatted = []
    for t in trails:
        formatted.append({
            'name': t['name'],
            'type': t['type'],
            'distance_km': round(float(t.get('distance_km') or 0), 1),
            'from_landmark': t.get('from_landmark', 'HOME'),
            'from_latitude': float(t['from_latitude']) if t.get('from_latitude') else None,
            'from_longitude': float(t['from_longitude']) if t.get('from_longitude') else None,
            'segment_distance_km': round(float(t.get('segment_distance_km') or 0), 1),
            'visit_count': t.get('visit_count', 0),
            'km_built': round(float(t.get('km_built') or 0), 3),
            'captain_km': round(float(t.get('captain_km') or 0), 3),
            'scientist_km': round(float(t.get('scientist_km') or 0), 3),
            'aria_km': round(float(t.get('aria_km') or 0), 3),
            'trip_count': t.get('trip_count', 0),
            'trail_level': t.get('trail_level', 'none'),
            'latitude': float(t['latitude']) if t.get('latitude') else None,
            'longitude': float(t['longitude']) if t.get('longitude') else None,
            'is_complete': bool(t.get('is_complete', False)),
        })

    return jsonify({'success': True, 'trails': formatted, 'base_coords': base_coords})



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
    data = request.json or {}
    destination = data.get('destination_name', '')

    if not destination:
        return jsonify({'success': False, 'error': 'No destination specified'})

    with db_cursor() as cur:
        cur.execute("""
            SELECT 1 FROM pilgrim.landmark_discoveries WHERE user_id = %s AND landmark_name = %s
        """, (g.user_id, destination))
        if not cur.fetchone():
            return jsonify({'success': False, 'error': 'Destination not discovered yet'})

    result = use_aria_resonance(g.user_id, destination)
    return jsonify(result)


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
    """
    Complete a trail building session and claim rewards (km built + XP).

    Request body:
    - worker_type: 'captain', 'scientist', or 'aria'
    """
    data = request.json or {}
    worker_type = data.get('worker_type', '').lower()

    if worker_type not in ('captain', 'scientist', 'aria'):
        return jsonify({'success': False, 'error': 'Invalid worker type'})

    status = get_crew_mission_status(g.user_id)
    member_status = status.get(worker_type) or {}

    if member_status.get('busy'):
        return jsonify({'success': False, 'error': f'{worker_type.title()} is still on mission'})
    if not member_status.get('complete') and not member_status.get('target'):
        return jsonify({'success': False, 'error': f'No mission to complete for {worker_type.title()}'})

    result = complete_crew_mission(g.user_id, worker_type)
    return jsonify(result)


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
    """
    Get user's Origin Site eligibility - which sites can they claim based on expedition proximity.
    Returns all 14 sites with distance info and can_claim flag.
    """
    sites = get_user_origin_site_eligibility(g.user_id)

    claimable = [s for s in sites if s['can_claim']]

    return jsonify({
        'success': True,
        'sites': sites,
        'claimable_count': len(claimable),
        'claimable_sites': claimable
    })


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
    """
    Get legendary item status for an Origin Site.
    Can be polled to check when Flux generation is complete.
    """
    item = get_origin_site_legendary_item(site_id)
    if not item:
        return jsonify({'success': False, 'error': 'Origin Site not found'})

    return jsonify({
        'success': True,
        'site_code': item['site_code'],
        'mission_name': item['mission_name'],
        'item_name': item['item_name'],
        'item_description': item['item_description'],
        'image_url': item['image_url'],
        'has_image': item['has_image'],
        'founder_name': item['founder_name'],
        'founder_wallet_prefix': item['founder_wallet_prefix']
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
    """
    Universal upgrade endpoint for all upgradeable items.
    Body: {"category": "vehicles", "item_key": "rover"}
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'})

    data = request.get_json()
    category = data.get('category')
    item_key = data.get('item_key')

    if not category or not item_key:
        return jsonify({'success': False, 'error': 'Missing category or item_key'})

    result = perform_upgrade(user_id, category, item_key)

    if result.get('success'):
        # Invalidate balance cache after purchase
        session.pop('_bal', None)
        session.modified = True

    return jsonify(result)


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
def cron_sync_balances():
    """
    Hourly blockchain balance sync - Updates all user wallet balances in DB.
    This allows page loads to use fast DB-cached balances instead of hitting blockchain.
    Triggered by App Engine cron.yaml every hour.
    """
    # Verify request is from App Engine cron (security check)
    if not request.headers.get('X-Appengine-Cron') and not app.debug:
        logger.warning("Cron endpoint called without X-Appengine-Cron header")
        return jsonify({'error': 'Forbidden'}), 403

    try:
        result = sync_all_wallet_balances()
        logger.info(f"✅ Balance sync completed: {result['updated']}/{result['total']} wallets updated")
        return jsonify({'success': True, **result})
    except Exception as e:
        logger.error(f"❌ Balance sync failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/cron/aria_test_email', methods=['GET'])
def cron_aria_test_email():
    """Hourly ARIA email - TEST ONLY, sends to andy.tillo@gmail.com."""
    result = handle_cron_aria_test_email(request.headers.get('X-Appengine-Cron'), app.debug)
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@app.route('/api/cron/generate_snapshots', methods=['GET'])
def cron_generate_snapshots():
    """Daily ARIA Photo Journal generation - kicked off in background thread."""
    if not request.headers.get('X-Appengine-Cron') and not app.debug:
        return jsonify({'error': 'Forbidden'}), 403
    start_background_snapshot_generation()
    return jsonify({'success': True, 'message': 'Snapshot generation started in background'})


@app.route('/api/cron/qa_bot', methods=['GET'])
def cron_qa_bot():
    """QA Bot - plays the game as user 250 (Trustable CC) to catch regressions."""
    if not request.headers.get('X-Appengine-Cron') and not app.debug:
        return jsonify({'error': 'Forbidden'}), 403
    try:
        from tools.qa_bot import run_bot_session
        result = run_bot_session()
        status_code = 200 if not result.get('errors') else 207
        return jsonify({'success': True, **result}), status_code
    except Exception as e:
        logger.error(f"QA Bot failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/cron/retry_bonds', methods=['GET'])
def cron_retry_bonds():
    """Safety net: retry stuck ARIA bonds that failed to create blockchain tx."""
    if not request.headers.get('X-Appengine-Cron') and not app.debug:
        return jsonify({'error': 'Forbidden'}), 403
    try:
        from utilities.aria.bonds import retry_stuck_bonds
        result = retry_stuck_bonds()
        return jsonify({'success': True, **result})
    except Exception as e:
        logger.error(f"Bond retry cron failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/cron/drone_trail_build', methods=['GET'])
def cron_drone_trail_build():
    """Passive trail building via Automation Drone upgrades. Runs every 30 min."""
    if not request.headers.get('X-Appengine-Cron') and not app.debug:
        return jsonify({'error': 'Forbidden'}), 403
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
    """Admin preview of the First Contact cinematic — uses bond #3 data without completing it."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not is_admin(real_user_id):
        return redirect(url_for('home'))

    from utilities.aria.bonds import _get_commander_name
    # Load bond #3 directly for preview
    with db_cursor() as cur:
        cur.execute("SELECT * FROM pilgrim.aria_bonds WHERE id = 3")
        bond = cur.fetchone()
    if not bond:
        return "No bond #3 found", 404

    captain_1 = _get_commander_name(bond['user_id_1']) or f"Captain {bond['user_id_1']}"
    captain_2 = _get_commander_name(bond['user_id_2']) or f"Captain {bond['user_id_2']}"

    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM pilgrim.aria_bonds WHERE id <= %s", (bond['id'],))
        bond_number = cur.fetchone()['count']
    from utilities.mars_environment_utils import get_mars_sol_number
    sol = get_mars_sol_number()

    from types import SimpleNamespace
    bond_obj = SimpleNamespace(**bond)

    return render_template('aria_first_contact.html',
                           bond=bond_obj, captain_1=captain_1, captain_2=captain_2,
                           bond_number=bond_number, sol=sol, static_v=STATIC_V)


@app.route('/api/aria-bond/complete', methods=['POST'])
@handle_api_error
def api_aria_bond_complete():
    """Complete ARIA bond from First Contact cinematic — marks bond as bonded, creates inventory."""
    if not auth.is_authenticated():
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    user_id = session.get('user_id')
    data = request.get_json() or {}
    bond_id = data.get('bond_id')
    if not bond_id:
        return jsonify({'success': False, 'error': 'Missing bond_id'})

    # Mark first_contact_shown for this user
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT user_id_1, user_id_2 FROM pilgrim.aria_bonds WHERE id = %s", (bond_id,))
        bond = cur.fetchone()
        if not bond:
            return jsonify({'success': False, 'error': 'Bond not found'})
        if user_id not in (bond['user_id_1'], bond['user_id_2']):
            return jsonify({'success': False, 'error': 'Unauthorized'})

        field = 'first_contact_shown_user_1' if user_id == bond['user_id_1'] else 'first_contact_shown_user_2'
        cur.execute(f"UPDATE pilgrim.aria_bonds SET {field} = TRUE WHERE id = %s", (bond_id,))

    # Complete the bond (marks bonded, creates inventory items)
    from utilities.aria.bonds import _complete_bond
    result = _complete_bond(bond_id)

    # Set session flag so before_request stops redirecting
    session['_fc_shown'] = True
    session.modified = True

    return jsonify(result)


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
    from utilities.postgres.core import db_cursor, get_pool_health, get_db_connection_stats
    import json
    with db_cursor() as cur:
        cur.execute("SELECT id, tested_by, results, slowest_page, slowest_time, all_ok, tested_at FROM speed_test_runs ORDER BY tested_at DESC LIMIT 30")
        history = cur.fetchall()
    for run in history:
        if isinstance(run['results'], str):
            run['results'] = json.loads(run['results'])
    latest = history[0] if history else None
    pool = get_pool_health()
    db_stats = get_db_connection_stats()
    return render_template('admin_speed.html', active_tab=None, user=auth.get_current_user(),
                          latest=latest, history=history, pool=pool, db_stats=db_stats)


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
    from utilities.postgres.bugs import upload_bug_screenshot, get_bug_by_id
    f = request.files.get('file')
    if not f:
        return jsonify({'success': False, 'error': 'No file provided'})
    # Fill first empty screenshot slot (supports up to 3)
    bug = get_bug_by_id(bug_id)
    if not bug or not bug.get('screenshot_url'):
        field = 'screenshot_url'
    elif not bug.get('screenshot_2_url'):
        field = 'screenshot_2_url'
    else:
        field = 'screenshot_3_url'
    url = upload_bug_screenshot(bug_id, f.read(), f.filename, f.content_type, field)
    return jsonify({'success': bool(url), 'url': url})


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
    real_user_id = session.get('_real_uid') or session.get('user_id')
    from utilities.pilgrimbot_utils import get_user_chats, get_user_role
    from utilities.pilgrimbot_context import build_prefill_context

    chats = get_user_chats(real_user_id) if real_user_id else []
    pb_role = session.get('_pb_role')
    if not pb_role:
        pb_role = get_user_role(real_user_id) if real_user_id else 'captain'
        session['_pb_role'] = pb_role

    brainstorm_page = request.args.get('brainstorm')
    bug_id = request.args.get('bug')
    combined_context, display_name, _bug, _bp = build_prefill_context(brainstorm_page, bug_id)

    return render_template('pilgrimbot.html', user=auth.get_current_user(),
        chats=chats, bug_context=combined_context, bug_id=bug_id, bug_name=display_name,
        pb_role=pb_role, brainstorm_page=brainstorm_page)


@app.route('/api/pilgrimbot/chat', methods=['POST'])
def api_pilgrimbot_chat():
    """Chat with PilgrimBot — streaming SSE response."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not session.get('_adm'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    data = request.get_json() or {}
    message = data.get('message', '').strip()
    if not message:
        return jsonify({'success': False, 'error': 'No message provided'})

    chat_id = data.get('chat_id')
    from utilities.pilgrimbot_utils import handle_chat_streaming, get_user_role
    bug_mode = bool(data.get('bug_mode'))
    # Cache user_role in session to avoid DB hit per message
    user_role = session.get('_pb_role')
    if not user_role:
        user_role = get_user_role(real_user_id)
        session['_pb_role'] = user_role

    # PilgrimBot actions — detect and execute before streaming
    from utilities.admin.pilgrimbot_actions import detect_and_execute_actions
    action_context = detect_and_execute_actions(message, chat_id, real_user_id, auth)

    image_url = data.get('image_url')
    generator = handle_chat_streaming(message, chat_id, real_user_id, bug_mode=bug_mode, action_context=action_context, user_role=user_role, image_url=image_url)
    return Response(
        stream_with_context(generator),
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
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not session.get('_adm'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    data = request.get_json() or {}
    response_text = data.get('response_text', '').strip()
    chat_id = data.get('chat_id', '')
    if not response_text and not chat_id:
        return jsonify({'success': False, 'error': 'No response text or chat_id'})
    from utilities.pilgrimbot_utils import create_bug_from_conversation, create_bug_from_response
    # If response_text provided, create bug from just that response (not full conversation)
    if response_text:
        return jsonify(create_bug_from_response(
            response_text, real_user_id, chat_id=chat_id,
            title_override=data.get('title', '').strip() or None,
            priority_override=data.get('priority', '').strip() or None
        ))
    return jsonify(create_bug_from_conversation(
        chat_id, real_user_id,
        title_override=data.get('title', '').strip() or None,
        priority_override=data.get('priority', '').strip() or None
    ))


@app.route('/api/pilgrimbot/upload', methods=['POST'])
def api_pilgrimbot_upload():
    """Upload a pasted screenshot for PilgrimBot chat. Returns GCS URL."""
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not real_user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 403
    f = request.files.get('image')
    if not f:
        return jsonify({'success': False, 'error': 'No image provided'})
    from google.cloud import storage as gcs_storage
    import time as _time
    try:
        ext = f.filename.rsplit('.', 1)[-1] if f.filename and '.' in f.filename else 'png'
        ts = int(_time.time())
        blob_name = f"pilgrimbot/chat_{real_user_id}_{ts}.{ext}"
        client = gcs_storage.Client(project="galactica-character-game")
        bucket = client.bucket("galactica-pilgrim-assets")
        blob = bucket.blob(blob_name)
        blob.cache_control = 'public, max-age=604800'
        blob.upload_from_string(f.read(), content_type=f.content_type or 'image/png', timeout=60)
        url = f"https://storage.googleapis.com/galactica-pilgrim-assets/{blob_name}"
        return jsonify({'success': True, 'url': url})
    except Exception as e:
        logger.error(f"PilgrimBot image upload failed: {e}")
        return jsonify({'success': False, 'error': 'Upload failed'})


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
    real_user_id = session.get('_real_uid') or session.get('user_id')
    if not session.get('_adm'):
        return jsonify({'success': False}), 403
    chat_id = request.args.get('chat_id', '')
    if not chat_id:
        return jsonify({'success': False, 'error': 'No chat_id'})
    from utilities.pilgrimbot_utils import get_chat_history
    messages = get_chat_history(real_user_id, chat_id, limit=100)
    return jsonify({'success': True, 'messages': messages})


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
