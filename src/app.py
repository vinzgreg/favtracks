"""Flask application for FavTracks."""

import json
import logging
import sqlite3

import gpxpy
import gpxpy.gpx
from flask import Flask, jsonify, render_template, request, Response

from src.classify import classify_activity
from src.compute import compute_incremental, recompute_all
from src.config import load_config, setup_logging
from src.gpx_parse import extract_points_for_cells
from src.grid import cell_center, compute_overlaps, group_into_segments
from src.storage import FavTracksStore

log = logging.getLogger("favtracks.app")


def create_app(config: dict | None = None) -> Flask:
    if config is None:
        config = load_config()

    setup_logging(config.get("log_level", "INFO"))

    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )
    app.config["FAVTRACKS"] = config

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/users")
    def api_users():
        """Return list of users from garmin_nostra DB."""
        try:
            conn = sqlite3.connect(
                f"file:{config['garmin_db_path']}?mode=ro", uri=True, timeout=10
            )
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT id, name FROM users ORDER BY name").fetchall()
            conn.close()
        except sqlite3.OperationalError:
            log.error("Cannot read users from garmin_nostra DB at '%s'", config["garmin_db_path"])
            return jsonify({"error": "Cannot connect to garmin_nostra database. Check garmin_db_path in config.toml."}), 500
        return jsonify([{"id": r["id"], "name": r["name"]} for r in rows])

    @app.route("/api/segments")
    def api_segments():
        """Return segments with overlap data, filtered by query params.

        Query params:
          category: 'running' or 'cycling' (required)
          date_from: ISO date string (optional)
          date_to: ISO date string (optional)
          user_ids: comma-separated user IDs (optional, default=all)
        """
        category = request.args.get("category")
        if category not in ("running", "cycling"):
            return jsonify({"error": "Parameter 'category' is required and must be 'running' or 'cycling'."}), 400

        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")
        user_ids_raw = request.args.get("user_ids")

        grid_m = config["running_grid_m"] if category == "running" else config["cycling_grid_m"]

        # Get grid sequences from favtracks DB
        store = FavTracksStore(config["favtracks_db_path"])
        try:
            sequences = store.get_all_sequences(category=category)
        finally:
            store.close()

        if not sequences:
            return jsonify({"segments": [], "max_count": 0})

        # Filter by date and user via garmin_nostra DB
        activity_ids = {s["activity_id"] for s in sequences}
        if date_from or date_to or user_ids_raw:
            activity_ids = _filter_activity_ids(
                config["garmin_db_path"], activity_ids,
                date_from=date_from, date_to=date_to,
                user_ids_raw=user_ids_raw,
            )
            sequences = [s for s in sequences if s["activity_id"] in activity_ids]

        if not sequences:
            return jsonify({"segments": [], "max_count": 0})

        # Compute overlaps and group into segments
        overlaps = compute_overlaps(sequences, grid_m)
        if not overlaps:
            return jsonify({"segments": [], "max_count": 0})

        grouped = group_into_segments(overlaps, grid_m)

        # Estimate reference latitude from first cell
        first_cell = next(iter(overlaps.keys()))
        ref_lat = cell_center(first_cell[0], first_cell[1], grid_m, 48.0)[0]

        max_count = max(o["count"] for o in overlaps.values())

        segment_list = []
        for seg_cells in grouped:
            coords = [cell_center(r, c, grid_m, ref_lat) for r, c in seg_cells]
            counts = [overlaps[(r, c)]["count"] for r, c in seg_cells]
            seg_activity_ids = set()
            for r, c in seg_cells:
                seg_activity_ids.update(overlaps[(r, c)]["activity_ids"])
            avg_count = sum(counts) / len(counts) if counts else 0

            segment_list.append({
                "coords": coords,
                "count": round(avg_count, 1),
                "activity_ids": sorted(seg_activity_ids),
                "cells": seg_cells,
            })

        return jsonify({"segments": segment_list, "max_count": max_count})

    @app.route("/api/segment_info")
    def api_segment_info():
        """Return details for a specific segment's activities.

        Query params:
          activity_ids: comma-separated activity IDs
        """
        ids_raw = request.args.get("activity_ids", "")
        if not ids_raw:
            return jsonify({"error": "Parameter 'activity_ids' is required."}), 400

        try:
            activity_ids = [int(x) for x in ids_raw.split(",")]
        except ValueError:
            return jsonify({"error": "activity_ids must be comma-separated integers."}), 400

        try:
            conn = sqlite3.connect(
                f"file:{config['garmin_db_path']}?mode=ro", uri=True, timeout=10
            )
            conn.row_factory = sqlite3.Row
            placeholders = ",".join("?" for _ in activity_ids)
            rows = conn.execute(
                f"SELECT id, activity_name, start_time_local, activity_type "
                f"FROM activities WHERE id IN ({placeholders}) "
                f"ORDER BY start_time_local DESC",
                activity_ids,
            ).fetchall()
            conn.close()
        except sqlite3.OperationalError:
            log.error("Cannot query activities from garmin_nostra DB")
            return jsonify({"error": "Database read error."}), 500

        activities = [
            {
                "id": r["id"],
                "name": r["activity_name"],
                "date": r["start_time_local"],
                "type": r["activity_type"],
            }
            for r in rows
        ]

        return jsonify({
            "count": len(activities),
            "last_date": activities[0]["date"] if activities else None,
            "last_name": activities[0]["name"] if activities else None,
            "activities": activities,
        })

    @app.route("/api/recompute", methods=["POST"])
    def api_recompute():
        """Trigger a full recompute of all grid sequences."""
        log.info("Recompute triggered via API")
        try:
            summary = recompute_all(config)
        except Exception:
            log.error("Recompute failed", exc_info=True)
            return jsonify({"error": "Recompute failed. Check logs for details."}), 500
        return jsonify(summary)

    @app.route("/api/export_gpx", methods=["POST"])
    def api_export_gpx():
        """Export selected segments as a GPX file using original GPS points.

        JSON body:
          segments: list of { activity_ids: [...], cells: [...] }
          multi_segment: bool (default false)
          category: 'running' or 'cycling'
        """
        data = request.get_json()
        if not data or "segments" not in data:
            return jsonify({"error": "Request body must contain 'segments'."}), 400

        category = data.get("category", "running")
        grid_m = config["running_grid_m"] if category == "running" else config["cycling_grid_m"]
        multi_segment = data.get("multi_segment", False)

        # Fetch gpx_path for all referenced activities
        all_activity_ids = set()
        for seg in data["segments"]:
            all_activity_ids.update(seg.get("activity_ids", []))

        try:
            conn = sqlite3.connect(
                f"file:{config['garmin_db_path']}?mode=ro", uri=True, timeout=10
            )
            conn.row_factory = sqlite3.Row
            placeholders = ",".join("?" for _ in all_activity_ids)
            rows = conn.execute(
                f"SELECT id, gpx_path FROM activities WHERE id IN ({placeholders})",
                list(all_activity_ids),
            ).fetchall()
            conn.close()
        except sqlite3.OperationalError:
            log.error("Cannot query activities for GPX export")
            return jsonify({"error": "Database read error."}), 500

        gpx_paths = {r["id"]: r["gpx_path"] for r in rows}

        # Build GPX output
        gpx_out = gpxpy.gpx.GPX()
        track = gpxpy.gpx.GPXTrack()
        gpx_out.tracks.append(track)

        for seg_data in data["segments"]:
            cells = {tuple(c) for c in seg_data.get("cells", [])}
            seg_activity_ids = seg_data.get("activity_ids", [])

            all_points = []
            for aid in seg_activity_ids:
                gpx_path = gpx_paths.get(aid)
                if not gpx_path:
                    continue
                pts = extract_points_for_cells(
                    gpx_path, cells, grid_m, config.get("gpx_base_dir")
                )
                all_points.extend(pts)

            if not all_points:
                continue

            gpx_seg = gpxpy.gpx.GPXTrackSegment()
            for lat, lon in all_points:
                gpx_seg.points.append(gpxpy.gpx.GPXTrackPoint(lat, lon))

            if multi_segment:
                seg_track = gpxpy.gpx.GPXTrack()
                seg_track.segments.append(gpx_seg)
                gpx_out.tracks.append(seg_track)
            else:
                track.segments.append(gpx_seg)

        # Remove the empty first track if multi_segment mode added separate tracks
        if multi_segment and not track.segments:
            gpx_out.tracks.remove(track)

        return Response(
            gpx_out.to_xml(),
            mimetype="application/gpx+xml",
            headers={"Content-Disposition": "attachment; filename=favtracks_export.gpx"},
        )

    return app


def _filter_activity_ids(garmin_db_path: str, activity_ids: set[int],
                         date_from: str | None, date_to: str | None,
                         user_ids_raw: str | None) -> set[int]:
    """Filter activity IDs by date range and user via garmin_nostra DB."""
    conditions = []
    params: list = []

    placeholders = ",".join("?" for _ in activity_ids)
    conditions.append(f"id IN ({placeholders})")
    params.extend(activity_ids)

    if date_from:
        conditions.append("start_time_local >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("start_time_local <= ?")
        params.append(date_to + "T23:59:59")
    if user_ids_raw:
        try:
            user_ids = [int(x) for x in user_ids_raw.split(",")]
        except ValueError:
            return activity_ids
        user_ph = ",".join("?" for _ in user_ids)
        conditions.append(f"user_id IN ({user_ph})")
        params.extend(user_ids)

    where = " AND ".join(conditions)
    try:
        conn = sqlite3.connect(f"file:{garmin_db_path}?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT id FROM activities WHERE {where}", params).fetchall()
        conn.close()
    except sqlite3.OperationalError:
        log.error("Cannot filter activities from garmin_nostra DB")
        return activity_ids

    return {r["id"] for r in rows}
