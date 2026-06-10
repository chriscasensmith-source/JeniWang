"""Week-over-week diff, keyed on (Item Number, Supplier, Request Date) with
qty tolerance 0. Every diff row stores the mrp_lines ids it came from."""
from __future__ import annotations

import json
import sqlite3


def _grouped_lines(conn: sqlite3.Connection, snapshot_id: int) -> dict:
    groups: dict[tuple, dict] = {}
    rows = conn.execute(
        "SELECT id, item_number, supplier, supplier_name, request_date, required_qty "
        "FROM mrp_lines WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchall()
    for row in rows:
        key = (row["item_number"], row["supplier"], row["request_date"])
        group = groups.setdefault(
            key, {"qty": 0.0, "line_ids": [], "supplier_name": row["supplier_name"]}
        )
        group["qty"] += row["required_qty"] or 0.0
        group["line_ids"].append(row["id"])
    return groups


def compute_diff(conn: sqlite3.Connection, snapshot_id: int, prev_snapshot_id: int) -> list[dict]:
    """Compute NEW / RESOLVED / CHANGED rows between two snapshots."""
    new_groups = _grouped_lines(conn, snapshot_id)
    old_groups = _grouped_lines(conn, prev_snapshot_id)
    out: list[dict] = []
    for key, group in sorted(new_groups.items(), key=lambda kv: (kv[0][0], kv[0][2] or "")):
        item, supplier, request_date = key
        old = old_groups.get(key)
        if old is None:
            out.append({
                "kind": "NEW", "item_number": item, "supplier": supplier,
                "supplier_name": group["supplier_name"], "request_date": request_date,
                "old_qty": None, "new_qty": group["qty"],
                "old_line_ids": [], "new_line_ids": group["line_ids"],
            })
        elif old["qty"] != group["qty"]:  # tolerance 0
            out.append({
                "kind": "CHANGED", "item_number": item, "supplier": supplier,
                "supplier_name": group["supplier_name"], "request_date": request_date,
                "old_qty": old["qty"], "new_qty": group["qty"],
                "old_line_ids": old["line_ids"], "new_line_ids": group["line_ids"],
            })
    for key, old in sorted(old_groups.items(), key=lambda kv: (kv[0][0], kv[0][2] or "")):
        if key not in new_groups:
            item, supplier, request_date = key
            out.append({
                "kind": "RESOLVED", "item_number": item, "supplier": supplier,
                "supplier_name": old["supplier_name"], "request_date": request_date,
                "old_qty": old["qty"], "new_qty": None,
                "old_line_ids": old["line_ids"], "new_line_ids": [],
            })
    return out


def store_diff(conn: sqlite3.Connection, snapshot_id: int, prev_snapshot_id: int,
               rows: list[dict]) -> None:
    conn.execute(
        "DELETE FROM diffs WHERE snapshot_id = ? AND prev_snapshot_id = ?",
        (snapshot_id, prev_snapshot_id),
    )
    conn.executemany(
        """INSERT INTO diffs (snapshot_id, prev_snapshot_id, kind, item_number,
               supplier, supplier_name, request_date, old_qty, new_qty,
               old_line_ids, new_line_ids)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                snapshot_id, prev_snapshot_id, r["kind"], r["item_number"],
                r["supplier"], r["supplier_name"], r["request_date"],
                r["old_qty"], r["new_qty"],
                json.dumps(r["old_line_ids"]), json.dumps(r["new_line_ids"]),
            )
            for r in rows
        ],
    )


def load_diff(conn: sqlite3.Connection, snapshot_id: int) -> dict | None:
    rows = conn.execute(
        "SELECT * FROM diffs WHERE snapshot_id = ? ORDER BY kind, item_number",
        (snapshot_id,),
    ).fetchall()
    if not rows:
        return None
    prev_id = rows[0]["prev_snapshot_id"]
    prev = conn.execute("SELECT * FROM snapshots WHERE id = ?", (prev_id,)).fetchone()
    return {
        "prev_snapshot_id": prev_id,
        "prev_snapshot_date": prev["snapshot_date"] if prev else None,
        "rows": [
            {
                "kind": r["kind"],
                "item_number": r["item_number"],
                "supplier": r["supplier"],
                "supplier_name": r["supplier_name"],
                "request_date": r["request_date"],
                "old_qty": r["old_qty"],
                "new_qty": r["new_qty"],
                "old_line_ids": json.loads(r["old_line_ids"]),
                "new_line_ids": json.loads(r["new_line_ids"]),
            }
            for r in rows
        ],
    }
