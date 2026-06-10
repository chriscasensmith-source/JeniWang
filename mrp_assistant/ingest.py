"""Ingest pipeline: archive the original file, parse, store append-only,
compute week-over-week diffs, and log everything in the uploads table."""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import db as dbmod
from . import diff as diffmod
from .parsing import ParsedSheet, parse_workbook

DEFAULT_ARCHIVE_DIR = Path("archive") / "originals"


@dataclass
class IngestResult:
    status: str                      # 'ingested' | 'duplicate, skipped'
    upload_id: int
    archive_path: str | None = None
    snapshots: list[dict] = field(default_factory=list)  # created snapshots
    skipped_sheets: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _log_upload(conn, *, filename, sha256, status, snapshot_dates=None,
                row_counts=None, warnings=None, archive_path=None) -> int:
    cur = conn.execute(
        """INSERT INTO uploads (ts, filename, sha256, status, snapshot_dates,
               row_counts, warnings, archive_path)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now().isoformat(timespec="seconds"),
            filename, sha256, status,
            json.dumps(snapshot_dates or []),
            json.dumps(row_counts or {}),
            json.dumps(warnings or []),
            archive_path,
        ),
    )
    return cur.lastrowid


def _store_sheet(conn, upload_id: int, sheet: ParsedSheet) -> dict:
    iso = sheet.snapshot_date.isoformat()
    row = conn.execute(
        "SELECT COALESCE(MAX(revision), 0) AS r FROM snapshots WHERE snapshot_date = ?",
        (iso,),
    ).fetchone()
    revision = row["r"] + 1
    cur = conn.execute(
        """INSERT INTO snapshots (snapshot_date, revision, upload_id, source_tab,
               sheet_hash, row_count) VALUES (?, ?, ?, ?, ?, ?)""",
        (iso, revision, upload_id, sheet.tab, sheet.content_hash, len(sheet.lines)),
    )
    snapshot_id = cur.lastrowid
    conn.executemany(
        """INSERT INTO mrp_lines (snapshot_id, row_id, msg_typ, item_number,
               description, lead_time, qa_request_date, actual_request_date,
               request_date, required_qty, order_number, supplier,
               supplier_name, message, or_ty, qa_days, demand_branch)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                snapshot_id, ln.row_id, ln.msg_typ, ln.item_number,
                ln.description, ln.lead_time,
                ln.qa_request_date.isoformat() if ln.qa_request_date else None,
                ln.actual_request_date.isoformat() if ln.actual_request_date else None,
                ln.request_date.isoformat() if ln.request_date else None,
                ln.required_qty, ln.order_number, ln.supplier, ln.supplier_name,
                ln.message, ln.or_ty, ln.qa_days, ln.demand_branch,
            )
            for ln in sheet.lines
        ],
    )
    # Week-over-week diff, computed on ingest.
    prev = dbmod.latest_snapshot_before(conn, iso, revision)
    if prev is not None:
        rows = diffmod.compute_diff(conn, snapshot_id, prev["id"])
        diffmod.store_diff(conn, snapshot_id, prev["id"], rows)
    return {
        "snapshot_id": snapshot_id,
        "snapshot_date": iso,
        "revision": revision,
        "tab": sheet.tab,
        "row_count": len(sheet.lines),
        "diff_vs": prev["snapshot_date"] if prev else None,
    }


