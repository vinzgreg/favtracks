"""Check which activities have a gpx_path in the DB but no file on disk.

Usage:
    python check_missing_gpx.py [--db PATH] [--gpx-root PATH]

Defaults:
    --db        ~/data/garminnostra/garmin_nostra.db
    --gpx-root  ~/data/garminnostra   (paths in DB are like /data/gpx/... so
                                       /data maps to this root)
"""

import argparse
import os
import sqlite3
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Find activities with missing GPX files")
    parser.add_argument("--db", default=os.path.expanduser("~/data/garminnostra/garmin_nostra.db"))
    parser.add_argument("--gpx-root", default=os.path.expanduser("~/data/garminnostra"),
                        help="Host directory that is mounted as /data inside the container")
    args = parser.parse_args()

    db_path = Path(args.db)
    gpx_root = Path(args.gpx_root)

    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}")
        return

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, garmin_activity_id, activity_name, activity_type, "
        "start_time_local, gpx_path "
        "FROM activities "
        "WHERE gpx_path IS NOT NULL AND gpx_path != '' "
        "ORDER BY start_time_local"
    ).fetchall()
    conn.close()

    total = len(rows)
    missing = []

    for row in rows:
        # gpx_path is like /data/gpx/vinz/12345.gpx
        # map /data -> gpx_root
        rel = row["gpx_path"].lstrip("/")          # data/gpx/vinz/12345.gpx
        rel = rel[len("data/"):]                   # gpx/vinz/12345.gpx
        host_path = gpx_root / rel

        if not host_path.exists():
            missing.append({
                "id": row["id"],
                "garmin_id": row["garmin_activity_id"],
                "name": row["activity_name"],
                "type": row["activity_type"],
                "date": row["start_time_local"],
                "expected_path": host_path,
            })

    print(f"Total activities with gpx_path in DB : {total}")
    print(f"Missing GPX files on disk             : {len(missing)}")
    print(f"Already present                        : {total - len(missing)}")

    if not missing:
        print("\nAll GPX files are present — nothing to backfill.")
        return

    print("\nMissing files (oldest first):")
    print(f"{'Date':<22} {'Type':<20} {'Garmin ID':<15} Name")
    print("-" * 90)
    for m in missing:
        date = m["date"] or ""
        atype = (m["type"] or "")[:19]
        name = (m["name"] or "")[:40]
        print(f"{date:<22} {atype:<20} {m['garmin_id']:<15} {name}")

    # Write a plain list of Garmin activity IDs for easy scripting
    out_file = Path("missing_gpx_ids.txt")
    with open(out_file, "w") as f:
        for m in missing:
            f.write(m["garmin_id"] + "\n")
    print(f"\nGarmin activity IDs written to: {out_file}")
    print("Use these IDs to download GPX files from Garmin Connect.")


if __name__ == "__main__":
    main()
