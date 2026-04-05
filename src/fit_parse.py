"""Parse FIT files (plain or gzipped) to extract track points."""

import gzip
import io
import logging
from pathlib import Path

log = logging.getLogger("favtracks.fit_parse")


def parse_fit(fit_path: str, base_dir: str | None = None) -> list[tuple[float, float]]:
    """Parse a FIT or FIT.gz file and return a list of (lat, lon) points."""
    path = Path(fit_path)
    if not path.is_absolute() and base_dir:
        path = Path(base_dir) / path

    if not path.exists():
        log.warning("FIT file not found: %s", path)
        return []

    try:
        import fitparse
    except ImportError:
        log.error("fitparse is not installed — cannot read FIT files")
        return []

    try:
        if path.suffix.lower() == ".gz":
            with gzip.open(path, "rb") as gz:
                data = gz.read()
            fit_file = fitparse.FitFile(io.BytesIO(data))
        else:
            fit_file = fitparse.FitFile(str(path))
    except Exception:
        log.error("Failed to open FIT file: %s", path, exc_info=True)
        return []

    points = []
    try:
        for record in fit_file.get_messages("record"):
            fields = {f.name: f.value for f in record}
            lat = fields.get("position_lat")
            lon = fields.get("position_long")
            if lat is not None and lon is not None:
                # FIT stores coordinates as semicircles — convert to degrees
                lat_deg = lat * (180.0 / 2**31)
                lon_deg = lon * (180.0 / 2**31)
                points.append((lat_deg, lon_deg))
    except Exception:
        log.error("Failed to parse records in FIT file: %s", path, exc_info=True)
        return []

    log.debug("Parsed %d points from FIT file %s", len(points), path)
    return points
