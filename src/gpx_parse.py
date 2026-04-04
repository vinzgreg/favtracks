"""Parse GPX files to extract track points."""

import logging
from pathlib import Path

import gpxpy

log = logging.getLogger("favtracks.gpx_parse")


def parse_gpx(gpx_path: str, base_dir: str | None = None) -> list[tuple[float, float]]:
    """Parse a GPX file and return a list of (lat, lon) points.

    If gpx_path is relative and base_dir is provided, the path is resolved
    relative to base_dir.
    """
    path = Path(gpx_path)
    if not path.is_absolute() and base_dir:
        path = Path(base_dir) / path

    if not path.exists():
        log.warning("GPX file not found: %s", path)
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            gpx = gpxpy.parse(f)
    except Exception:
        log.error("Failed to parse GPX file: %s", path, exc_info=True)
        return []

    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for pt in segment.points:
                points.append((pt.latitude, pt.longitude))

    log.debug("Parsed %d points from %s", len(points), path)
    return points


def extract_points_for_cells(gpx_path: str, cells: set[tuple[int, int]],
                             grid_m: float,
                             base_dir: str | None = None) -> list[tuple[float, float]]:
    """Extract original GPS points that fall within the given grid cells.

    Used for GPX export with original (non-snapped) coordinates.
    """
    from src.grid import snap_point

    points = parse_gpx(gpx_path, base_dir)
    matched = []
    for lat, lon in points:
        cell = snap_point(lat, lon, grid_m)
        if cell in cells:
            matched.append((lat, lon))
    return matched
