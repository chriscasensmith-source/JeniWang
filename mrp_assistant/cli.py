"""Command line entry points:

    mrp ingest <file.xlsm>             ingest the latest dated tab
    mrp ingest --all-tabs <file.xlsm>  backfill every dated tab
    mrp serve                          launch the dashboard at localhost
"""
from __future__ import annotations

import argparse
import sys

from . import db as dbmod
from .config import load_config
from .ingest import DEFAULT_ARCHIVE_DIR, ingest_file


def cmd_ingest(args) -> int:
    result = ingest_file(
        args.file,
        all_tabs=args.all_tabs,
        tab=args.tab,
        db_path=args.db,
        archive_dir=args.archive_dir,
        force=args.force,
    )
    print(f"upload #{result.upload_id}: {result.status}")
    if result.status == "duplicate, skipped":
        print("  identical file already ingested; nothing changed (use --force to override)")
        return 0
    print(f"  archived original -> {result.archive_path}")
    for s in result.snapshots:
        diff_note = f", diff vs {s['diff_vs']}" if s["diff_vs"] else ", no earlier snapshot to diff"
        print(
            f"  snapshot {s['snapshot_date']} rev {s['revision']} "
            f"(tab {s['tab']!r}): {s['row_count']} rows{diff_note}"
        )
    for tab in result.skipped_sheets:
        print(f"  tab {tab!r}: unchanged since last ingest, skipped")
    for w in result.warnings:
        print(f"  WARNING: {w}")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from .server import create_app

    load_config(args.config)  # create config.yaml with defaults on first run
    app = create_app(db_path=args.db, config_path=args.config)
    print(f"MRP Ordering Assistant -> http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mrp", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="ingest a weekly MRP workbook")
    p_ingest.add_argument("file", help="path to the .xlsm export")
    p_ingest.add_argument("--all-tabs", action="store_true",
                          help="backfill: ingest every dated tab in the workbook")
    p_ingest.add_argument("--tab", help="ingest one specific tab (e.g. 05.29.26)")
    p_ingest.add_argument("--db", default=str(dbmod.DEFAULT_DB_PATH))
    p_ingest.add_argument("--archive-dir", default=str(DEFAULT_ARCHIVE_DIR))
    p_ingest.add_argument("--force", action="store_true",
                          help="re-ingest even if this exact file was already ingested")
    p_ingest.set_defaults(func=cmd_ingest)

    p_serve = sub.add_parser("serve", help="launch the dashboard")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--db", default=str(dbmod.DEFAULT_DB_PATH))
    p_serve.add_argument("--config", default="config.yaml")
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
