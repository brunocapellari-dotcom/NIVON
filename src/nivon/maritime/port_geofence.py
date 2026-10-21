# Adapted from AgroLogMT/models/port_geofence.py (main 2026-10-19); internal use, validate provenance before release.
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence


ZONE_PRIORITY = {
    "UNKNOWN": 0,
    "SEA": 1,
    "APPROACH": 2,
    "PORT": 3,
    "ANCHORAGE": 4,
    "CHANNEL": 5,
    "BERTH": 6,
}


def _validate_coordinate(latitude: float, longitude: float) -> tuple[float, float]:
    lat = float(latitude)
    lon = float(longitude)
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise ValueError("coordenada de geofence deve ser finita")
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"latitude de geofence fora do limite fisico: {lat}")
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"longitude de geofence fora do limite fisico: {lon}")
    return lat, lon


def _polygon_area(polygon: Sequence[tuple[float, float]]) -> float:
    """Planar shoelace area in degree², sufficient as a degeneracy guard for small port polygons."""
    area = 0.0
    for index, (lat_a, lon_a) in enumerate(polygon):
        lat_b, lon_b = polygon[(index + 1) % len(polygon)]
        area += lon_a * lat_b - lon_b * lat_a
    return abs(area) / 2.0


@dataclass(frozen=True)
class PortZone:
    zone_id: str
    port_id: str
    zone: str
    polygon: tuple[tuple[float, float], ...]  # (lat, lon)
    geofence_version: str
    terminal_id: str | None = None
    source_id: str | None = None

    def __post_init__(self) -> None:
        if not self.zone_id.strip():
            raise ValueError("zone_id obrigatorio")
        if not self.port_id.strip():
            raise ValueError("port_id obrigatorio")
        if not self.geofence_version.strip():
            raise ValueError("geofence_version obrigatoria")
        if self.zone.upper() not in ZONE_PRIORITY:
            raise ValueError(f"zone invalida: {self.zone}")
        if len(self.polygon) < 3:
            raise ValueError("polygon precisa de ao menos 3 vertices")

        normalized = tuple(_validate_coordinate(lat, lon) for lat, lon in self.polygon)
        if len(set(normalized)) < 3:
            raise ValueError("polygon precisa de ao menos 3 vertices distintos")
        if _polygon_area(normalized) <= 1e-12:
            raise ValueError("polygon degenerado ou com area nula")


def point_in_polygon(latitude: float, longitude: float, polygon: Sequence[tuple[float, float]]) -> bool:
    """Ray-casting for small port polygons away from the antimeridian."""
    y, x = _validate_coordinate(latitude, longitude)
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        yi, xi = polygon[i]
        yj, xj = polygon[j]
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def classify_position(
    latitude: float,
    longitude: float,
    zones: Iterable[PortZone],
    *,
    preferred_port_id: str | None = None,
) -> dict[str, str | None]:
    _validate_coordinate(latitude, longitude)
    hits: list[PortZone] = []
    for zone in zones:
        if preferred_port_id and zone.port_id != preferred_port_id:
            continue
        if point_in_polygon(latitude, longitude, zone.polygon):
            hits.append(zone)
    if not hits:
        return {
            "zone": "SEA",
            "port_id": preferred_port_id,
            "terminal_id": None,
            "zone_id": None,
            "geofence_version": None,
            "source_id": None,
        }
    best = max(hits, key=lambda z: (ZONE_PRIORITY[z.zone.upper()], z.terminal_id is not None))
    return {
        "zone": best.zone.upper(),
        "port_id": best.port_id,
        "terminal_id": best.terminal_id,
        "zone_id": best.zone_id,
        "geofence_version": best.geofence_version,
        "source_id": best.source_id,
    }
