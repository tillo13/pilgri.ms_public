"""
Mars Environment Utilities - Scientifically Accurate Mars Conditions

Calculates realistic Mars environmental data based on:
- Mars orbital mechanics (687-day year)
- Seasonal variations (25° axial tilt)
- Diurnal temperature swings
- User's base latitude

This provides immersive, varying data without needing external APIs.
All calculations based on real Mars science from NASA/JPL data.
"""

import math
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Mars Constants (from NASA/JPL)
MARS_YEAR_DAYS = 686.97  # Earth days per Mars year
MARS_SOL_HOURS = 24.6597  # Hours per Mars sol
MARS_AXIAL_TILT = 25.19  # degrees
MARS_GRAVITY = 0.376  # Earth g

# Temperature ranges by latitude (Celsius) - based on Mars Global Surveyor data
# Format: (equatorial_min, equatorial_max, polar_adjustment)
TEMP_SUMMER = (-70, -10, -30)  # Summer day temps
TEMP_WINTER = (-110, -30, -40)  # Winter day temps
TEMP_NIGHT_DROP = 60  # Night is ~60°C colder

# Pressure at different elevations (Pa) - Mars avg is ~636 Pa
BASE_PRESSURE_PA = 636
PRESSURE_VARIATION = 100  # Seasonal variation

# Atmospheric opacity conditions
OPACITY_CONDITIONS = [
    (0.0, 0.3, "Clear", 98),
    (0.3, 0.6, "Hazy", 85),
    (0.6, 1.0, "Dusty", 70),
    (1.0, 2.0, "Dust Storm", 45),
    (2.0, 10.0, "Severe Storm", 20),
]


def get_mars_sol_number(reference_date: datetime = None) -> int:
    """
    Calculate game Sol number — days since the first captain landed on Mars.

    Sol 1 = October 4, 2025 (game launch). Uses real Mars Sol Date
    math internally, then offsets so the game epoch starts at Sol 1.
    """
    # MSD offset so Oct 4, 2025 = Sol 1 (was Oct 3, updated per Luke #4)
    GAME_EPOCH_MSD = 53946

    if reference_date is None:
        reference_date = datetime.utcnow()

    # Julian Date calculation
    year = reference_date.year
    month = reference_date.month
    day = reference_date.day + reference_date.hour/24 + reference_date.minute/1440

    if month <= 2:
        year -= 1
        month += 12

    A = int(year / 100)
    B = 2 - A + int(A / 4)
    JD = int(365.25 * (year + 4716)) + int(30.6001 * (month + 1)) + day + B - 1524.5

    # Mars Sol Date (MSD)
    MSD = (JD - 2451549.5) / 1.02749125 + 44796.0

    # Return game-epoch sol (Sol 1 = first landing)
    return max(1, int(MSD) - GAME_EPOCH_MSD)


def get_mars_season(sol_of_year: int) -> dict:
    """
    Determine Mars season based on solar longitude (Ls).

    Ls 0° = Northern spring equinox
    Ls 90° = Northern summer solstice
    Ls 180° = Northern autumn equinox
    Ls 270° = Northern winter solstice
    """
    # Convert sol of year to Ls (approximate)
    ls = (sol_of_year / 668.6) * 360  # 668.6 sols per Mars year
    ls = ls % 360

    if 0 <= ls < 90:
        season = "Northern Spring"
        season_progress = ls / 90
    elif 90 <= ls < 180:
        season = "Northern Summer"
        season_progress = (ls - 90) / 90
    elif 180 <= ls < 270:
        season = "Northern Autumn"
        season_progress = (ls - 180) / 90
    else:
        season = "Northern Winter"
        season_progress = (ls - 270) / 90

    return {
        'season': season,
        'ls': round(ls, 1),
        'progress': round(season_progress * 100),
    }


def get_sol_time(reference_date: datetime = None) -> dict:
    """
    Calculate current time of sol (Mars day/night cycle).

    Returns position in the 24h 37m sol cycle.
    """
    if reference_date is None:
        reference_date = datetime.utcnow()

    # Milliseconds since midnight UTC
    ms_today = (reference_date.hour * 3600 + reference_date.minute * 60 + reference_date.second) * 1000

    # Mars sol is 24h 37m = 88620 seconds = 88620000 ms
    sol_length_ms = 88620000

    # Position in sol (0-1)
    sol_position = (ms_today % sol_length_ms) / sol_length_ms

    # Determine time of day
    if sol_position < 0.25:
        time_of_day = "Dawn"
        icon = "🌅"
    elif sol_position < 0.5:
        time_of_day = "Day"
        icon = "☀️"
    elif sol_position < 0.75:
        time_of_day = "Dusk"
        icon = "🌆"
    else:
        time_of_day = "Night"
        icon = "🌙"

    # Calculate sol hours (0-24.6)
    sol_hours = sol_position * MARS_SOL_HOURS
    hours = int(sol_hours)
    minutes = int((sol_hours - hours) * 60)

    return {
        'time_of_day': time_of_day,
        'icon': icon,
        'sol_time': f"{hours:02d}:{minutes:02d}",
        'position': round(sol_position, 3),
        'is_night': sol_position >= 0.75 or sol_position < 0.25,
    }


