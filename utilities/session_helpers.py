"""Session cache invalidation helpers.

Single source of truth for clearing cached session data after
state-changing operations. Replaces duplicates that existed
across depot_utils, app.py, signal_utils, and tech_utils.
"""


def invalidate_balance_cache(session):
    """Clear cached balance after a transaction (purchase, claim, transfer)."""
    session.pop('_bal', None)
    session.pop('_hyd', None)
    session.modified = True


def invalidate_nav_stats_cache(session):
    """Clear cached nav stats when inventory/expeditions/structures change."""
    session.pop('_nav', None)
    session.pop('_hyd', None)
    session.modified = True


def invalidate_commander_cache(session):
    """Clear cached commander name when commander changes."""
    session.pop('_cmd', None)
    session.pop('_hyd', None)
    session.modified = True


def invalidate_dust_storm_cache(session):
    """Clear dust storm cache when claiming income or building structures."""
    session.pop('_dsc', None)
    session.pop('_dsa', None)
    session.pop('_ads', None)
    session.modified = True


def invalidate_all_caches(session):
    """Clear ALL session caches. Forces complete re-hydration on next page load."""
    session.pop('_bal', None)
    session.pop('_nav', None)
    session.pop('_cmd', None)
    session.pop('_dsc', None)
    session.pop('_dsa', None)
    session.pop('_ads', None)
    session.pop('_hyd', None)
    session.modified = True


def update_session_balance(session, new_balance_display):
    """Update the cached balance in session after a known transaction."""
    session['_bal'] = new_balance_display
    session.modified = True
