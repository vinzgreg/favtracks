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


def snap_track(points: list[tuple[float, float]], grid_m: float) -> list[list]:
    """Snap a list of (lat, lon) points to grid cells, removing consecutive duplicates.

    Returns a list of [row, col, lat, lon] entries. The lat/lon is a representative
    original GPS coordinate for that cell (average of all points that mapped to it).
    Consecutive duplicate cells are collapsed.
    """
    # First pass: group original points by cell, preserving order
    cell_order = []
    cell_points: dict[tuple[int, int], list[tuple[float, float]]] = {}
    prev = None
    for lat, lon in points:
        cell = snap_point(lat, lon, grid_m)
        if cell not in cell_points:
            cell_points[cell] = []
        cell_points[cell].append((lat, lon))
        if cell != prev:
            cell_order.append(cell)
            prev = cell

    # Build result with average original coordinate per cell
    result = []
    for cell in cell_order:
        pts = cell_points[cell]
        avg_lat = sum(p[0] for p in pts) / len(pts)
        avg_lon = sum(p[1] for p in pts) / len(pts)
        result.append([cell[0], cell[1], round(avg_lat, 6), round(avg_lon, 6)])
    return result


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
               where grid_cells entries are [row, col, lat, lon].

    Returns a dict mapping (row, col) -> {
        'count': int,
        'activity_ids': list[int],
    }
    """
    # Build a mapping from each cell to the activities that passed through it.
    # Each cell is expanded to include its 8 neighbours so that GPS drift
    # (which causes the same street to snap to adjacent cells on different runs)
    # is compensated. Two activities within one cell-width of each other are
    # treated as sharing the same segment.
    cell_usage: dict[tuple[int, int], set[int]] = {}

    for seq in sequences:
        activity_id = seq["activity_id"]
        # Track which expanded cells were already claimed for this activity
        # to avoid double-counting it within the same activity.
        claimed: set[tuple[int, int]] = set()
        for cell in seq["grid_cells"]:
            r, c = cell[0], cell[1]
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    neighbour = (r + dr, c + dc)
                    if neighbour not in claimed:
                        claimed.add(neighbour)
                        if neighbour not in cell_usage:
                            cell_usage[neighbour] = set()
                        cell_usage[neighbour].add(activity_id)

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