def calculate_temperature(base_lat: float, season_ls: float, sol_position: float) -> dict:
    """
    Calculate Mars surface temperature based on location, season, and time.

    Based on Mars Global Surveyor and Curiosity data.
    """
    # Seasonal factor (0 = winter, 1 = summer for northern hemisphere)
    # Ls 90 = summer solstice, Ls 270 = winter solstice
    if base_lat >= 0:  # Northern hemisphere
        seasonal_factor = math.cos(math.radians(season_ls - 90)) * 0.5 + 0.5
    else:  # Southern hemisphere (opposite)
        seasonal_factor = math.cos(math.radians(season_ls + 90)) * 0.5 + 0.5

    # Latitude factor (equator warmer than poles)
    lat_factor = math.cos(math.radians(abs(base_lat)))

    # Base temperatures for season
    summer_range = (TEMP_SUMMER[0] + lat_factor * 20, TEMP_SUMMER[1] + lat_factor * 15)
    winter_range = (TEMP_WINTER[0] + lat_factor * 15, TEMP_WINTER[1] + lat_factor * 10)

    # Interpolate between winter and summer
    min_temp = winter_range[0] + seasonal_factor * (summer_range[0] - winter_range[0])
    max_temp = winter_range[1] + seasonal_factor * (summer_range[1] - winter_range[1])

    # Diurnal variation (day/night)
    # Peak temp at sol_position ~0.4 (early afternoon)
    # Min temp at sol_position ~0.9 (late night)
    diurnal_factor = math.sin((sol_position - 0.15) * math.pi * 2) * 0.5 + 0.5
    current_temp = min_temp + diurnal_factor * (max_temp - min_temp)

    return {
        'current': round(current_temp),
        'min': round(min_temp),
        'max': round(max_temp),
        'unit': 'C',
    }


def calculate_pressure(season_ls: float) -> dict:
    """
    Calculate atmospheric pressure based on season.

    Mars pressure varies ~25% seasonally as CO2 sublimates/deposits at poles.
    """
    # Pressure peaks around Ls 250, minimum around Ls 150
    pressure_factor = math.cos(math.radians(season_ls - 250)) * 0.125 + 1.0
    pressure = BASE_PRESSURE_PA * pressure_factor

    return {
        'value': round(pressure),
        'unit': 'Pa',
        'earth_percent': round((pressure / 101325) * 100, 2),
    }


def calculate_dust_opacity(season_ls: float) -> dict:
    """
    Calculate atmospheric dust opacity based on season.

    Dust storm season is typically Ls 180-330 (southern spring/summer).
    """
    # Base opacity
    base_opacity = 0.2

    # Dust storm season factor (peaks around Ls 250)
    if 180 <= season_ls <= 330:
        dust_factor = math.sin(math.radians((season_ls - 180) * (180/150))) * 0.5
    else:
        dust_factor = 0

    # Add some randomness based on sol (deterministic but varying)
    sol = get_mars_sol_number()
    pseudo_random = (math.sin(sol * 0.1) * 0.5 + 0.5) * 0.3

    opacity = base_opacity + dust_factor + pseudo_random

    # Determine condition
    for min_op, max_op, condition, efficiency in OPACITY_CONDITIONS:
        if min_op <= opacity < max_op:
            return {
                'value': round(opacity, 2),
                'condition': condition,
                'solar_efficiency': efficiency,
            }

    return {'value': round(opacity, 2), 'condition': 'Clear', 'solar_efficiency': 98}


def get_mars_environment(base_lat: float = -4.43, base_lon: float = 139.91) -> dict:
    """
    Get complete Mars environmental conditions for a base location.

    Default coordinates are Gale Crater (Curiosity's location).

    Returns comprehensive Mars environmental data.
    """
    now = datetime.utcnow()

    # Calculate current sol
    sol = get_mars_sol_number(now)
    sol_of_year = sol % 669  # Approximate sols per Mars year

    # Get season info
    season_info = get_mars_season(sol_of_year)

    # Get sol time
    sol_time = get_sol_time(now)

    # Calculate temperature
    temp = calculate_temperature(base_lat, season_info['ls'], sol_time['position'])

    # Calculate pressure
    pressure = calculate_pressure(season_info['ls'])

    # Calculate dust/opacity
    dust = calculate_dust_opacity(season_info['ls'])

    return {
        'sol': sol,
        'sol_of_year': sol_of_year,
        'season': season_info,
        'time': sol_time,
        'temperature': temp,
        'pressure': pressure,
        'dust': dust,
        'gravity': MARS_GRAVITY,
        'base_coords': {'lat': base_lat, 'lon': base_lon},
        'generated_at': now.isoformat(),
    }


def get_mars_environment_summary(base_lat: float = -4.43, base_lon: float = 139.91) -> dict:
    """
    Get a simplified summary for UI display.
    """
    env = get_mars_environment(base_lat, base_lon)

    # Calculate real MSD for display
    now = datetime.utcnow()
    year = now.year
    month = now.month
    day_frac = now.day + now.hour/24 + now.minute/1440
    if month <= 2:
        year -= 1
        month += 12
    A = int(year / 100)
    B = 2 - A + int(A / 4)
    JD = int(365.25 * (year + 4716)) + int(30.6001 * (month + 1)) + day_frac + B - 1524.5
    real_msd = int((JD - 2451549.5) / 1.02749125 + 44796.0)

    return {
        'sol': env['sol'],
        'real_msd': real_msd,
        'time_of_day': env['time']['time_of_day'],
        'time_icon': env['time']['icon'],
        'sol_time': env['time']['sol_time'],
        'temperature': env['temperature']['current'],
        'temp_unit': 'C',
        'pressure': env['pressure']['value'],
        'pressure_earth_pct': env['pressure']['earth_percent'],
        'condition': env['dust']['condition'],
        'solar_efficiency': env['dust']['solar_efficiency'],
        'season': env['season']['season'],
        'ls': env['season']['ls'],  # Solar longitude (Ls) - orbital position
        'dust_opacity': env['dust']['value'],  # Atmospheric dust opacity
        'gravity': f"{env['gravity']}g",
    }
