"""Canonical Mars distance and coordinate calculations.

Single source of truth for haversine distance, coordinate offsets,
and Mars constants. Replaces duplicates that existed in postgres_utils,
expedition_utils, and signal_utils.
"""
import math

MARS_RADIUS_KM = 3396


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great circle distance between two points on Mars in km."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return MARS_RADIUS_KM * c


# Alias for backward compatibility with postgres_utils callers
calculate_mars_distance = haversine_distance


def offset_coordinates(lat: float, lon: float, distance_km: float, bearing_deg: float) -> tuple:
    """Offset coordinates by distance in a given direction on Mars."""
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    bearing_rad = math.radians(bearing_deg)
    angular_distance = distance_km / MARS_RADIUS_KM

    new_lat = math.asin(
        math.sin(lat_rad) * math.cos(angular_distance) +
        math.cos(lat_rad) * math.sin(angular_distance) * math.cos(bearing_rad)
    )
    new_lon = lon_rad + math.atan2(
        math.sin(bearing_rad) * math.sin(angular_distance) * math.cos(lat_rad),
        math.cos(angular_distance) - math.sin(lat_rad) * math.sin(new_lat)
    )

    return math.degrees(new_lat), math.degrees(new_lon)


def point_to_path_distance(point_lat: float, point_lon: float,
                           start_lat: float, start_lon: float,
                           end_lat: float, end_lon: float) -> float:
    """Calculate minimum distance from a point to a great circle path (A->B) on Mars."""
    d_ap = haversine_distance(point_lat, point_lon, start_lat, start_lon)
    d_bp = haversine_distance(point_lat, point_lon, end_lat, end_lon)
    d_ab = haversine_distance(start_lat, start_lon, end_lat, end_lon)

    if d_ab < 0.1:
        return d_ap

    a_lat, a_lon = math.radians(start_lat), math.radians(start_lon)
    b_lat, b_lon = math.radians(end_lat), math.radians(end_lon)
    p_lat, p_lon = math.radians(point_lat), math.radians(point_lon)

    bearing_ab = math.atan2(
        math.sin(b_lon - a_lon) * math.cos(b_lat),
        math.cos(a_lat) * math.sin(b_lat) - math.sin(a_lat) * math.cos(b_lat) * math.cos(b_lon - a_lon)
    )
    bearing_ap = math.atan2(
        math.sin(p_lon - a_lon) * math.cos(p_lat),
        math.cos(a_lat) * math.sin(p_lat) - math.sin(a_lat) * math.cos(p_lat) * math.cos(p_lon - a_lon)
    )

    cross_track = abs(math.asin(math.sin(d_ap / MARS_RADIUS_KM) *
                                math.sin(bearing_ap - bearing_ab))) * MARS_RADIUS_KM
    along_track = math.acos(math.cos(d_ap / MARS_RADIUS_KM) /
                            math.cos(cross_track / MARS_RADIUS_KM)) * MARS_RADIUS_KM

    if along_track < 0 or along_track > d_ab:
        return min(d_ap, d_bp)

    return cross_track


def bearing_deg(from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> float:
    """Initial bearing from one point to another on Mars, in degrees [0, 360)."""
    a_lat, a_lon = math.radians(from_lat), math.radians(from_lon)
    b_lat, b_lon = math.radians(to_lat), math.radians(to_lon)
    y = math.sin(b_lon - a_lon) * math.cos(b_lat)
    x = math.cos(a_lat) * math.sin(b_lat) - math.sin(a_lat) * math.cos(b_lat) * math.cos(b_lon - a_lon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def bearing_to_cardinal(bearing: float) -> tuple:
    """Return (arrow_char, cardinal_label) for a bearing in degrees."""
    dirs = [
        (0,   '↑', 'N'),
        (45,  '↗', 'NE'),
        (90,  '→', 'E'),
        (135, '↘', 'SE'),
        (180, '↓', 'S'),
        (225, '↙', 'SW'),
        (270, '←', 'W'),
        (315, '↖', 'NW'),
    ]
    idx = int(((bearing + 22.5) % 360) // 45)
    return dirs[idx][1], dirs[idx][2]