def _store_reference_tables(conn, upload_id: int, parsed) -> None:
    if parsed.tier_rows:
        conn.executemany(
            """INSERT INTO tier_rows (upload_id, supplier_name, supplier_no,
                   item_no, item_name, tier_str, tier_qty, pricing,
                   pricing_year, notes, incomplete, incomplete_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    upload_id, t.supplier_name, t.supplier_no, t.item_no,
                    t.item_name, t.tier_str, t.tier_qty, t.pricing,
                    t.pricing_year, t.notes, int(t.incomplete), t.incomplete_reason,
                )
                for t in parsed.tier_rows
            ],
        )
    if parsed.suppliers:
        conn.executemany(
            "INSERT INTO suppliers (upload_id, coo, name, number, branches) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (upload_id, s.coo, s.name, s.number, json.dumps(s.branches))
                for s in parsed.suppliers
            ],
        )


def ingest_file(
    path: str | Path,
    *,
    all_tabs: bool = False,
    tab: str | None = None,
    db_path: str | Path = dbmod.DEFAULT_DB_PATH,
    archive_dir: str | Path = DEFAULT_ARCHIVE_DIR,
    force: bool = False,
) -> IngestResult:
    """Ingest a weekly workbook.

    Default: ingest the most recent dated tab (the weekly upload case).
    all_tabs=True: backfill every dated tab. tab="05.29.26": one specific tab.
    """
    path = Path(path)
    conn = dbmod.connect(db_path)
    try:
        sha = file_sha256(path)
        # Idempotency: refuse duplicate ingestion of an identical hash, but
        # still log the attempt.
        dup = conn.execute(
            "SELECT id FROM uploads WHERE sha256 = ? AND status = 'ingested'", (sha,)
        ).fetchone()
        if dup is not None and not force:
            upload_id = _log_upload(
                conn, filename=path.name, sha256=sha, status="duplicate, skipped",
                warnings=[f"identical to upload #{dup['id']}; nothing ingested"],
            )
            conn.commit()
            return IngestResult(status="duplicate, skipped", upload_id=upload_id)

        parsed = parse_workbook(path)
        if not parsed.weekly_sheets:
            raise ValueError(f"{path.name}: no dated weekly tabs found")

        if all_tabs:
            sheets = parsed.weekly_sheets  # already sorted oldest -> newest
        elif tab is not None:
            sheets = [s for s in parsed.weekly_sheets if s.tab == tab]
            if not sheets:
                available = ", ".join(s.tab for s in parsed.weekly_sheets)
                raise ValueError(f"tab {tab!r} not found; dated tabs: {available}")
        else:
            sheets = [parsed.weekly_sheets[-1]]  # latest snapshot date

        warnings = list(parsed.warnings)

        # Archive the original file unmodified before touching the database.
        archive_dir = Path(archive_dir)
        archive_dir.mkdir(parents=True, exist_ok=True)
        latest_date = max(s.snapshot_date for s in sheets).isoformat()
        archive_path = archive_dir / f"{latest_date}__{sha[:12]}{path.suffix}"
        if not archive_path.exists():
            shutil.copy2(path, archive_path)

        upload_id = _log_upload(
            conn, filename=path.name, sha256=sha, status="ingested",
            archive_path=str(archive_path),
        )
        _store_reference_tables(conn, upload_id, parsed)

        snapshots: list[dict] = []
        skipped_sheets: list[str] = []
        row_counts: dict[str, int] = {}
        for sheet in sheets:
            iso = sheet.snapshot_date.isoformat()
            # Same snapshot date + identical content = nothing new; a changed
            # file for the same date becomes a new revision (both kept).
            existing = conn.execute(
                "SELECT id FROM snapshots WHERE snapshot_date = ? AND sheet_hash = ?",
                (iso, sheet.content_hash),
            ).fetchone()
            if existing is not None:
                skipped_sheets.append(sheet.tab)
                warnings.append(
                    f"[{sheet.tab}] identical content already stored for "
                    f"{iso} (snapshot #{existing['id']}); skipped"
                )
                continue
            info = _store_sheet(conn, upload_id, sheet)
            snapshots.append(info)
            row_counts[iso] = info["row_count"]

        conn.execute(
            "UPDATE uploads SET snapshot_dates = ?, row_counts = ?, warnings = ? WHERE id = ?",
            (
                json.dumps([s["snapshot_date"] for s in snapshots]),
                json.dumps(row_counts),
                json.dumps(warnings),
                upload_id,
            ),
        )
        conn.commit()
        return IngestResult(
            status="ingested",
            upload_id=upload_id,
            archive_path=str(archive_path),
            snapshots=snapshots,
            skipped_sheets=skipped_sheets,
            warnings=warnings,
        )
    finally:
        conn.close()
