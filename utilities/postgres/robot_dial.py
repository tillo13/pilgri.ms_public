"""Narog dial → real, live game effects (#1492).

Luke's robot-crew brainstorm §4/§5 spec says the Narog's role dial is not
cosmetic — each slot drives a real bonus, and §5 pins the magnitude
("Robot impact on Depot Speed up is +10%", start low / tune up):

    exploration  → passive trail building   (already live, #1113 — segments.py)
    logistics    → Depot/equipment BUILD speed   (this module)
    research     → Tech RESEARCH speed           (this module)
    expeditions  → robot missions (locked: needs #1269 robot range — no effect yet)

Two responsibilities:

  1. get_robot_dial_multipliers() — exposes the dial as time multipliers so the
     existing effects funnel (get_user_upgrade_effects → build_time_mult, and
     tech research duration) picks them up for NEW builds/research. One funnel,
     no duplicated math — leans on the #1486 "one adjusted duration drives
     card/toast/countdown/completion" unification.

  2. recompute_in_progress_for_dial() — Luke #1492 explicitly wants moving the
     dial to shorten work ALREADY in progress ("10 hours left → 8 hours left").
     Build/research durations are frozen at start (post-#1486), so on a dial
     change we rescale ONLY the remaining portion of each in-progress item by
     the ratio new_mult/old_mult. Already-elapsed time stays spent — deterministic,
     fair, and it keeps the single-duration model #1486 established.

EFFECT MODEL (tunable — flagged for Luke at QA):
    effective = base_stat × (dial_pct / 100)          # matches the /crew "Active" readout
    time_mult = 1 − MAX_SPEEDUP × (effective / 100)    # 1.0 (no effect) … 0.90 (−10%) at effective 100
So max speed-up needs both a maxed Narog (base 100 @ Foundry L10) AND 100% dial —
mirroring how the exploration dial scales trail output with stage. Flat "+10% at
dial 100% regardless of Foundry" is a one-constant change if Luke prefers it.
"""

from utilities.postgres.core import db_cursor

# Tunable magnitudes (Luke §5: depot +10%, start low). Research matched to logistics.
LOGISTICS_MAX_SPEEDUP = 0.10   # build time at effective-100 logistics → ×0.90
RESEARCH_MAX_SPEEDUP = 0.10    # research time at effective-100 research → ×0.90


def _lab_level(user_id: int) -> int:
    """Narog Foundry (robotics_lab) level — the source of base stat (#1436)."""
    try:
        from utilities.upgrades_utils import get_all_infrastructure_levels
        return int((get_all_infrastructure_levels(user_id) or {}).get('robotics_lab', 0))
    except Exception:
        return 0


def _build_mult(dial: dict, base_stat: int) -> float:
    eff = base_stat * (int((dial or {}).get('logistics', 0) or 0) / 100.0)
    return 1.0 - LOGISTICS_MAX_SPEEDUP * (eff / 100.0)


def _research_mult(dial: dict, base_stat: int) -> float:
    eff = base_stat * (int((dial or {}).get('research', 0) or 0) / 100.0)
    return 1.0 - RESEARCH_MAX_SPEEDUP * (eff / 100.0)


def get_robot_dial_multipliers(user_id: int) -> dict:
    """Time multipliers (≤1.0 = faster) the dial currently grants. Identity
    {1.0, 1.0} unless the captain has a COMPLETE Narog — so callers can multiply
    unconditionally. Cheap: 1 robot read + 1 infra-levels read.
    """
    identity = {'build_time_mult': 1.0, 'research_time_mult': 1.0}
    try:
        from utilities.postgres.robot import get_robot, compute_robot_stat_value
        robot = get_robot(user_id)
        if not robot or robot.get('build_status') != 'complete':
            return identity
        base = compute_robot_stat_value(_lab_level(user_id))
        dial = robot.get('dial') or {}
        return {
            'build_time_mult': _build_mult(dial, base),
            'research_time_mult': _research_mult(dial, base),
        }
    except Exception:
        return identity


def recompute_in_progress_for_dial(user_id: int, old_dial: dict, new_dial: dict) -> dict:
    """On a dial change, rescale the REMAINING time of in-progress work so the
    new allocation applies live (#1492). Build ratio hits infra builds +
    equipment upgrades; research ratio hits tech research. Set-based SQL — no
    per-row loop. No-op (and cheap) when the relevant slot didn't move.
    Returns counts of rows touched (for logging/tests).
    """
    touched = {'infra': 0, 'upgrades': 0, 'techs': 0}
    try:
        from utilities.postgres.robot import compute_robot_stat_value
        base = compute_robot_stat_value(_lab_level(user_id))
        # Ratio of new→old time multiplier; base cancels but is needed for the curve.
        b_old, b_new = _build_mult(old_dial, base), _build_mult(new_dial, base)
        r_old, r_new = _research_mult(old_dial, base), _research_mult(new_dial, base)
        build_ratio = (b_new / b_old) if b_old else 1.0
        research_ratio = (r_new / r_old) if r_old else 1.0

        with db_cursor(commit=True) as cur:
            if abs(build_ratio - 1.0) > 1e-9:
                # colony_infrastructure: duration model (rescale remaining, keep elapsed spent)
                cur.execute("""
                    UPDATE pilgrim.colony_infrastructure c
                    SET build_duration_seconds = nd.new_dur,
                        ready_at = c.build_started_at + make_interval(secs => nd.new_dur),
                        updated_at = NOW()
                    FROM (
                        SELECT id, GREATEST(60, e + (build_duration_seconds - e) * %(r)s) AS new_dur
                        FROM (
                            SELECT id, build_duration_seconds,
                                   EXTRACT(EPOCH FROM (NOW() - build_started_at)) AS e
                            FROM pilgrim.colony_infrastructure
                            WHERE user_id = %(uid)s AND status = 'building'
                        ) x
                    ) nd
                    WHERE c.id = nd.id
                """, {'uid': user_id, 'r': build_ratio})
                touched['infra'] = cur.rowcount or 0

                # player_upgrades: deadline model (only ready_at; rescale time left)
                cur.execute("""
                    UPDATE pilgrim.player_upgrades
                    SET ready_at = NOW() + make_interval(
                        secs => GREATEST(0, EXTRACT(EPOCH FROM (ready_at - NOW())) * %(r)s))
                    WHERE user_id = %(uid)s AND pending_level IS NOT NULL AND ready_at > NOW()
                """, {'uid': user_id, 'r': build_ratio})
                touched['upgrades'] = cur.rowcount or 0

            if abs(research_ratio - 1.0) > 1e-9:
                # player_techs: duration model, no ready_at column
                cur.execute("""
                    UPDATE pilgrim.player_techs t
                    SET research_duration_seconds = nd.new_dur
                    FROM (
                        SELECT user_id, branch, tech_key, branch_level,
                               GREATEST(60, e + (research_duration_seconds - e) * %(r)s) AS new_dur
                        FROM (
                            SELECT user_id, branch, tech_key, branch_level, research_duration_seconds,
                                   EXTRACT(EPOCH FROM (NOW() - research_started_at)) AS e
                            FROM pilgrim.player_techs
                            WHERE user_id = %(uid)s AND status = 'researching'
                        ) x
                    ) nd
                    WHERE t.user_id = nd.user_id AND t.branch = nd.branch
                      AND t.tech_key = nd.tech_key AND t.branch_level = nd.branch_level
                """, {'uid': user_id, 'r': research_ratio})
                touched['techs'] = cur.rowcount or 0
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"recompute_in_progress_for_dial failed for {user_id}: {e}")
    return touched
