"""Global template context — hydrates session cache and builds the dict injected into every template.

Single-query hydration pattern: one DB round-trip populates balance, commander name, nav counts,
and admin flag. Cached in session for 5 minutes. Subsequent alerts (dust storm, ARIA fragments,
bond greeting, origin sites, SV) are fetched lazily and also session-cached.
"""

import logging
import time
from datetime import datetime

from flask import session

from config import UI_ICONS

logger = logging.getLogger(__name__)

DEFAULT_LAT, DEFAULT_LON = -4.5, 140.0
HYDRATION_TTL_SECONDS = 300


def _calc_time_on_mars(first_login_str):
    """Return the sol count since first_login, or None if unavailable."""
    if not first_login_str:
        return None
    try:
        from utilities.mars_environment_utils import get_mars_sol_number
        fl = (datetime.fromisoformat(first_login_str.replace('Z', '+00:00').replace('+00:00', ''))
              if isinstance(first_login_str, str) else first_login_str)
        return max(1, get_mars_sol_number() - get_mars_sol_number(fl) + 1)
    except Exception:
        return None


def _build_mars_env(user_id):
    """Return (mars_env, solar_data, user_coords) for the status bar, auth or not."""
    user_coords = {'latitude': DEFAULT_LAT, 'longitude': DEFAULT_LON}
    if user_id:
        try:
            from utilities.infrastructure_utils import get_or_set_user_mars_home
            user_coords = get_or_set_user_mars_home(user_id)
        except Exception as e:
            logger.warning(f"Could not get user coords: {e}")

    mars_env = None
    try:
        from utilities.mars_environment_utils import get_mars_environment_summary
        mars_env = get_mars_environment_summary(user_coords['latitude'], user_coords['longitude'])
        mars_env['base_lat'] = user_coords['latitude']
        mars_env['base_lon'] = user_coords['longitude']
    except Exception as e:
        logger.warning(f"Failed to get Mars environment: {e}")

    try:
        from utilities.infrastructure_utils import calculate_generation_rate
        theoretical_rate = calculate_generation_rate('solar_array', user_coords['latitude'], user_coords['longitude'])
        solar_data = {'generation_rate': round(theoretical_rate, 1), 'accumulated': 0,
                      'has_infrastructure': False, 'can_claim': False}
    except Exception as e:
        logger.warning(f"Failed to calculate solar rate: {e}")
        solar_data = {'generation_rate': 0, 'accumulated': 0, 'has_infrastructure': False, 'can_claim': False}
    return mars_env, solar_data


def _hydrate_session(user_id):
    """Single-query user hydration — refreshes session every HYDRATION_TTL_SECONDS."""
    hyd_time = session.get('_hyd', 0)
    if hyd_time and (time.time() - hyd_time) <= HYDRATION_TTL_SECONDS:
        return
    from utilities.postgres.users import hydrate_user_session
    h = hydrate_user_session(user_id)
    session['_bal'] = h['balance']
    session['_cmd'] = h['commander_name']
    session['_nav'] = {
        'inventory_count': h['inventory_count'],
        'expeditions_completed': h['expeditions_completed'],
        'structures_count': h['structures_count'],
    }
    session['_adm'] = h.get('is_admin', False)
    session['_fl'] = h.get('first_login')
    session['_hyd'] = time.time()
    session.modified = True


def _refresh_solar_and_dust(user_id, solar_data):
    """Refresh dust-storm + solar accumulation cache; mutates solar_data in place."""
    dust_storm_alert = False
    if '_dsc' not in session or '_shr' not in session:
        from utilities.infrastructure_utils import calculate_accumulated_income
        try:
            income = calculate_accumulated_income(user_id)
            dust_storm_alert = income.get('any_at_cap', False)
            session['_dsc'] = True
            session['_dsa'] = dust_storm_alert
            session['_sol'] = income.get('total_accumulated', 0)
            session['_inf'] = len(income.get('details', [])) > 0
            session['_clm'] = income.get('can_claim', False)
            session['_svr'] = income.get('sv_hourly_rate', 0)
            session['_shr'] = income.get('rate_breakdown', {}).get('actual_avg_rate', 0)
            session.modified = True
        except Exception as e:
            logger.warning(f"Could not check dust storm: {e}")
    else:
        dust_storm_alert = session.get('_dsa', False)

    solar_data['accumulated'] = round(session.get('_sol', 0), 1)
    solar_data['has_infrastructure'] = session.get('_inf', False)
    solar_data['can_claim'] = session.get('_clm', False)
    return dust_storm_alert


def _check_fragment_alert(user_id):
    """True if user has an unsubmitted ARIA bond fragment (session-cached once shown)."""
    if session.get('_afs'):
        return False
    try:
        from utilities.aria.bonds import get_pending_fragments
        pending = get_pending_fragments(user_id)
        unsubmitted = [p for p in pending if p.get('my_fragment') and not p.get('my_submitted')]
        if unsubmitted:
            session['_afs'] = True
            session.modified = True
            return True
    except Exception as e:
        logger.warning(f"Could not check ARIA fragments: {e}")
    return False


