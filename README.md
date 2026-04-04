# FavTracks

Visualize your most frequently used running and cycling routes on an interactive map.
FavTracks analyses GPX tracks from [garmin_nostra](https://github.com/vinzgreg/garmin_nostra)
and highlights route segments by usage frequency — red for heavily used, green for rarely used.

## Features

- **Heatmap view** of route segments colored by frequency (red → orange → green)
- **Activity type filter** — switch between running and cycling
- **Date range filter** — focus on a specific time period
- **Multi-user support** — show all users or filter by one or more
- **Hover info** — see how often a segment was used, last activity date and name
- **Segment selection** — click segments to select them
- **GPX export** — export selected segments using original GPS points (single track or multi-segment)
- **Responsive layout** — works on desktop and mobile

## Prerequisites

- Docker and Docker Compose
- A running [garmin_nostra](https://github.com/vinzgreg/garmin_nostra) instance with synced activities and GPX files

## Quick start

1. **Clone and configure**

   ```bash
   git clone <your-repo-url> favtracks
   cd favtracks
   cp config.toml.example config.toml
   ```

2. **Edit `config.toml`** — point it to your garmin_nostra database and GPX files:

   ```toml
   [storage]
   garmin_db_path = "/data/garmin_nostra.db"
   favtracks_db_path = "/data/favtracks.db"
   ```

   Paths are inside the container. The `docker-compose.yml` mounts `~/data/favtracks`
   to `/data`, so place or symlink your `garmin_nostra.db` and GPX directory there.

3. **Start the container**

   ```bash
   docker compose up --build
   ```

   On first start, FavTracks will scan all GPX files and precompute grid sequences.
   With ~2000 activities this takes a few minutes.

4. **Open the app** at [http://localhost:5055](http://localhost:5055)

## Configuration

All settings live in `config.toml`. See `config.toml.example` for all options with comments.

| Section       | Key                | Default                  | Description                                      |
|---------------|--------------------|--------------------------|--------------------------------------------------|
| `[storage]`   | `garmin_db_path`   | `/data/garmin_nostra.db` | Path to garmin_nostra SQLite DB (read-only)      |
| `[storage]`   | `favtracks_db_path`| `/data/favtracks.db`     | Path to favtracks SQLite DB (created on startup) |
| `[storage]`   | `gpx_base_dir`     | _(none)_                 | Base dir for GPX files if paths in DB are relative |
| `[detection]` | `running_grid_m`   | `20`                     | Grid cell size in meters for running             |
| `[detection]` | `cycling_grid_m`   | `50`                     | Grid cell size in meters for cycling             |
| `[logging]`   | `level`            | `INFO`                   | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`   |
| `[server]`    | `host`             | `0.0.0.0`                | Flask bind address                               |
| `[server]`    | `port`             | `5000`                   | Flask port (inside the container)                 |

## CLI commands

Run inside the container or locally with `python __main__.py <command>`:

| Command       | Description                                        |
|---------------|----------------------------------------------------|
| `serve`       | Start the web server (default)                     |
| `recompute`   | Delete all cached data and recompute from scratch  |
| `incremental` | Process only new activities not yet in favtracks.db|

The entrypoint runs `incremental` automatically on every container start, then launches the server.

## How it works

1. **Grid snapping** — each GPS track is snapped to a grid (20m cells for running, 50m for cycling). Consecutive duplicate cells are collapsed.
2. **Per-activity storage** — the grid cell sequence for each activity is stored in `favtracks.db`.
3. **Query-time overlap** — when you load the map, the backend filters activities by your selected type, date range, and users, then computes which grid cells appear in multiple activities. These overlapping cells are grouped into contiguous segments.
4. **Original GPS export** — when exporting GPX, the original track points (not snapped coordinates) are extracted from the source GPX files.

## Docker setup

The `docker-compose.yml` binds to `127.0.0.1:5055` on the host. To change the port,
edit the `ports` line in `docker-compose.yml`.

The container runs as non-root user (UID 1000). Make sure the mounted data directory
is readable by this UID.

## Project structure

```
favtracks/
├── config.toml.example      # Configuration template
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
├── requirements.txt
├── src/
│   ├── app.py               # Flask app and API endpoints
│   ├── classify.py           # Activity type classification
│   ├── compute.py            # Precompute engine
│   ├── config.py             # Config loading and logging
│   ├── gpx_parse.py          # GPX file parsing
│   ├── grid.py               # Grid-snapping segment detection
│   └── storage.py            # favtracks.db access layer
├── templates/
│   └── index.html
└── static/
    ├── style.css
    └── app.js
```

## License

MIT
