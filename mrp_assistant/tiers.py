"""Tier recommendation engine.

For each (supplier, item) with at least one actionable message: aggregate
Required Quantity within the consolidation horizon, place the aggregate on the
tier ladder, and show the next-tier bump math. The math is always displayed;
the bump is only *recommended* when total extended cost at the higher tier is
<= total at the lower tier (plus configured tolerance). Prices are never
invented: missing/TBD/VARIOUS tier data yields a "request pricing" flag.
"""
from __future__ import annotations

from datetime import timedelta

from .config import horizon_for_supplier


def build_ladders(tier_rows: list[dict]) -> dict:
    """Group tier rows into ladders keyed by (supplier_no, item_no).

    Keep the most recent Pricing Year as the active ladder; expose older
    years alongside. Incomplete rows are kept and flagged.
    """
    grouped: dict[tuple, list[dict]] = {}
    for row in tier_rows:
        key = (str(row["supplier_no"] or ""), str(row["item_no"] or ""))
        grouped.setdefault(key, []).append(row)

    ladders = {}
    for key, rows in grouped.items():
        years = [r["pricing_year"] for r in rows if r["pricing_year"] is not None]
        active_year = max(years) if years else None
        active = [r for r in rows if r["pricing_year"] == active_year]
        older = [r for r in rows if r["pricing_year"] != active_year]
        usable = sorted(
            (r for r in active if not r["incomplete"]),
            key=lambda r: r["tier_qty"],
        )
        incomplete_reasons = sorted(
            {r["incomplete_reason"] for r in active if r["incomplete"] and r["incomplete_reason"]}
        )
        ladders[key] = {
            "supplier_no": key[0],
            "item_no": key[1],
            "supplier_name": rows[0]["supplier_name"],
            "item_name": rows[0]["item_name"],
            "active_year": active_year,
            "tiers": [
                {"tier_str": r["tier_str"], "qty": r["tier_qty"], "price": r["pricing"]}
                for r in usable
            ],
            "incomplete": bool(incomplete_reasons) or not usable,
            "incomplete_reasons": incomplete_reasons,
            "older_years": [
                {
                    "year": r["pricing_year"], "tier_str": r["tier_str"],
                    "qty": r["tier_qty"], "price": r["pricing"],
                }
                for r in sorted(older, key=lambda r: (r["pricing_year"] or 0, r["tier_qty"] or 0))
            ],
        }
    return ladders


def find_ladder(ladders: dict, supplier_no, item_no) -> tuple[dict | None, str | None]:
    """Exact (supplier, item) ladder, else the supplier's VARIOUS ladder."""
    exact = ladders.get((str(supplier_no or ""), str(item_no or "")))
    if exact:
        return exact, None
    various = ladders.get((str(supplier_no or ""), "VARIOUS"))
    if various:
        return various, "supplier tier data is listed per 'VARIOUS' items"
    return None, None


def consolidate(messages: list[dict], horizon_days: int) -> tuple[list[dict], list[dict]]:
    """Split messages into those within the consolidation horizon of the
    earliest effective deadline, and those beyond it."""
    dated = [m for m in messages if m.get("effective_deadline") is not None]
    undated = [m for m in messages if m.get("effective_deadline") is None]
    if not dated:
        return messages, []
    earliest = min(m["effective_deadline"] for m in dated)
    cutoff = earliest + timedelta(days=horizon_days)
    included = [m for m in dated if m["effective_deadline"] <= cutoff] + undated
    excluded = [m for m in dated if m["effective_deadline"] > cutoff]
    return included, excluded


def _msg_ref(m: dict) -> dict:
    return {
        "line_id": m.get("line_id"),
        "row_id": m.get("row_id"),
        "msg_typ": m.get("msg_typ"),
        "request_date": m.get("request_date"),
        "effective_deadline": m.get("effective_deadline"),
        "qty": m.get("required_qty"),
    }


