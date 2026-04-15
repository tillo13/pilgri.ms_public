"""Mars environment + daylight + generation rate math."""
import math
from datetime import datetime

from config_infrastructure import INFRASTRUCTURE_CATALOG

# Mars sol duration in Earth hours (24h 37m 22s)
MARS_SOL_HOURS = 24.6228

# ============================================================================
# DUST STORM / ACCUMULATION CAP SETTINGS
# Matches idle discoveries 7-day cap for consistency
# ============================================================================
ACCUMULATION_CAP_HOURS = 24 * 7  # 7 days = 168 hours max accumulation
DUST_STORM_MESSAGE = "A Martian dust storm has coated your solar arrays. Claim your accumulated shards and clean the panels to resume generation."


def calculate_daylight_fraction(hours_elapsed: float, longitude: float) -> tuple[float, float]:
    """
    Calculate what fraction of elapsed time was during Mars daylight vs night.
    Uses simplified model: Mars has ~12.3 hour days and ~12.3 hour nights.
    Longitude determines current time of day on Mars.

    Returns: (day_fraction, night_fraction) that sum to 1.0
    """
    hours_since_epoch = (datetime.utcnow() - datetime(2000, 1, 1)).total_seconds() / 3600
    mars_local_time = (hours_since_epoch / MARS_SOL_HOURS * 24 + longitude / 15) % MARS_SOL_HOURS
    day_start = MARS_SOL_HOURS * 0.25
    day_end = MARS_SOL_HOURS * 0.75
    full_sols = hours_elapsed / MARS_SOL_HOURS

    if full_sols >= 1.0:
        return 0.5, 0.5
    else:
        if day_start <= mars_local_time <= day_end:
            day_fraction = 0.6 + (0.4 * (1.0 - full_sols))
        else:
            day_fraction = 0.4 * (1.0 - full_sols)
        return day_fraction, 1.0 - day_fraction


def _get_mars_environment_multiplier(latitude: float) -> float:
    """Get Mars environment multiplier for solar shard generation."""
    factors = _get_mars_environment_factors(latitude)
    return round(factors['dust'] * factors['temperature'], 3)


def _get_mars_environment_factors(latitude: float) -> dict:
    """Get individual Mars environment factors for UI breakdown."""
    from utilities.mars_environment_utils import get_mars_environment
    env = get_mars_environment(base_lat=latitude)
    dust_factor = env['dust']['solar_efficiency'] / 100.0
    temp = env['temperature']['current']
    temp_factor = 1.0 + (temp + 60) / 500.0
    lat_factor = math.cos(math.radians(abs(latitude)))
    return {
        'dust': round(dust_factor, 3),
        'temperature': round(temp_factor, 3),
        'latitude': round(lat_factor, 3),
        'dust_condition': env['dust']['condition'],
        'temp_celsius': env['temperature']['current'],
        'combined': round(min(1.0, dust_factor * temp_factor), 3),
    }


def calculate_generation_rate(structure_type, latitude, longitude, level: int = 1):
    """Calculate resource generation rate based on structure type, location, and level."""
    definition = INFRASTRUCTURE_CATALOG.get(structure_type, {})
    level_data = definition.get('levels', {}).get(level, {})
    catalog_rate = float(level_data.get('generation_rate', 0.0))

    if structure_type == 'solar_array':
        lat_radians = math.radians(abs(latitude))
        latitude_factor = math.cos(lat_radians)
        base_rate = 10.0 * latitude_factor
        level_mult = catalog_rate / 10.0 if catalog_rate > 0 else 1.0
        return round(base_rate * level_mult, 2)

    return catalog_rate
