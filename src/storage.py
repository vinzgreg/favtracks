"""FavTracks SQLite storage for precomputed grid sequences."""

import json
import logging
import sqlite3

log = logging.getLogger("favtracks.storage")

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS grid_sequences (
    activity_id   INTEGER PRIMARY KEY,
    activity_type TEXT    NOT NULL,
    category      TEXT    NOT NULL,
    grid_cells    TEXT    NOT NULL,
    computed_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gs_category ON grid_sequences(category);
"""


class FavTracksStore:

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            log.debug("Opening favtracks DB: %s", self._db_path)
            conn = sqlite3.connect(self._db_path, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            conn.executescript(_SCHEMA)
            self._conn = conn
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def upsert_grid_sequence(self, activity_id: int, activity_type: str,
                             category: str, grid_cells: list[tuple[int, int]],
                             computed_at: str) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO grid_sequences "
            "(activity_id, activity_type, category, grid_cells, computed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (activity_id, activity_type, category, json.dumps(grid_cells), computed_at),
        )
        conn.commit()

    def get_all_sequences(self, category: str | None = None) -> list[dict]:
        conn = self._connect()
        if category:
            rows = conn.execute(
                "SELECT activity_id, activity_type, category, grid_cells "
                "FROM grid_sequences WHERE category = ?",
                (category,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT activity_id, activity_type, category, grid_cells "
                "FROM grid_sequences"
            ).fetchall()
        return [
            {
                "activity_id": r["activity_id"],
                "activity_type": r["activity_type"],
                "category": r["category"],
                "grid_cells": json.loads(r["grid_cells"]),
            }
            for r in rows
        ]

    def get_computed_activity_ids(self) -> set[int]:
        conn = self._connect()
        rows = conn.execute("SELECT activity_id FROM grid_sequences").fetchall()
        return {r["activity_id"] for r in rows}

    def delete_all(self) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM grid_sequences")
        conn.commit()
        log.info("Cleared all grid sequences from favtracks DB")
