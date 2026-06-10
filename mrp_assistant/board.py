"""Assemble the per-snapshot 'board': computed lines, tier cards, diff."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

from . import db as dbmod
from .calc import compute_line
from .diff import load_diff
from .tiers import build_ladders, tier_cards


def _iso_to_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def get_snapshot(conn: sqlite3.Connection, snapshot_id: int | None):
    if snapshot_id is None:
        return conn.execute(
            "SELECT * FROM snapshots ORDER BY snapshot_date DESC, revision DESC LIMIT 1"
        ).fetchone()
    return conn.execute(
        "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
    ).fetchone()


def list_snapshots(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT s.*, u.filename, u.ts AS ingested_at FROM snapshots s "
        "JOIN uploads u ON u.id = s.upload_id "
        "ORDER BY s.snapshot_date DESC, s.revision DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def load_tier_ladders(conn: sqlite3.Connection) -> dict:
    upload_id = dbmod.latest_reference_upload_id(conn, "tier_rows")
    if upload_id is None:
        return {}
    rows = conn.execute(
        "SELECT * FROM tier_rows WHERE upload_id = ?", (upload_id,)
    ).fetchall()
    return build_ladders([dict(r) for r in rows])


def load_suppliers(conn: sqlite3.Connection) -> dict[str, dict]:
    upload_id = dbmod.latest_reference_upload_id(conn, "suppliers")
    if upload_id is None:
        return {}
    rows = conn.execute(
        "SELECT * FROM suppliers WHERE upload_id = ?", (upload_id,)
    ).fetchall()
    return {
        r["number"]: {
            "name": r["name"],
            "coo": r["coo"],
            "branches": json.loads(r["branches"] or "[]"),
        }
        for r in rows
        if r["number"]
    }


def computed_lines(conn: sqlite3.Connection, snapshot, cfg: dict,
                   today: date | None = None) -> list[dict]:
    today = today or date.today()
    snapshot_date = _iso_to_date(snapshot["snapshot_date"])
    out = []
    for row in conn.execute(
        "SELECT * FROM mrp_lines WHERE snapshot_id = ? ORDER BY row_id",
        (snapshot["id"],),
    ).fetchall():
        line = dict(row)
        line["line_id"] = line.pop("id")
        for f in ("request_date", "qa_request_date", "actual_request_date"):
            line[f] = _iso_to_date(line[f])
        out.append(compute_line(line, snapshot_date, today, cfg))
    return out


def build_board(conn: sqlite3.Connection, cfg: dict,
                snapshot_id: int | None = None) -> dict | None:
    snapshot = get_snapshot(conn, snapshot_id)
    if snapshot is None:
        return None
    lines = computed_lines(conn, snapshot, cfg)
    ladders = load_tier_ladders(conn)
    cards = tier_cards(lines, ladders, cfg)
    return {
        "snapshot": dict(snapshot),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "today": date.today().isoformat(),
        "config": {k: v for k, v in cfg.items() if k != "suppliers"},
        "lines": lines,
        "tier_cards": cards,
        "diff": load_diff(conn, snapshot["id"]),
        "suppliers": load_suppliers(conn),
    }
