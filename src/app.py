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
from src.grid import compute_overlaps
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
                f"file:{config['garmin_db_path']}?mode=ro&immutable=1", uri=True, timeout=10
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

        total_in_category = len(sequences)

        if not sequences:
            return jsonify({"edges": [], "max_count": 0,
                            "total_activities": 0, "filtered_activities": 0})

        # Always filter by date and user via garmin_nostra DB
        activity_ids = {s["activity_id"] for s in sequences}
        activity_ids = _filter_activity_ids(
            config["garmin_db_path"], activity_ids,
            date_from=date_from, date_to=date_to,
            user_ids_raw=user_ids_raw,
        )
        sequences = [s for s in sequences if s["activity_id"] in activity_ids]
        filtered_count = len(sequences)

        if not sequences:
            return jsonify({"edges": [], "max_count": 0,
                            "total_activities": total_in_category,
                            "filtered_activities": 0})

        # Compute overlaps
        overlaps = compute_overlaps(sequences, grid_m)
        if not overlaps:
            return jsonify({"edges": [], "max_count": 0})

        # Build a lookup: (row, col) -> original GPS coord per activity
        # Each activity may have a different representative coord for the same cell
        # We pick the first one we encounter per cell pair
        cell_coords: dict[tuple[int, int], tuple[float, float]] = {}
        for seq in sequences:
            for entry in seq["grid_cells"]:
                cell_key = (entry[0], entry[1])
                if cell_key not in cell_coords and len(entry) >= 4:
                    cell_coords[cell_key] = (entry[2], entry[3])

        def best_overlap(r, c):
            """Return the overlap entry for cell (r,c) or its nearest neighbour."""
            for dr in range(0, 2):
                for dc in range(0, 2):
                    for sr, sc in [(dr, dc), (-dr, dc), (dr, -dc), (-dr, -dc)]:
                        k = (r + sr, c + sc)
                        if k in overlaps:
                            return k, overlaps[k]
            return None, None

        # Build line segments from consecutive overlapping cells along tracks
        # using original GPS coordinates
        edge_data = {}
        for seq in sequences:
            entries = seq["grid_cells"]
            for i in range(len(entries) - 1):
                a_r, a_c = entries[i][0], entries[i][1]
                b_r, b_c = entries[i + 1][0], entries[i + 1][1]
                a_key, a_info = best_overlap(a_r, a_c)
                b_key, b_info = best_overlap(b_r, b_c)
                if a_key is None or b_key is None:
                    continue
                edge_key = (a_key, b_key) if a_key <= b_key else (b_key, a_key)
                count = min(a_info["count"], b_info["count"])
                aids = set(a_info["activity_ids"]) & set(b_info["activity_ids"])
                if not aids:
                    continue
                if edge_key not in edge_data or count > edge_data[edge_key]["count"]:
                    coord_a = (entries[i][2], entries[i][3]) if len(entries[i]) >= 4 else (0, 0)
                    coord_b = (entries[i + 1][2], entries[i + 1][3]) if len(entries[i + 1]) >= 4 else (0, 0)
                    edge_data[edge_key] = {
                        "count": count,
                        "activity_ids": sorted(aids),
                        "coord_a": coord_a,
                        "coord_b": coord_b,
                    }

        if not edge_data:
            return jsonify({"edges": [], "max_count": 0,
                            "total_activities": total_in_category,
                            "filtered_activities": filtered_count})

        max_count = max(e["count"] for e in edge_data.values())

        edges = []
        for (a_key, b_key), info in edge_data.items():
            edges.append({
                "coords": [list(info["coord_a"]), list(info["coord_b"])],
                "count": info["count"],
                "activity_ids": info["activity_ids"],
                "cells": [list(a_key), list(b_key)],
            })

        return jsonify({"edges": edges, "max_count": max_count,
                        "total_activities": total_in_category,
                        "filtered_activities": filtered_count})

    @app.route("/api/tracks")
    def api_tracks():
        """Return full track polylines for all filtered activities.

        Same query params as /api/segments. Returns simplified tracks
        built from stored grid cell coordinates (no GPX re-reads).
        """
        category = request.args.get("category")
        if category not in ("running", "cycling"):
            return jsonify({"error": "Parameter 'category' must be 'running' or 'cycling'."}), 400

        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")
        user_ids_raw = request.args.get("user_ids")

        store = FavTracksStore(config["favtracks_db_path"])
        try:
            sequences = store.get_all_sequences(category=category)
        finally:
            store.close()

        if not sequences:
            return jsonify({"tracks": []})

        activity_ids = {s["activity_id"] for s in sequences}
        activity_ids = _filter_activity_ids(
            config["garmin_db_path"], activity_ids,
            date_from=date_from, date_to=date_to,
            user_ids_raw=user_ids_raw,
        )
        sequences = [s for s in sequences if s["activity_id"] in activity_ids]

        tracks = []
        for seq in sequences:
            coords = [
                [e[2], e[3]] for e in seq["grid_cells"] if len(e) >= 4
            ]
            if len(coords) >= 2:
                tracks.append({"activity_id": seq["activity_id"], "coords": coords})

        log.debug("Returning %d full tracks for category=%s", len(tracks), category)
        return jsonify({"tracks": tracks})

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
                f"file:{config['garmin_db_path']}?mode=ro&immutable=1", uri=True, timeout=10
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
        """Trigger a full recompute, streaming progress via SSE."""
        log.info("Recompute triggered via API")

        def generate():
            import json as _json
            try:
                def on_progress(processed, skipped, total):
                    data = {"processed": processed, "skipped": skipped, "total": total}
                    yield f"data: {_json.dumps(data)}\n\n"

                summary = recompute_all(config, on_progress=on_progress)
                yield f"data: {_json.dumps({**summary, 'done': True})}\n\n"
            except Exception:
                log.error("Recompute failed", exc_info=True)
                yield f"data: {_json.dumps({'error': 'Recompute failed. Check logs.'})}\n\n"

        return Response(generate(), mimetype="text/event-stream")

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
                f"file:{config['garmin_db_path']}?mode=ro&immutable=1", uri=True, timeout=10
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
        conn = sqlite3.connect(f"file:{garmin_db_path}?mode=ro&immutable=1", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT id FROM activities WHERE {where}", params).fetchall()
        conn.close()
    except sqlite3.OperationalError:
        log.error("Cannot filter activities from garmin_nostra DB", exc_info=True)
        return set()

    filtered = {r["id"] for r in rows}
    log.info("Filter: %d input → %d filtered (user_ids=%s, dates=%s..%s)",
             len(activity_ids), len(filtered), user_ids_raw, date_from, date_to)
    return filtered