def recommend(supplier_no, item_no, messages: list[dict], ladders: dict, cfg: dict) -> dict:
    """Build the tier consolidation card for one (supplier, item)."""
    horizon = horizon_for_supplier(cfg, supplier_no)
    included, excluded = consolidate(messages, horizon)
    agg_qty = sum(m.get("required_qty") or 0 for m in included)

    card = {
        "supplier": str(supplier_no or ""),
        "supplier_name": messages[0].get("supplier_name") if messages else None,
        "item_number": str(item_no or ""),
        "description": messages[0].get("description") if messages else None,
        "horizon_days": horizon,
        "aggregate_qty": agg_qty,
        # Traceability: exactly which MRP messages were consolidated.
        "consolidated_messages": [_msg_ref(m) for m in included],
        "beyond_horizon_messages": [_msg_ref(m) for m in excluded],
    }

    ladder, ladder_note = find_ladder(ladders, supplier_no, item_no)
    if ladder is None:
        card.update({"tier_status": "no_data",
                     "note": "no tier data — request pricing"})
        return card
    card["ladder_note"] = ladder_note
    card["pricing_year"] = ladder["active_year"]
    card["older_years"] = ladder["older_years"]
    tiers = ladder["tiers"]
    if not tiers:
        card.update({
            "tier_status": "incomplete",
            "note": "tier data incomplete — request pricing",
            "incomplete_reasons": ladder["incomplete_reasons"],
        })
        return card
    if ladder["incomplete"]:
        card["incomplete_reasons"] = ladder["incomplete_reasons"]

    card["tiers"] = tiers
    lowest = tiers[0]
    current = None
    for tier in tiers:
        if agg_qty >= tier["qty"]:
            current = tier
    if current is None:
        # Below the lowest tier: say so explicitly and show the minimum.
        card.update({
            "tier_status": "below_minimum",
            "minimum_tier": lowest,
            "units_short_of_minimum": lowest["qty"] - agg_qty,
            "cost_at_minimum": round(lowest["qty"] * lowest["price"], 2),
            "note": (
                f"aggregate {agg_qty:,.0f} is below the lowest tier "
                f"({lowest['tier_str']} = {lowest['qty']:,})"
            ),
        })
        return card

    extended_cost = agg_qty * current["price"]
    card.update({
        "tier_status": "ok",
        "current_tier": current,
        "extended_cost": round(extended_cost, 2),
    })

    next_tier = next((t for t in tiers if t["qty"] > agg_qty), None)
    if next_tier is not None:
        units_short = next_tier["qty"] - agg_qty
        cost_at_next = next_tier["qty"] * next_tier["price"]
        savings_per_unit = current["price"] - next_tier["price"]
        tolerance = cfg["tier_bump_tolerance_pct"] / 100.0
        card["next_tier"] = {
            "tier": next_tier,
            "units_short": units_short,
            "incremental_units_cost_at_current_price": round(units_short * current["price"], 2),
            "incremental_units_cost_at_next_price": round(units_short * next_tier["price"], 2),
            "savings_per_unit": round(savings_per_unit, 5),
            "savings_on_full_order": round(next_tier["qty"] * savings_per_unit, 2),
            "incremental_spend": round(cost_at_next - extended_cost, 2),
            "total_cost_at_next_tier": round(cost_at_next, 2),
            "recommended": cost_at_next <= extended_cost * (1 + tolerance),
        }
    return card


def tier_cards(lines: list[dict], ladders: dict, cfg: dict) -> list[dict]:
    """Cards for every (supplier, item) with at least one actionable message."""
    grouped: dict[tuple, list[dict]] = {}
    for line in lines:
        if not line.get("actionable"):
            continue
        key = (line.get("supplier"), line.get("item_number"))
        grouped.setdefault(key, []).append(line)
    cards = []
    for (supplier_no, item_no), messages in sorted(
        grouped.items(), key=lambda kv: (str(kv[0][0] or ""), str(kv[0][1] or ""))
    ):
        cards.append(recommend(supplier_no, item_no, messages, ladders, cfg))
    return cards
