# FavTracks — Project Specification

## Overview
Web application for visualizing GPS activity tracks (running & cycling),
highlighting frequently used route segments with heatmap coloring.

## Prerequisites
- Web application, responsive (desktop-first, mobile-friendly)
- Builds on data from garmin_nostra: https://github.com/vinzgreg/garmin_nostra
- Activities and GPX file paths stored in garmin_nostra.db (SQLite)
- Follow the project structure of garmin_nostra
- Dockerized, Python-based

## Data Source
- **Database**: garmin_nostra.db, read-only access
  - Table `activities`: contains activity metadata (name, type, dates, speed, user_id, gpx_path, etc.)
  - Table `users`: user accounts
- **GPX files**: stored on disk, path referenced in `activities.gpx_path`
- Both the DB and the GPX folder are mounted into the container

## Activity Classification
- **Running**: `activity_type` contains "running", "lauf", "run", "trail_running", etc.
- **Cycling**: `activity_type` contains "cycling", "fahrrad", "bike", "mountain_biking",
  "gravel", "road", etc.
- **Exclude**: anything with "indoor" in `activity_type`
- Classification uses `activity_type` column only (no speed-based fallback needed)

## Segment Detection
- A **segment** is a street/track section shared by multiple activities.
  It starts where tracks begin to overlap and ends where the overlap ends.
- **Method**: grid-snapping. Snap GPS points to grid cells, then find common
  sequences of cells across activities.
- **Grid cell size by activity type**:
  - Running: 20m
  - Cycling: 50m
- **Segment break distance**: a gap longer than the grid cell size breaks a segment
  (i.e. consecutive non-matching cells end the overlap).
- **Architecture**: the segment detection layer must be abstracted behind a clean
  interface so that the grid-snapping method can be replaced (e.g. with
  OSRM-based map matching) without changing the frontend or storage layer.
- Precomputed **per-activity grid sequences** stored in favtracks.db.
  Segment overlaps are computed at query time based on active filters
  (activity type, date range, users). This keeps filter changes fast without
  needing to precompute every combination.
- Incremental updates when new activities appear.
- **Recompute command**: `python -m favtracks recompute` for full rebuild.
  Also exposed as a button/action in the UI.

## Features

### Map View
- Leaflet.js with OpenStreetMap tiles
- Pan / zoom
- Segments rendered as polylines, colored by frequency:
  - Red: heavily frequented
  - Orange: mid frequency
  - Green: rarely used

### Hover Info
- Hover over a segment to show:
  - Number of times this segment was used
  - Last activity date
  - Last activity name (from `activities.activity_name`)

### Filters
- **Activity type selector**: Running / Cycling
- **Date range filter**: start and end date picker
- **User selector**: by default all users are shown. Allow selecting one or
  multiple users from the `users` table.

### Segment Selection & GPX Export
- Click to select multiple segments on the map
- Export selected segments as GPX using **original GPS points** (not snapped grid
  coordinates) traced back from the matching activities
- Toggle: single continuous track or multi-segment GPX (`<trkseg>` per segment)

## Tech Stack
- **Backend**: Flask (Python)
- **Frontend**: Leaflet.js, HTML/CSS/JS
- **Database**: SQLite (garmin_nostra.db read-only + favtracks.db for segments)
- **Deployment**: Docker, Linux host

## Configuration
- TOML config file (following garmin_nostra's pattern), e.g. `config.toml`
- Configurable values:
  - Path to garmin_nostra.db
  - Path to favtracks.db
  - Path to GPX directory (if not derived from DB)
  - Grid cell sizes (defaults: running=20m, cycling=50m)
  - Flask host/port

## Instructions
- Do not modify garmin_nostra.db — treat it as read-only
- Store all favtracks-specific data in a separate favtracks.db
- ~2000 activities expected — per-activity grid sequences are precomputed,
  segment overlaps computed at query time per filter combination

## Future Enhancements
- **Map matching via OSRM**: replace grid-snapping with OSRM-based map matching
  for road-aware segment detection. The segment detection interface is designed
  to allow this swap without frontend or storage changes. OSRM would run as a
  separate Docker container with a regional OSM extract.
