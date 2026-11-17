"""Deterministic cash-flow / ripple simulation engine (no ML, no randomness).

Conventions (all surfaced in the UI as assumptions):
* Paid transactions are excluded: they are assumed to be reflected in the opening cash.
* Incoming payments (receivables) arrive on ``expected_date`` (+ any simulated shift).
* Outgoing payments are made on ``due_date`` (+ any simulated shift); ``expected_date`` is ignored for them.
* Items dated before the simulation start are projected on the start date (cannot happen in the past).
* Within a day, all receipts are added first, then payments are made in order of (due_date, transaction_id).
* Payments are assumed to be made on their date even if cash is short, so the balance can go negative;
  that negative value is the projected liquidity gap, NOT a statement that the business has defaulted.
* Balances are end-of-day. A "buffer breach day" is an end-of-day balance strictly below the safety buffer.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

COVERED, BUFFER, UNCOVERED = "Covered", "Breaches buffer", "Cannot be covered"
RISK_RANK = {"": 0, COVERED: 0, BUFFER: 1, UNCOVERED: 2}

EVENT_COLUMNS = ["transaction_id", "entity_name", "transaction_type", "direction", "flexibility",
                 "due_date", "scheduled_date", "effective_date", "amount"]


@dataclass(frozen=True)
class SimConfig:
    opening_cash: float
    buffer: float
    start_date: dt.date
    horizon_days: int

    @property
    def end_date(self) -> dt.date:
        return self.start_date + dt.timedelta(days=int(self.horizon_days))


@dataclass
class Adjustments:
    shifts: dict = field(default_factory=dict)            # transaction_id -> days (+ later / - earlier)
    amount_overrides: dict = field(default_factory=dict)  # transaction_id -> amount
    extra_inflows: list = field(default_factory=list)     # (date, amount, label)
    exclude_ids: set = field(default_factory=set)

    def merged(self, other: "Adjustments") -> "Adjustments":
        shifts = dict(self.shifts)
        for k, v in other.shifts.items():
            shifts[k] = shifts.get(k, 0) + v
        return Adjustments(shifts, {**self.amount_overrides, **other.amount_overrides},
                           list(self.extra_inflows) + list(other.extra_inflows),
                           set(self.exclude_ids) | set(other.exclude_ids))


@dataclass
class SimulationResult:
    cfg: SimConfig
    daily: pd.DataFrame
    events: pd.DataFrame
    summary: dict


def _events(df: pd.DataFrame, cfg: SimConfig, adj: Adjustments) -> pd.DataFrame:
    rows = []
    for r in df.itertuples(index=False):
        if r.status == "paid" or r.transaction_id in adj.exclude_ids:
            continue
        direction = "in" if r.transaction_type == "receivable" else "out"
        base = r.expected_date if direction == "in" else r.due_date
        eff = base + dt.timedelta(days=int(adj.shifts.get(r.transaction_id, 0)))
        if eff < cfg.start_date:
            eff = cfg.start_date
        rows.append(dict(
            transaction_id=r.transaction_id, entity_name=r.entity_name,
            transaction_type=r.transaction_type, direction=direction, flexibility=r.flexibility,
            due_date=r.due_date, scheduled_date=base, effective_date=eff,
            amount=float(adj.amount_overrides.get(r.transaction_id, r.amount))))
    for n, (d, amt, label) in enumerate(adj.extra_inflows):
        d = max(d, cfg.start_date)
        rows.append(dict(transaction_id=f"EXTRA-{n + 1}", entity_name=label, transaction_type="reserve",
                         direction="in", flexibility="fixed", due_date=d, scheduled_date=d,
                         effective_date=d, amount=float(amt)))
    return pd.DataFrame(rows, columns=EVENT_COLUMNS)


def simulate(df: pd.DataFrame, cfg: SimConfig, adj: Adjustments | None = None) -> SimulationResult:
    adj = adj or Adjustments()
    ev = _events(df, cfg, adj)
    beyond = int((ev["effective_date"] > cfg.end_date).sum()) if len(ev) else 0
    ev = ev[ev["effective_date"] <= cfg.end_date].copy()
    ev["_dir"] = ev["direction"].map({"in": 0, "out": 1})
    ev = ev.sort_values(["effective_date", "_dir", "due_date", "transaction_id"],
                        kind="mergesort").drop(columns="_dir").reset_index(drop=True)

    by_day: dict = {}
    for idx, r in ev.iterrows():
        by_day.setdefault(r["effective_date"], []).append(idx)

    n = len(ev)
    bal = round(float(cfg.opening_cash), 2)
    before_l, after_l, risk, unc = [0.0] * n, [0.0] * n, [""] * n, [0.0] * n
    daily = []
    for k in range(int(cfg.horizon_days) + 1):
        day = cfg.start_date + dt.timedelta(days=k)
        inflow = outflow = 0.0
        idxs = by_day.get(day, [])
        for idx in idxs:                       # receipts first (rows are pre-sorted in -> out)
            if ev.at[idx, "direction"] == "in":
                before_l[idx] = bal
                bal = round(bal + ev.at[idx, "amount"], 2)
                after_l[idx] = bal
                inflow += ev.at[idx, "amount"]
        for idx in idxs:
            if ev.at[idx, "direction"] == "out":
                amt = ev.at[idx, "amount"]
                before_l[idx] = bal
                bal = round(bal - amt, 2)
                after_l[idx] = bal
                outflow += amt
                if before_l[idx] < amt:
                    risk[idx] = UNCOVERED
                    unc[idx] = round(amt - max(before_l[idx], 0.0), 2)
                elif bal < cfg.buffer:
                    risk[idx] = BUFFER
                else:
                    risk[idx] = COVERED
        daily.append(dict(date=day, inflow=round(inflow, 2), outflow=round(outflow, 2), balance=bal))
    daily = pd.DataFrame(daily)
    daily["net"] = (daily["inflow"] - daily["outflow"]).round(2)
    daily["below_buffer"] = daily["balance"] < cfg.buffer
    daily["buffer_shortfall"] = (cfg.buffer - daily["balance"]).clip(lower=0).round(2)
    daily["cash_shortfall"] = (-daily["balance"]).clip(lower=0).round(2)
    ev["balance_before"], ev["balance_after"] = before_l, after_l
    ev["risk"], ev["uncovered_amount"] = risk, unc

    below = daily[daily["below_buffer"]]
    mi = daily["balance"].idxmin()
    first_breach = below["date"].iloc[0] if len(below) else None
    last_breach = below["date"].iloc[-1] if len(below) else None
    recovery = None
    if first_breach is not None and not bool(daily["below_buffer"].iloc[-1]):
        recovery = last_breach + dt.timedelta(days=1)
    outs = ev[ev["direction"] == "out"]
    at_risk = outs[outs["risk"].isin([BUFFER, UNCOVERED])]
    summary = dict(
        opening_cash=float(cfg.opening_cash), buffer=float(cfg.buffer),
        start_date=cfg.start_date, end_date=cfg.end_date, horizon_days=int(cfg.horizon_days),
        total_inflow=round(float(daily["inflow"].sum()), 2),
        total_outflow=round(float(daily["outflow"].sum()), 2),
        closing_balance=float(daily["balance"].iloc[-1]),
        min_balance=float(daily.at[mi, "balance"]), min_balance_date=daily.at[mi, "date"],
        max_cash_shortfall=float(daily["cash_shortfall"].max()),
        max_liquidity_gap=float(daily["buffer_shortfall"].max()),
        breach_days=int(daily["below_buffer"].sum()),
        first_breach_date=first_breach, last_breach_date=last_breach, recovery_date=recovery,
        n_at_risk=int(len(at_risk)), n_uncovered=int((outs["risk"] == UNCOVERED).sum()),
        n_buffer_only=int((outs["risk"] == BUFFER).sum()),
        at_risk_ids=list(at_risk["transaction_id"]),
        at_risk_value=round(float(at_risk["amount"].sum()), 2),
        uncovered_value=round(float(outs.loc[outs["risk"] == UNCOVERED, "uncovered_amount"].sum()), 2),
        events_beyond_horizon=beyond, n_outgoing=int(len(outs)),
    )
    return SimulationResult(cfg, daily, ev, summary)


def risk_map(res: SimulationResult) -> dict:
    ev = res.events
    o = ev[ev["direction"] == "out"]
    return dict(zip(o["transaction_id"], o["risk"]))


def compare(base: SimulationResult, other: SimulationResult) -> dict:
    """Deltas of ``other`` relative to ``base`` plus obligations whose risk got worse / better."""
    b, o = risk_map(base), risk_map(other)
    worse = [k for k in o if RISK_RANK[o[k]] > RISK_RANK[b.get(k, "")]]
    better = [k for k in o if RISK_RANK[o[k]] < RISK_RANK[b.get(k, "")]]
    bs, os_ = base.summary, other.summary
    return dict(
        min_balance_change=round(os_["min_balance"] - bs["min_balance"], 2),
        gap_change=round(os_["max_liquidity_gap"] - bs["max_liquidity_gap"], 2),
        breach_days_change=os_["breach_days"] - bs["breach_days"],
        at_risk_change=os_["n_at_risk"] - bs["n_at_risk"],
        newly_at_risk=worse, no_longer_at_risk=better)


def contributors(res: SimulationResult) -> pd.DataFrame:
    """Obligations paid inside the buffer-breach window (candidates that drive the disruption)."""
    s = res.summary
    cols = ["transaction_id", "entity_name", "transaction_type", "effective_date", "amount",
            "flexibility", "risk", "balance_after"]
    if s["first_breach_date"] is None:
        return pd.DataFrame(columns=cols)
    ev = res.events
    m = ((ev["direction"] == "out") & (ev["effective_date"] >= s["first_breach_date"])
         & (ev["effective_date"] <= s["last_breach_date"]))
    return ev.loc[m, cols].sort_values(["amount", "transaction_id"], ascending=[False, True]).reset_index(drop=True)
