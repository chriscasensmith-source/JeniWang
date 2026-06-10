"""SQLite storage. mrp_lines is append-only: rows are keyed by
(snapshot_date, revision, row_id) and never updated in place."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path("data") / "mrp.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL,            -- 'ingested' | 'duplicate, skipped'
    snapshot_dates TEXT,             -- JSON list of ISO dates found
    row_counts TEXT,                 -- JSON {iso_date: row_count}
    warnings TEXT,                   -- JSON list of parse warnings
    archive_path TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    snapshot_date TEXT NOT NULL,
    revision INTEGER NOT NULL,
    upload_id INTEGER NOT NULL REFERENCES uploads(id),
    source_tab TEXT NOT NULL,
    sheet_hash TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    UNIQUE (snapshot_date, revision)
);

CREATE TABLE IF NOT EXISTS mrp_lines (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    row_id INTEGER NOT NULL,         -- source row number in the worksheet
    msg_typ TEXT NOT NULL,
    item_number TEXT NOT NULL,
    description TEXT,
    lead_time INTEGER,
    qa_request_date TEXT,
    actual_request_date TEXT,
    request_date TEXT,
    required_qty REAL,
    order_number TEXT,
    supplier TEXT,
    supplier_name TEXT,
    message TEXT,
    or_ty TEXT,
    qa_days INTEGER,
    demand_branch TEXT,
    UNIQUE (snapshot_id, row_id)
);

CREATE TABLE IF NOT EXISTS tier_rows (
    id INTEGER PRIMARY KEY,
    upload_id INTEGER NOT NULL REFERENCES uploads(id),
    supplier_name TEXT,
    supplier_no TEXT,
    item_no TEXT,
    item_name TEXT,
    tier_str TEXT,
    tier_qty INTEGER,
    pricing REAL,
    pricing_year INTEGER,
    notes TEXT,
    incomplete INTEGER NOT NULL DEFAULT 0,
    incomplete_reason TEXT
);

CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY,
    upload_id INTEGER NOT NULL REFERENCES uploads(id),
    coo TEXT,
    name TEXT,
    number TEXT,
    branches TEXT                    -- JSON list
);

CREATE TABLE IF NOT EXISTS diffs (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    prev_snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    kind TEXT NOT NULL,              -- 'NEW' | 'RESOLVED' | 'CHANGED'
    item_number TEXT,
    supplier TEXT,
    supplier_name TEXT,
    request_date TEXT,
    old_qty REAL,
    new_qty REAL,
    old_line_ids TEXT,               -- JSON list of mrp_lines.id (traceability)
    new_line_ids TEXT
);

CREATE INDEX IF NOT EXISTS idx_lines_snapshot ON mrp_lines(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_diffs_snapshot ON diffs(snapshot_id);
"""


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def latest_snapshot_before(conn: sqlite3.Connection, snapshot_date: str, revision: int):
    """The snapshot that precedes (snapshot_date, revision) in time order;
    used as the diff baseline."""
    return conn.execute(
        """
        SELECT * FROM snapshots
        WHERE snapshot_date < ? OR (snapshot_date = ? AND revision < ?)
        ORDER BY snapshot_date DESC, revision DESC LIMIT 1
        """,
        (snapshot_date, snapshot_date, revision),
    ).fetchone()


def latest_reference_upload_id(conn: sqlite3.Connection, table: str) -> int | None:
    row = conn.execute(f"SELECT MAX(upload_id) AS u FROM {table}").fetchone()
    return row["u"] if row else None
