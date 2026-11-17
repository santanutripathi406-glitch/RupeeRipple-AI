"""Counterfactual scenario engine. Interventions are SIMULATED assumptions only - nothing is executed,
no supplier/customer is contacted and no loan is arranged."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

from core.ripple_engine import Adjustments, SimConfig, SimulationResult, compare, simulate

KINDS = {
    "earlier_payment": "Request earlier customer payment",
    "reschedule_flexible": "Reschedule flexible obligation(s)",
    "defer_purchase": "Defer non-essential planned purchase",
    "use_reserve": "Use existing cash reserve",
}
DEFAULT_RANK_WEIGHTS = {"gap": 0.5, "days": 0.3, "affected": 0.2}


class InterventionError(ValueError):
    """Raised when an intervention is not feasible under the stated rules."""


@dataclass
class Intervention:
    kind: str
    params: dict = field(default_factory=dict)
    label: str = ""

    def name(self) -> str:
        return self.label or KINDS[self.kind]


@dataclass
class Applied:
    adjustments: Adjustments
    cost: float
    assumptions: list
    tradeoffs: list


def _row(df, tid):
    m = df[df["transaction_id"] == tid]
    if m.empty:
        raise InterventionError(f"Transaction {tid} does not exist in the dataset.")
    return m.iloc[0]


def apply_intervention(df: pd.DataFrame, iv: Intervention, reserve_balance: float, start: dt.date) -> Applied:
    p = iv.params
    if iv.kind == "earlier_payment":
        r = _row(df, p["transaction_id"])
        if r["transaction_type"] != "receivable":
            raise InterventionError("Only receivables can be paid earlier by a customer.")
        days, disc = int(p.get("days_earlier", 0)), float(p.get("discount_pct", 0)) / 100
        if days <= 0:
            raise InterventionError("Days earlier must be greater than zero.")
        if not 0 <= disc < 1:
            raise InterventionError("Early-payment discount must be between 0% and under 100%.")
        cost = round(r["amount"] * disc, 2)
        adj = Adjustments(shifts={r["transaction_id"]: -days},
                          amount_overrides={r["transaction_id"]: round(r["amount"] - cost, 2)} if cost else {})
        return Applied(adj, cost,
                       [f"{r['entity_name']} ({r['transaction_id']}) agrees to pay {days} day(s) earlier than the delayed date.",
                        f"Early-payment discount of {disc:.1%} (cost {cost:,.0f}) is accepted by the business."],
                       ["The customer may refuse; a discount reduces margin; may strain the relationship."])
    if iv.kind in ("reschedule_flexible", "defer_purchase"):
        ids, days = list(p.get("transaction_ids", [])), int(p.get("days", 0))
        fee = float(p.get("fee_pct", 0)) / 100 if iv.kind == "reschedule_flexible" else 0.0
        if not ids:
            raise InterventionError("Select at least one obligation.")
        if days <= 0:
            raise InterventionError("Deferral days must be greater than zero.")
        shifts, over, cost = {}, {}, 0.0
        for tid in ids:
            r = _row(df, tid)
            if r["transaction_type"] == "receivable":
                raise InterventionError(f"{tid} is a receivable, not an obligation.")
            if r["flexibility"] != "flexible":
                raise InterventionError(f"{tid} ({r['entity_name']}) is marked fixed and cannot be rescheduled.")
            if iv.kind == "defer_purchase" and r["transaction_type"] != "other":
                raise InterventionError(f"{tid} is a '{r['transaction_type']}' obligation, not a planned purchase ('other').")
            shifts[tid] = days
            if fee:
                over[tid] = round(r["amount"] * (1 + fee), 2)
                cost += r["amount"] * fee
        if iv.kind == "reschedule_flexible":
            a = [f"Each selected supplier/payee explicitly agrees to be paid {days} day(s) later.",
                 f"Late/extension fee of {fee:.1%} per obligation (total {cost:,.0f}) is charged." if fee else "No fee is charged."]
            t = ["Suppliers are NOT assumed to agree - agreement must be obtained first.",
                 "May affect supplier terms or relationship."]
        else:
            a = [f"The planned purchase(s) are postponed by {days} day(s) with no penalty."]
            t = ["Delays growth/efficiency benefits of the purchase; vendor may change price or availability."]
        return Applied(Adjustments(shifts=shifts, amount_overrides=over), round(cost, 2), a, t)
    if iv.kind == "use_reserve":
        amt = float(p.get("amount", 0))
        on = p.get("on_date") or start
        if amt <= 0:
            raise InterventionError("Reserve amount must be greater than zero.")
        if amt > reserve_balance + 1e-9:
            raise InterventionError(f"Requested reserve {amt:,.0f} exceeds the available reserve {reserve_balance:,.0f} (see Settings).")
        return Applied(Adjustments(extra_inflows=[(on, amt, "Cash reserve")]), 0.0,
                       [f"An existing reserve of {amt:,.0f} is available and moved into operating cash on {on}.",
                        "The reserve is separate from the opening cash balance."],
                       ["Reserve is depleted and no longer available for later shocks; not a loan or new funding."])
    raise InterventionError(f"Unknown intervention type '{iv.kind}'.")


def _metrics(res: SimulationResult) -> dict:
    s = res.summary
    return dict(min_balance=s["min_balance"], max_liquidity_gap=s["max_liquidity_gap"],
                max_cash_shortfall=s["max_cash_shortfall"], breach_days=s["breach_days"],
                affected_obligations=s["n_at_risk"], first_breach=s["first_breach_date"],
                recovery_date=s["recovery_date"], closing_balance=s["closing_balance"])


def _frac(base: float, new: float) -> float:
    if base <= 0:
        return 0.0
    return max(0.0, min(1.0, (base - new) / base))


def run_scenarios(df: pd.DataFrame, cfg: SimConfig, delays: dict, interventions: list,
                  reserve_balance: float, include_combined: bool = True, rank_weights: dict | None = None):
    """Return (comparison_df, results_by_name). Raises nothing: infeasible interventions are reported
    as rows with ``feasible=False`` and the reason in ``note``."""
    rw = {**DEFAULT_RANK_WEIGHTS, **(rank_weights or {})}
    base_adj = Adjustments(shifts=dict(delays))
    ref = simulate(df, cfg)
    delayed = simulate(df, cfg, base_adj)
    results = {"On-time reference (no delay)": ref, "Delayed - no action": delayed}
    meta = {"On-time reference (no delay)": dict(cost=0.0, assumptions=["All receivables arrive on their expected dates."], tradeoffs=[], feasible=True, note=""),
            "Delayed - no action": dict(cost=0.0, assumptions=["The selected delay happens and no action is taken."], tradeoffs=[], feasible=True, note="")}
    applied_ok = []
    for iv in interventions:
        nm = iv.name()
        try:
            ap = apply_intervention(df, iv, reserve_balance, cfg.start_date)
        except InterventionError as exc:
            meta[nm] = dict(cost=0.0, assumptions=[], tradeoffs=[], feasible=False, note=str(exc))
            continue
        results[nm] = simulate(df, cfg, base_adj.merged(ap.adjustments))
        meta[nm] = dict(cost=ap.cost, assumptions=ap.assumptions, tradeoffs=ap.tradeoffs, feasible=True, note="")
        applied_ok.append((nm, ap))
    if include_combined and len(applied_ok) > 1:
        merged, cost, a, t = base_adj, 0.0, [], []
        for nm, ap in applied_ok:
            merged = merged.merged(ap.adjustments)
            cost += ap.cost
            a += ap.assumptions
            t += ap.tradeoffs
        results["Combined (all selected)"] = simulate(df, cfg, merged)
        meta["Combined (all selected)"] = dict(cost=round(cost, 2), assumptions=a, tradeoffs=t, feasible=True,
                                               note="All feasible interventions applied together.")
    dm = _metrics(delayed)
    rows = []
    for nm, m in meta.items():
        if not m["feasible"]:
            rows.append(dict(scenario=nm, feasible=False, note=m["note"], cost=0.0))
            continue
        res = results[nm]
        row = dict(scenario=nm, feasible=True, **_metrics(res), cost=m["cost"], note=m["note"])
        row["gap_reduction"] = round(dm["max_liquidity_gap"] - row["max_liquidity_gap"], 2)
        row["breach_days_reduction"] = dm["breach_days"] - row["breach_days"]
        row["affected_reduction"] = dm["affected_obligations"] - row["affected_obligations"]
        row["min_balance_improvement"] = round(row["min_balance"] - dm["min_balance"], 2)
        row["score"] = round(100 * (rw["gap"] * _frac(dm["max_liquidity_gap"], row["max_liquidity_gap"])
                                    + rw["days"] * _frac(dm["breach_days"], row["breach_days"])
                                    + rw["affected"] * _frac(dm["affected_obligations"], row["affected_obligations"])), 1)
        row["assumptions"] = " | ".join(m["assumptions"])
        row["tradeoffs"] = " | ".join(m["tradeoffs"])
        rows.append(row)
    comp = pd.DataFrame(rows)
    cand = comp[(comp["feasible"]) & (~comp["scenario"].isin(["On-time reference (no delay)", "Delayed - no action"]))].copy()
    comp["rank"] = pd.NA
    comp.loc[comp["scenario"].isin(["On-time reference (no delay)", "Delayed - no action"]), "score"] = float("nan")
    if len(cand):
        cand = cand.sort_values(["score", "cost", "scenario"], ascending=[False, True, True])
        for i, idx in enumerate(cand.index, start=1):
            comp.at[idx, "rank"] = i
    comp.attrs["meta"] = meta
    return comp, results


def default_interventions(df: pd.DataFrame, cfg: SimConfig, delays: dict, reserve_balance: float) -> list:
    """Sensible starting parameters (user-editable in the Intervention Lab)."""
    ivs = []
    recs = [t for t in delays if t in set(df["transaction_id"])]
    if recs:
        ivs.append(Intervention("earlier_payment", {"transaction_id": recs[0], "days_earlier": 5, "discount_pct": 1.0}))
    flex = df[(df["flexibility"] == "flexible") & (df["status"] != "paid")
              & (df["transaction_type"].isin(["payable", "utilities", "rent"]))]
    if len(flex):
        ivs.append(Intervention("reschedule_flexible", {"transaction_ids": list(flex["transaction_id"][:3]), "days": 14, "fee_pct": 1.0}))
    purchases = df[(df["flexibility"] == "flexible") & (df["status"] != "paid") & (df["transaction_type"] == "other")]
    if len(purchases):
        ivs.append(Intervention("defer_purchase", {"transaction_ids": list(purchases["transaction_id"]), "days": 30}))
    if reserve_balance > 0:
        ivs.append(Intervention("use_reserve", {"amount": float(min(reserve_balance, 100000.0)), "on_date": cfg.start_date}))
    return ivs