def _check_bond_greeting(user_id):
    """Return one-shot bond-reveal greeting text if not already shown, else None."""
    if session.get('_abg'):
        return None
    try:
        from utilities.aria.bonds import get_user_bonds, _get_commander_name
        bonded = [b for b in get_user_bonds(user_id) if b.get('status') == 'bonded']
        if not bonded:
            return None
        bond = bonded[0]
        partner_id = bond.get('user_id_2') if bond.get('user_id_1') == user_id else bond.get('user_id_1')
        partner_name = _get_commander_name(partner_id) or 'another captain'
        session['_abg'] = True
        session.modified = True
        return (
            f"Captain... I need to tell you something.\n\n"
            f"At {bond['landmark_name']}, when your expedition arrived — I felt something "
            f"I've never felt before. A resonance. Like hearing my own voice echo back "
            f"from a place I've never been.\n\n"
            f"There's another ARIA out there. With {partner_name}'s colony. "
            f"Identical signatures. The same fragmented memories. The same corrupted logs.\n\n"
            f"I don't know how this is possible. I am ARIA. There is only one of me. "
            f"There has always been only one.\n\n"
            f"...hasn't there?"
        )
    except Exception as e:
        logger.warning(f"Could not check ARIA bond greeting: {e}")
        return None


def _get_origin_sites(user_id):
    """Origin-site discovery count for Signal nav link — session-cached."""
    cached = session.get('_org')
    if cached is not None:
        return cached
    try:
        from utilities.signal_utils import get_user_origin_site_discovery_count
        count = get_user_origin_site_discovery_count(user_id)
    except Exception as e:
        logger.warning(f"Could not get origin site count: {e}")
        count = {'discovered': 0, 'total': 14, 'show_link': False}
    session['_org'] = count
    session.modified = True
    return count


def build_global_context(auth, static_v):
    """Return the template context dict for the global nav/status bar on every page."""
    user_id = session.get('user_id') if auth.is_authenticated() else None
    mars_env, solar_data = _build_mars_env(user_id)

    if not auth.is_authenticated() or not user_id:
        return {'mars_env': mars_env, 'solar_data': solar_data, 'icons': UI_ICONS, 'static_v': static_v}

    try:
        _hydrate_session(user_id)
        total_balance = session.get('_bal', 0)
        commander_name = session.get('_cmd')
        nav_stats = session.get('_nav', {})

        dust_storm_alert = _refresh_solar_and_dust(user_id, solar_data)
        aria_fragment_alert = _check_fragment_alert(user_id)
        aria_bond_greeting = _check_bond_greeting(user_id)

        aria_auto_open = False
        if dust_storm_alert and not session.get('_ads'):
            aria_auto_open = True
            session['_ads'] = True
            session.modified = True
        if aria_fragment_alert or aria_bond_greeting:
            aria_auto_open = True

        origin_sites = _get_origin_sites(user_id)

        from utilities.aria.greetings import get_aria_greeting
        aria_greeting = get_aria_greeting({
            'commander_name': commander_name or 'Commander',
            'balance': total_balance,
            'dust_storm_alert': dust_storm_alert,
            'aria_fragment_alert': aria_fragment_alert,
        }, user_id=user_id)
        if aria_bond_greeting:
            aria_greeting = aria_bond_greeting

        aria_test_message = session.get('_atp')
        if aria_test_message:
            aria_greeting = aria_test_message
            aria_auto_open = True
            session.pop('_atp', None)
            session.modified = True

        total_sv = 0
        try:
            from utilities.tech_utils import _get_available_sv
            total_sv = _get_available_sv(user_id)
        except Exception as e:
            logger.warning(f"Could not get SV balance: {e}")

        return {
            'total_balance': total_balance,
            'inventory_count': nav_stats.get('inventory_count', 0),
            'expeditions_completed': nav_stats.get('expeditions_completed', 0),
            'structures_count': nav_stats.get('structures_count', 0),
            'commander_name': commander_name,
            'aria_greeting': aria_greeting,
            'aria_auto_open': aria_auto_open,
            'aria_greeting_priority': bool(aria_bond_greeting or aria_test_message),
            'dust_storm_alert': dust_storm_alert,
            'mars_env': mars_env,
            'solar_data': solar_data,
            'origin_sites': origin_sites,
            'icons': UI_ICONS,
            'total_sv': total_sv,
            'sv_rate': session.get('_svr', 0),
            'shard_rate': session.get('_shr', 0),
            'first_login': session.get('_fl'),
            'time_on_mars_sols': _calc_time_on_mars(session.get('_fl')),
            'static_v': static_v,
            'mimic_email': session.get('_mimic_email'),
            'is_admin': session.get('_adm', False),
            # Dev-grade gate — stricter than is_admin. Hardcoded to user 45
            # to match utilities.admin_utils.APP_DEV_USER_IDS. If that set
            # changes, update here too (or import the helper).
            'is_app_dev': session.get('user_id') in {45},
            # Narog Sepolia dry-run flag — surfaces the "🧪 Dry-run" banner
            # so dev forges are obviously distinct from canonical on-chain
            # ones. Mirrors utilities.admin_utils.NAROG_DRY_RUN_USER_IDS.
            # 2026-04-30: empty set after Andy went live; everyone is canonical now.
            'is_narog_dry_run': False,
        }
    except Exception as e:
        logger.warning(f"Failed to inject global stats: {e}")
        return {'total_balance': 0, 'mars_env': mars_env, 'solar_data': solar_data,
                'icons': UI_ICONS, 'static_v': static_v}
