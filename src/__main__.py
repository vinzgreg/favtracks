"""CLI entry point for FavTracks.

Usage:
    python -m favtracks serve         Start the web server (default)
    python -m favtracks recompute     Full recompute of all grid sequences
    python -m favtracks incremental   Process only new activities
"""

import sys

from src.config import load_config, setup_logging


def main():
    config = load_config()
    setup_logging(config["log_level"])

    command = sys.argv[1] if len(sys.argv) > 1 else "serve"

    if command == "recompute":
        from src.compute import recompute_all
        summary = recompute_all(config)
        print(f"Done: {summary['processed']} processed, {summary['skipped']} skipped, {summary['errors']} errors")

    elif command == "incremental":
        from src.compute import compute_incremental
        summary = compute_incremental(config)
        print(f"Done: {summary['processed']} new, {summary['skipped']} skipped, {summary['errors']} errors")

    elif command == "serve":
        from src.app import create_app
        app = create_app(config)
        app.run(host=config["host"], port=config["port"])

    else:
        print(f"Unknown command: {command}")
        print("Usage: python -m favtracks [serve|recompute|incremental]")
        sys.exit(1)


if __name__ == "__main__":
    main()
