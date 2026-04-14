"""
Expedition pricing engine: cost calculation, narrative, and landmark sorting.

Pure logic. Reads tuning values from config.py, terrain lookup from terrain.py.
No DB writes; `sort_landmarks_by_cost` does a lazy read of user upgrade effects.
"""

from typing import Dict, List

from utilities.expeditions.config import (
    BASE_SPEED_KM_PER_HOUR,
    EVA_HOURS_PER_DAY,
    BASE_COST_PER_KM,
)
from utilities.expeditions.terrain import get_terrain_info


def calculate_expedition_cost(
    distance_km: float,
    destination_type: str,
    commander_stats: dict,
    user_expeditions_completed: int = 0,
    base_coords: dict = None,
    upgrade_effects: dict = None,
    is_return_visit: bool = False,
    scientist_nav_mult: float = 1.0,
    trail_speed_mult: float = 1.0,
    vehicle_type: str = None,
) -> dict:
    """
    Expedition cost + travel time.

    Streamlined formula (vehicles, no life support as base cost):
    - Distance → base cost
    - Terrain affects both speed and cost
    - Vehicle efficiency, logistics, strategy, charisma, and experience all reduce cost
    - Return visits: -30% cost, -50% travel time
    """
    if upgrade_effects is None:
        upgrade_effects = {}

    vehicle_speed_mult = upgrade_effects.get('expedition_speed_mult', 1.25)
    vehicle_cost_mult = upgrade_effects.get('fuel_cost_mult', 1.0)

    terrain_info = get_terrain_info(destination_type)
    terrain_speed_mult = terrain_info.get('speed_mult', 1.0)
    terrain_cost_mult = terrain_info.get('cost_mult', 1.0)
    terrain_reason = terrain_info['reason']

    # Drones fly — terrain doesn't slow them (but still affects cost for landing/takeoff)
    if vehicle_type == 'drone':
        terrain_speed_mult = 1.0
        terrain_reason = 'Aerial (no terrain impact)'

    if distance_km < 50:
        distance_tier, distance_desc = "Short Range", "Local reconnaissance"
    elif distance_km < 200:
        distance_tier, distance_desc = "Medium Range", "Extended surface mission"
    elif distance_km < 500:
        distance_tier, distance_desc = "Long Range", "Major expedition"
    else:
        distance_tier, distance_desc = "Epic Expedition", "Unprecedented journey"

    logistics = commander_stats.get('logistics', 50)
    strategy = commander_stats.get('strategy', 50)

    # === TRAVEL TIME ===
    logistics_speed_bonus = 1.0 + (logistics / 100.0)  # 1.0–2.0×
    total_speed_mult = (
        vehicle_speed_mult * logistics_speed_bonus * scientist_nav_mult
        * trail_speed_mult * terrain_speed_mult
    )
    effective_speed = BASE_SPEED_KM_PER_HOUR * total_speed_mult
    travel_hours = distance_km / effective_speed
    travel_days = travel_hours / EVA_HOURS_PER_DAY

    if is_return_visit:
        travel_days *= 0.5
        travel_hours *= 0.5

    # === COST ===
    base_cost = distance_km * BASE_COST_PER_KM

    after_terrain = base_cost * terrain_cost_mult
    terrain_cost_added = after_terrain - base_cost

    after_vehicle = after_terrain * vehicle_cost_mult
    vehicle_savings = after_terrain - after_vehicle

    # Logistics: 0-100 → 0-30% cost reduction
    logistics_efficiency = max(0.7, 1.0 - (logistics / 333.0))
    after_logistics = after_vehicle * logistics_efficiency
    logistics_savings = after_vehicle - after_logistics
    logistics_savings_pct = (1.0 - logistics_efficiency) * 100

    # Strategy: refund up to 25% of terrain surcharge
    strategy_efficiency = min(0.25, strategy / 400.0)
    strategy_refund = terrain_cost_added * strategy_efficiency
    after_strategy = after_logistics - strategy_refund
    strategy_savings_pct = strategy_efficiency * 100

    # Charisma: 0-100 → 0-20% cost reduction
    charisma = commander_stats.get('charisma', 50)
    charisma_efficiency = max(0.8, 1.0 - (charisma / 500.0))
    after_charisma = after_strategy * charisma_efficiency
    charisma_savings = after_strategy - after_charisma
    charisma_savings_pct = (1.0 - charisma_efficiency) * 100

    # Experience: 2% per completed expedition, capped at 50%
    experience_discount = min(0.5, user_expeditions_completed * 0.02)
    after_experience = after_charisma * (1.0 - experience_discount)
    experience_savings = after_charisma - after_experience

    # Life-support upgrades
    life_support_mult = upgrade_effects.get('life_support_cost_mult', 1.0)
    after_life_support = after_experience * life_support_mult
    life_support_savings = after_experience - after_life_support
    life_support_discount_pct = (1.0 - life_support_mult) * 100

    if is_return_visit:
        final_cost = after_life_support * 0.7
        return_savings = after_life_support * 0.3
    else:
        final_cost = after_life_support
        return_savings = 0

    narrative = generate_expedition_narrative(
        distance_km=distance_km,
        travel_days=travel_days,
        distance_tier=distance_tier,
        distance_desc=distance_desc,
        terrain_reason=terrain_reason,
        commander_stats=commander_stats,
        user_expeditions_completed=user_expeditions_completed,
        logistics_savings_pct=logistics_savings_pct,
        strategy_savings_pct=strategy_savings_pct,
        total_speed_mult=total_speed_mult,
        is_return_visit=is_return_visit,
    )

    return {
        'base_cost': round(base_cost, 1),
        'terrain_cost': round(terrain_cost_added, 1),
        'terrain_multiplier': terrain_cost_mult,
        'terrain_speed_mult': terrain_speed_mult,
        'terrain_reason': terrain_reason,
        'vehicle_savings': round(vehicle_savings, 1),
        'vehicle_cost_mult': vehicle_cost_mult,
        'logistics_savings': round(logistics_savings, 1),
        'logistics_efficiency_pct': round(logistics_savings_pct, 1),
        'strategy_savings': round(strategy_refund, 1),
        'strategy_savings_pct': round(strategy_savings_pct, 1),
        'charisma_savings': round(charisma_savings, 1),
        'charisma_savings_pct': round(charisma_savings_pct, 1),
        'experience_savings': round(experience_savings, 1),
        'experience_discount_pct': round(experience_discount * 100, 1),
        'life_support_savings': round(life_support_savings, 1),
        'life_support_discount_pct': round(life_support_discount_pct, 1),
        'life_support_mult': life_support_mult,
        'return_savings': round(return_savings, 1),
        'is_return_visit': is_return_visit,
        'base_expedition_cost': round(final_cost, 1),

        'travel_days': round(travel_days, 1),
        'travel_hours': round(travel_hours, 1),
        'round_trip_days': round(travel_days * 2, 1),
        'round_trip_hours': round(travel_hours * 2, 1),
        'effective_speed_kmh': round(effective_speed, 1),
        'logistics_speed_multiplier': round(total_speed_mult, 2),
        'vehicle_speed_mult': vehicle_speed_mult,

        'distance_tier': distance_tier,
        'distance_desc': distance_desc,

        'logistics_skill': logistics,
        'strategy_skill': strategy,
        'expeditions_completed': user_expeditions_completed,

        'narrative': narrative,

        # Backward-compat keys
        'base_fuel_cost': round(base_cost, 1),
        'rover_speed_bonus': vehicle_speed_mult,
    }


