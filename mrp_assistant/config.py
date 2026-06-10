"""config.yaml handling: created with defaults on first run, merged over defaults."""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

DEFAULTS: dict = {
    "yellow_window_days": 21,
    "green_window_days": 60,
    "consolidation_horizon_days": 90,
    "tier_bump_tolerance_pct": 0,
    "actionable_msg_types": ["O", "B", "T"],
    "suppliers": {},
}

CONFIG_TEMPLATE = """\
# MRP Ordering Assistant configuration.
# Status buckets (days of slack vs the effective deadline):
#   RED     slack < 0                          -> should have ordered already
#   YELLOW  0 <= slack <= yellow_window_days   -> order now
#   GREEN   yellow < slack <= green_window_days -> coming up soon
#   (none)  slack > green_window_days          -> early
yellow_window_days: 21
green_window_days: 60

# Tier consolidation: aggregate messages whose effective deadlines fall within
# this many days of the earliest one for the same (supplier, item).
consolidation_horizon_days: 90

# Recommend bumping to the next tier when total extended cost at the higher
# tier <= total at the lower tier * (1 + tolerance/100).
tier_bump_tolerance_pct: 0

# Message types treated as actionable order lines.
actionable_msg_types: [O, B, T]

# Per-supplier overrides, keyed by supplier number, e.g.:
# suppliers:
#   "104374":
#     consolidation_horizon_days: 60
suppliers: {}
"""


def load_config(path: str | Path = "config.yaml") -> dict:
    """Load config.yaml, creating it with commented defaults on first run."""
    p = Path(path)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    cfg = copy.deepcopy(DEFAULTS)
    for key, value in data.items():
        if value is not None:
            cfg[key] = value
    return cfg


def supplier_override(cfg: dict, supplier_no: object) -> dict:
    overrides = cfg.get("suppliers") or {}
    return overrides.get(str(supplier_no), {}) or {}


def horizon_for_supplier(cfg: dict, supplier_no: object) -> int:
    return int(
        supplier_override(cfg, supplier_no).get(
            "consolidation_horizon_days", cfg["consolidation_horizon_days"]
        )
    )
