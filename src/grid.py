"""Grid-snapping segment detection.

This module implements the grid-snapping approach for segment detection.
It is designed behind a clean interface so it can be replaced with an
OSRM-based map-matching implementation in the future.
"""

import logging
import math

log = logging.getLogger("favtracks.grid")

# Earth radius in meters (WGS-84 mean)
_EARTH_R = 6_371_000


def _meters_per_degree_lat() -> float:
    return math.pi / 180.0 * _EARTH_R


def _meters_per_degree_lon(lat_deg: float) -> float:
    return math.pi / 180.0 * _EARTH_R * math.cos(math.radians(lat_deg))


def snap_point(lat: float, lon: float, grid_m: float) -> tuple[int, int]:
    """Snap a lat/lon point to a grid cell of the given size in meters.

    Returns (row, col) integer cell coordinates.
    """
    m_per_lat = _meters_per_degree_lat()
    m_per_lon = _meters_per_degree_lon(lat)

    row = int(math.floor(lat * m_per_lat / grid_m))
    col = int(math.floor(lon * m_per_lon / grid_m))
    return (row, col)


def snap_track(points: list[tuple[float, float]], grid_m: float) -> list[tuple[int, int]]:
    """Snap a list of (lat, lon) points to grid cells, removing consecutive duplicates.

    Returns a list of (row, col) cell coordinates representing the path through
    the grid. Consecutive duplicate cells are collapsed so that a straight road
    within one cell doesn't produce many identical entries.
    """
    cells = []
    prev = None
    for lat, lon in points:
        cell = snap_point(lat, lon, grid_m)
        if cell != prev:
            cells.append(cell)
            prev = cell
    return cells


def cell_center(row: int, col: int, grid_m: float, ref_lat: float) -> tuple[float, float]:
    """Convert a grid cell back to approximate lat/lon (cell center).

    ref_lat is a reference latitude for the longitude conversion (use the
    rough center of the dataset).
    """
    m_per_lat = _meters_per_degree_lat()
    m_per_lon = _meters_per_degree_lon(ref_lat)

    lat = (row + 0.5) * grid_m / m_per_lat
    lon = (col + 0.5) * grid_m / m_per_lon
    return (lat, lon)


def compute_overlaps(sequences: list[dict], grid_m: float) -> dict:
    """Compute segment overlaps from precomputed grid sequences.

    sequences: list of dicts with keys 'activity_id', 'grid_cells'
               where grid_cells is a list of (row, col) tuples.

    Returns a dict mapping (row, col) -> {
        'count': int,
        'activity_ids': list[int],
    }
    """
    cell_usage: dict[tuple[int, int], set[int]] = {}

    for seq in sequences:
        activity_id = seq["activity_id"]
        seen_in_activity: set[tuple[int, int]] = set()
        for cell in seq["grid_cells"]:
            cell_t = tuple(cell)
            if cell_t not in seen_in_activity:
                seen_in_activity.add(cell_t)
                if cell_t not in cell_usage:
                    cell_usage[cell_t] = set()
                cell_usage[cell_t].add(activity_id)

    # Only keep cells used by more than one activity
    overlaps = {}
    for cell, aids in cell_usage.items():
        if len(aids) >= 2:
            overlaps[cell] = {
                "count": len(aids),
                "activity_ids": sorted(aids),
            }

    log.info("Found %d overlapping cells from %d activities", len(overlaps), len(sequences))
    return overlaps


def group_into_segments(overlaps: dict, grid_m: float) -> list[list[tuple[int, int]]]:
    """Group overlapping cells into contiguous segments.

    Two cells are considered adjacent if they are within 1 cell distance
    (8-connected neighbourhood). Returns a list of segments, where each
    segment is a list of (row, col) cells.
    """
    if not overlaps:
        return []

    remaining = set(overlaps.keys())
    segments = []

    while remaining:
        start = next(iter(remaining))
        segment = []
        queue = [start]

        while queue:
            cell = queue.pop(0)
            if cell not in remaining:
                continue
            remaining.remove(cell)
            segment.append(cell)
            r, c = cell
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    neighbour = (r + dr, c + dc)
                    if neighbour in remaining:
                        queue.append(neighbour)

        segments.append(segment)

    log.debug("Grouped %d overlapping cells into %d segments", len(overlaps), len(segments))
    return segments