def generate_expedition_narrative(
    distance_km: float,
    travel_days: float,
    distance_tier: str,
    distance_desc: str,
    terrain_reason: str,
    commander_stats: dict,
    user_expeditions_completed: int,
    logistics_savings_pct: float,
    strategy_savings_pct: float,
    total_speed_mult: float,
    is_return_visit: bool = False,
) -> str:
    """Narrative explanation of an expedition's cost/speed breakdown."""
    parts = []

    if travel_days < 1:
        time_desc = f"{travel_days * EVA_HOURS_PER_DAY:.1f} hours"
    else:
        time_desc = f"{travel_days:.1f} days"

    if is_return_visit:
        parts.append("Return expedition to mapped territory.")

    parts.append(f"{distance_tier}: {distance_desc} spanning {distance_km:.0f} km.")
    parts.append(f"Estimated travel: {time_desc} round-trip at {total_speed_mult:.1f}× speed.")
    parts.append(terrain_reason + ".")

    effects = []
    if logistics_savings_pct > 5:
        effects.append(f"Logistics ({commander_stats['logistics']}): -{logistics_savings_pct:.0f}% cost")
    if strategy_savings_pct > 5:
        effects.append(f"Strategy ({commander_stats['strategy']}): terrain penalty reduced")
    if user_expeditions_completed >= 5:
        effects.append(f"Experience: -{min(50, user_expeditions_completed * 2)}% veteran discount")
    if is_return_visit:
        effects.append("Return visit: -30% cost, -50% travel time")

    if effects:
        parts.append("Bonuses: " + ", ".join(effects) + ".")

    if user_expeditions_completed >= 15:
        parts.append(f"Veteran expedition protocols active ({user_expeditions_completed} missions completed).")
    elif user_expeditions_completed >= 5:
        parts.append(f"Experience from {user_expeditions_completed} prior missions improves planning efficiency.")

    return " ".join(parts)


def sort_landmarks_by_cost(
    landmarks: List[Dict],
    commander_stats: dict,
    user_expeditions_completed: int,
    base_coords: dict,
    user_id: int = None,
) -> List[Dict]:
    """Enrich each landmark with its expedition pricing, sort cheapest-first."""
    safe_stats = {
        'leadership': commander_stats.get('leadership') or 50,
        'strategy': commander_stats.get('strategy') or 50,
        'exploration': commander_stats.get('exploration') or 50,
        'logistics': commander_stats.get('logistics') or 50,
        'charisma': commander_stats.get('charisma') or 50,
    }

    upgrade_effects = None
    if user_id:
        try:
            from utilities.upgrades_utils import get_user_upgrade_effects
            upgrade_effects = get_user_upgrade_effects(user_id)
        except ImportError:
            pass

    enriched = []
    for landmark in landmarks:
        is_return = landmark.get('visit_count', 0) > 0
        pricing = calculate_expedition_cost(
            distance_km=landmark['distance_km'],
            destination_type=landmark['type'],
            commander_stats=safe_stats,
            user_expeditions_completed=user_expeditions_completed,
            base_coords=base_coords,
            upgrade_effects=upgrade_effects,
            is_return_visit=is_return,
        )
        landmark['calculated_cost'] = pricing['base_expedition_cost']
        landmark['travel_hours_actual'] = pricing['travel_hours']
        landmark['travel_days'] = pricing['travel_days']
        landmark['speed_multiplier'] = pricing['logistics_speed_multiplier']
        landmark['is_return_visit'] = is_return
        landmark['expedition_pricing'] = pricing
        enriched.append(landmark)

    enriched.sort(key=lambda x: x['calculated_cost'])
    return enriched
