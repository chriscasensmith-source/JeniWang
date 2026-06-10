# MRP Ordering Assistant

A local tool for the weekly JDE MRP-message workflow. On each weekly upload it
answers, per SKU:

1. **If I place this order today, when does it arrive?**
2. **Does that make me late, on-time, or early — and by how many days?**
3. **What quantity should I actually order, given supplier price tiers?**

…and keeps an auditable paper trail of every upload. Everything runs offline
on one machine: SQLite storage, FastAPI + a single static HTML dashboard, no
cloud, no auth, no JS frameworks.

## The weekly routine (no terminal needed)

1. Export the MRP messages from JDE into the Excel workbook (.xlsm), as usual.
2. Double-click **`Start MRP Dashboard.bat`** (Windows) or
   **`start-mrp-dashboard.command`** (Mac). The browser opens by itself.
3. **Drag the .xlsm file anywhere onto the page** (or click
   "Ingest this week's workbook…"). Done — the new week appears, archived
   and diffed.

Ingest archives the original file, parses the latest weekly tab, stores every
line append-only, and computes the week-over-week diff. The dashboard shows
the fire drill, the order-now list with tier consolidation math, the horizon,
and the diff. Dropping the same file twice is harmless — duplicates are
detected by hash and skipped.

The same things work from a terminal if you prefer:

```
mrp ingest JW_MRP_2026.xlsm           # ingests the newest dated tab
mrp serve                             # open http://127.0.0.1:8000
```

## Install (one time)

Install Python 3.11+ from python.org (on Windows, check **"Add python.exe to
PATH"** in the installer), then double-click the launcher above — it installs
the tool automatically on first run. Or manually:

```
python -m pip install -e .
```

This installs the `mrp` command (openpyxl, pandas, FastAPI, uvicorn, PyYAML).
`python -m mrp_assistant …` works as an equivalent to `mrp …`.

## Commands

| Command | What it does |
|---|---|
| `mrp ingest <file.xlsm>` | Ingest the most recent dated weekly tab |
| `mrp ingest --all-tabs <file.xlsm>` | Backfill: ingest **every** dated tab (load the 2026 history) |
| `mrp ingest --tab 05.29.26 <file.xlsm>` | Ingest one specific tab |
| `mrp ingest --force …` | Re-ingest a file whose exact hash was already ingested |
| `mrp serve [--port 8000]` | Launch the dashboard at localhost |

## What the math is

For every actionable line (Msg Typ `O`/`B`/`T` by default):

```
effective_deadline   = Request Date − QA Days     (the "ACTUAL REQUEST DATE")
projected_dock_date  = order_date + Lead Time
slack_days           = effective_deadline − projected_dock_date
last_safe_order_date = effective_deadline − Lead Time   ← the "order by" date
```

This reproduces the workbook's own column P/Q logic exactly (verified by
tests against the real file). Two order-date modes are always available:
**as of snapshot** (the JDE pull date, default for historical sheets) and
**as of today**.

Status buckets (thresholds in `config.yaml`):

| Color | Slack | Meaning |
|---|---|---|
| RED | `< 0` | should have ordered already (late by N days) |
| YELLOW | `0–21` | order now |
| GREEN | `22–60` | coming up soon (subtle — an extension over the old sheet) |
| none | `> 60` | early by N days |

`T` (Past Due) and `B` (Expedite) lines always go to the fire-drill section.

## Tier recommendations

For each (supplier, item) with actionable messages, quantities are aggregated
across messages whose effective deadlines fall within the consolidation
horizon (default 90 days, per-supplier overridable). The card shows the tier
the aggregate lands in, extended cost, and the full bump-up math for the next
tier (units short, incremental cost at both prices, savings). A bump is only
*recommended* when the total at the higher tier ≤ total at the lower tier
(plus tolerance) — but the math is always displayed; the human decides.
`TBD`/`VARIOUS`/missing tier data is flagged "request pricing"; prices are
never invented. Every card lists exactly which MRP messages were consolidated.

## Paper trail

- Originals archived unmodified to `archive/originals/<snapshot>__<sha256>.xlsm`.
- Identical re-uploads are refused (logged as "duplicate, skipped"); a changed
  file for the same snapshot date becomes a new **revision** — both kept.
- Every parsed line stored append-only in SQLite (`data/mrp.db`), keyed by
  (snapshot_date, revision, row_id).
- Uploads log: timestamp, filename, hash, snapshot dates, row counts, warnings.
- Week-over-week diff (NEW / RESOLVED / CHANGED, keyed on item+supplier+request
  date) computed on ingest; every diff row traceable to source line ids.
- Export buttons on the dashboard produce stamped .xlsx files of the worksheet
  view and the diff.

## Configuration (`config.yaml`, created with defaults on first run)

```yaml
yellow_window_days: 21
green_window_days: 60
consolidation_horizon_days: 90
tier_bump_tolerance_pct: 0
actionable_msg_types: [O, B, T]
suppliers:            # per-supplier overrides by supplier number
  "104374":
    consolidation_horizon_days: 60
```

## Tests

Acceptance tests run against the real workbook at `fixtures/JW_MRP_2026.xlsm`
(not committed — drop your copy there):

```
python -m pytest
```

## Input format notes (ground truth from the real workbook)

- Weekly tabs are named `MM.DD.YY` (e.g. `05.29.26`, `2.20.26`). All other
  tabs are ignored for weekly ingest except `Standard Cost Tiers` and
  `SUPPLIERS`, which are parsed as reference tables.
- Columns are detected **by header name, never by position** (column count
  drifts week to week).
- The snapshot date is read from the cell to the right of the `Demand Branch`
  header; if missing, the tab name is used. A mismatch between the two is
  logged as a warning (the real workbook has one: tab `05.22.26` carries a
  header date of 2026-05-23).
- Subtotal rows (`… Count`, blank Msg Typ, SUBTOTAL leftovers) are skipped;
  whitespace is trimmed; formula cells are read as computed values and all
  derived fields are recomputed in Python.
