"""Load and validate FavTracks TOML configuration."""

import logging
import os
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

log = logging.getLogger("favtracks")

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


def load_config(path: str | None = None) -> dict:
    path = path or os.environ.get("CONFIG_FILE", "config.toml")
    try:
        with open(path, "rb") as f:
            cfg = tomllib.load(f)
    except FileNotFoundError:
        sys.exit(f"Config file not found: {path} — copy config.toml.example to config.toml and adjust paths.")
    except tomllib.TOMLDecodeError as exc:
        sys.exit(f"Invalid TOML in {path}: {exc}")

    storage = cfg.get("storage", {})
    detection = cfg.get("detection", {})
    server = cfg.get("server", {})
    log_cfg = cfg.get("logging", {})

    log_level = log_cfg.get("level", "INFO").upper()
    if log_level not in _VALID_LOG_LEVELS:
        sys.exit(f"Invalid log level '{log_level}' in config. Must be one of: {', '.join(sorted(_VALID_LOG_LEVELS))}")

    return {
        "garmin_db_path": storage.get("garmin_db_path", "/data/garmin_nostra.db"),
        "favtracks_db_path": storage.get("favtracks_db_path", "/data/favtracks.db"),
        "gpx_base_dir": storage.get("gpx_base_dir"),
        "running_grid_m": detection.get("running_grid_m", 20),
        "cycling_grid_m": detection.get("cycling_grid_m", 50),
        "log_level": log_level,
        "host": server.get("host", "0.0.0.0"),
        "port": server.get("port", 5000),
    }


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
