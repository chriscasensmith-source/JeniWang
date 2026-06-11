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


def _mark_key(item_number, supplier, request_date) -> str:
    return f"{item_number}|{supplier or ''}|{request_date or ''}"


def load_marks(conn: sqlite3.Connection) -> dict[str, dict]:
    """Latest 'ordered' mark per (item, supplier, request date). The table is
    append-only events; the most recent row per key wins."""
    marks: dict[str, dict] = {}
    for r in conn.execute("SELECT * FROM order_marks ORDER BY id").fetchall():
        key = _mark_key(r["item_number"], r["supplier"], r["request_date"])
        marks[key] = {"marked": bool(r["marked"]), "ts": r["ts"], "note": r["note"]}
    return marks


def add_mark(conn: sqlite3.Connection, *, item_number: str, supplier, request_date,
             marked: bool, note: str | None = None) -> None:
    conn.execute(
        "INSERT INTO order_marks (ts, item_number, supplier, request_date, marked, note) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.now().isoformat(timespec="seconds"), item_number,
         supplier, request_date, int(marked), note),
    )
    conn.commit()


def item_history(conn: sqlite3.Connection, item_number: str,
                 supplier: str | None = None) -> list[dict]:
    """That item's MRP messages across every stored snapshot, oldest first."""
    sql = (
        "SELECT s.snapshot_date, s.revision, m.msg_typ, m.request_date, "
        "       m.required_qty, m.lead_time, m.qa_days "
        "FROM mrp_lines m JOIN snapshots s ON s.id = m.snapshot_id "
        "WHERE m.item_number = ?"
    )
    params: list = [item_number]
    if supplier:
        sql += " AND m.supplier = ?"
        params.append(supplier)
    sql += " ORDER BY s.snapshot_date, s.revision, m.request_date"
    weeks: dict[tuple, dict] = {}
    for r in conn.execute(sql, params).fetchall():
        key = (r["snapshot_date"], r["revision"])
        week = weeks.setdefault(
            key, {"snapshot_date": r["snapshot_date"], "revision": r["revision"],
                  "messages": [], "total_qty": 0.0},
        )
        week["messages"].append({
            "msg_typ": r["msg_typ"], "request_date": r["request_date"],
            "qty": r["required_qty"],
        })
        week["total_qty"] += r["required_qty"] or 0.0
    return list(weeks.values())


def build_board(conn: sqlite3.Connection, cfg: dict,
                snapshot_id: int | None = None) -> dict | None:
    snapshot = get_snapshot(conn, snapshot_id)
    if snapshot is None:
        return None
    lines = computed_lines(conn, snapshot, cfg)
    marks = load_marks(conn)
    for line in lines:
        rd = line.get("request_date")
        key = _mark_key(line["item_number"], line.get("supplier"),
                        rd.isoformat() if rd else None)
        line["ordered"] = marks.get(key, {}).get("marked", False)
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
