"""Core order-timing math. Reproduces the workbook's own logic:

    effective_deadline    = Request Date - QA Days   (the "ACTUAL REQUEST DATE")
    projected_dock_date   = order_date + Lead Time
    slack_days            = effective_deadline - projected_dock_date
    last_safe_order_date  = effective_deadline - Lead Time

The workbook's column P is snapshot_date + Lead Time compared against the
QA-adjusted date in column F — mathematically the same slack.
"""
from __future__ import annotations

from datetime import date, timedelta

STATUS_RED = "RED"
STATUS_YELLOW = "YELLOW"
STATUS_GREEN = "GREEN"
STATUS_NONE = "NONE"


def bucket(slack_days: int | None, cfg: dict) -> str | None:
    if slack_days is None:
        return None
    if slack_days < 0:
        return STATUS_RED
    if slack_days <= cfg["yellow_window_days"]:
        return STATUS_YELLOW
    if slack_days <= cfg["green_window_days"]:
        return STATUS_GREEN
    return STATUS_NONE


def compute_line(line: dict, snapshot_date: date, today: date, cfg: dict) -> dict:
    """Augment a raw mrp_lines row (as a dict with date objects) with every
    derived field, in both order-date modes."""
    request_date = line.get("request_date")
    qa_days = line.get("qa_days")
    lead_time = line.get("lead_time")
    msg_typ = (line.get("msg_typ") or "").strip()

    effective_deadline = None
    last_safe_order_date = None
    if request_date is not None and qa_days is not None:
        effective_deadline = request_date - timedelta(days=qa_days)
        if lead_time is not None:
            last_safe_order_date = effective_deadline - timedelta(days=lead_time)

    out = dict(line)
    out["effective_deadline"] = effective_deadline
    out["last_safe_order_date"] = last_safe_order_date
    out["actionable"] = msg_typ in cfg["actionable_msg_types"]

    for mode, order_date in (("snapshot", snapshot_date), ("today", today)):
        projected_dock = None
        projected_arrival = None
        slack = None
        if lead_time is not None and order_date is not None:
            projected_dock = order_date + timedelta(days=lead_time)
            if qa_days is not None:
                projected_arrival = projected_dock + timedelta(days=qa_days)
            if effective_deadline is not None:
                slack = (effective_deadline - projected_dock).days
        status = bucket(slack, cfg) if out["actionable"] else None
        # T (Past Due) and B (Expedite) are late by definition; RED lines too.
        fire_drill = out["actionable"] and (
            msg_typ in ("T", "B") or status == STATUS_RED
        )
        out[mode] = {
            "order_date": order_date,
            "projected_dock_date": projected_dock,
            "projected_arrival_with_qa": projected_arrival,
            "slack_days": slack,
            "status": status,
            "fire_drill": fire_drill,
            "days_past_due": -slack if (slack is not None and slack < 0) else 0,
            "early_by_days": slack if (slack is not None and status == STATUS_NONE) else None,
        }
    return out
