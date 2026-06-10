"""FastAPI app serving the single-page dashboard and JSON/export endpoints.
Everything runs offline on localhost; no auth."""
from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response

from . import db as dbmod
from .board import build_board, list_snapshots
from .config import load_config
from .export import diff_xlsx, worksheet_xlsx

STATIC_DIR = Path(__file__).parent / "static"


def create_app(db_path=dbmod.DEFAULT_DB_PATH, config_path="config.yaml") -> FastAPI:
    app = FastAPI(title="MRP Ordering Assistant")

    def conn():
        # sqlite3's context manager commits but never closes; closing() does.
        return closing(dbmod.connect(db_path))

    def cfg():
        return load_config(config_path)

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/meta")
    def meta():
        with conn() as c:
            return {"snapshots": list_snapshots(c), "config": cfg()}

    @app.get("/api/board")
    def board(snapshot_id: int | None = Query(default=None)):
        with conn() as c:
            data = build_board(c, cfg(), snapshot_id)
        if data is None:
            raise HTTPException(404, "no snapshots ingested yet — run: mrp ingest <file.xlsm>")
        return data

    @app.get("/api/uploads")
    def uploads():
        with conn() as c:
            rows = c.execute("SELECT * FROM uploads ORDER BY id DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for f in ("snapshot_dates", "row_counts", "warnings"):
                d[f] = json.loads(d[f] or "null")
            out.append(d)
        return out

    def _xlsx_response(content: bytes, filename: str) -> Response:
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/export/worksheet")
    def export_worksheet(snapshot_id: int | None = None, mode: str = "snapshot"):
        if mode not in ("snapshot", "today"):
            raise HTTPException(400, "mode must be 'snapshot' or 'today'")
        with conn() as c:
            data = build_board(c, cfg(), snapshot_id)
        if data is None:
            raise HTTPException(404, "no snapshots ingested yet")
        stamp = data["generated_at"].replace(":", "-")
        name = f"worksheet_{data['snapshot']['snapshot_date']}_as-of-{mode}_{stamp}.xlsx"
        return _xlsx_response(worksheet_xlsx(data, mode), name)

    @app.get("/api/export/diff")
    def export_diff(snapshot_id: int | None = None):
        with conn() as c:
            data = build_board(c, cfg(), snapshot_id)
        if data is None:
            raise HTTPException(404, "no snapshots ingested yet")
        stamp = data["generated_at"].replace(":", "-")
        name = f"diff_{data['snapshot']['snapshot_date']}_{stamp}.xlsx"
        return _xlsx_response(diff_xlsx(data), name)

    return app
