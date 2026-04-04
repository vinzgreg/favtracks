"""Precompute grid sequences for all activities."""

import logging
import sqlite3
from datetime import datetime, timezone

from src.classify import classify_activity
from src.gpx_parse import parse_gpx
from src.grid import snap_track
from src.storage import FavTracksStore

log = logging.getLogger("favtracks.compute")


def _open_garmin_db(path: str) -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.OperationalError:
        log.error("Cannot open garmin_nostra DB at '%s'. Check the path in config.toml.", path)
        raise
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_activities(garmin_conn: sqlite3.Connection) -> list[dict]:
    rows = garmin_conn.execute(
        "SELECT id, activity_type, gpx_path FROM activities "
        "WHERE gpx_path IS NOT NULL AND gpx_path != ''"
    ).fetchall()
    return [dict(r) for r in rows]


def recompute_all(config: dict, on_progress=None) -> dict:
    """Full recompute: clear favtracks DB, re-parse all GPX files.

    on_progress: optional callback(processed, skipped, total) called after each activity.
    Returns a summary dict with counts.
    """
    store = FavTracksStore(config["favtracks_db_path"])
    try:
        store.delete_all()
        return _compute(config, store, incremental=False, on_progress=on_progress)
    finally:
        store.close()


def compute_incremental(config: dict, on_progress=None) -> dict:
    """Only process activities not yet in favtracks DB.

    on_progress: optional callback(processed, skipped, total) called after each activity.
    Returns a summary dict with counts.
    """
    store = FavTracksStore(config["favtracks_db_path"])
    try:
        return _compute(config, store, incremental=True, on_progress=on_progress)
    finally:
        store.close()


def _compute(config: dict, store: FavTracksStore, incremental: bool,
             on_progress=None) -> dict:
    garmin_conn = _open_garmin_db(config["garmin_db_path"])
    try:
        activities = _fetch_activities(garmin_conn)
    finally:
        garmin_conn.close()

    log.info("Found %d activities with GPX files", len(activities))

    if incremental:
        existing = store.get_computed_activity_ids()
        activities = [a for a in activities if a["id"] not in existing]
        log.info("Incremental mode: %d new activities to process", len(activities))

    total = len(activities)
    now = datetime.now(timezone.utc).isoformat()
    processed = 0
    skipped = 0
    errors = 0

    for act in activities:
        category = classify_activity(act["activity_type"])
        if category is None:
            skipped += 1
            if on_progress:
                on_progress(processed, skipped, total)
            continue

        grid_m = config["running_grid_m"] if category == "running" else config["cycling_grid_m"]
        points = parse_gpx(act["gpx_path"], config.get("gpx_base_dir"))

        if not points:
            log.warning("No points in GPX for activity %d (%s), skipping",
                        act["id"], act["gpx_path"])
            skipped += 1
            if on_progress:
                on_progress(processed, skipped, total)
            continue

        cells = snap_track(points, grid_m)
        if len(cells) < 2:
            log.debug("Activity %d produced fewer than 2 grid cells, skipping", act["id"])
            skipped += 1
            if on_progress:
                on_progress(processed, skipped, total)
            continue

        store.upsert_grid_sequence(act["id"], act["activity_type"], category, cells, now)
        processed += 1

        if on_progress:
            on_progress(processed, skipped, total)

    summary = {"processed": processed, "skipped": skipped, "errors": errors,
               "total": total}
    log.info("Compute complete: %d processed, %d skipped, %d errors",
             processed, skipped, errors)
    return summary
