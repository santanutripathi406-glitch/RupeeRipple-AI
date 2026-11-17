import datetime as dt

import pytest

from core.intervention_engine import (Intervention, InterventionError, apply_intervention, run_scenarios)
from core.ripple_engine import Adjustments, simulate
from tests.helpers import D0, cfg, make_df

ROWS = [("R1", "Big Customer", "receivable", 1000, 2, 2, "fixed", "pending"),
        ("P1", "Flexi Supplier", "payable", 900, 4, None, "flexible", "pending"),
        ("P2", "Fixed Payee", "payable", 200, 5, None, "fixed", "pending"),
        ("OT1", "Planned Purchase", "other", 300, 6, None, "flexible", "pending")]


def test_9_flexible_obligation_rescheduling_moves_payment():
    df = make_df(ROWS)
    ap = apply_intervention(df, Intervention("reschedule_flexible", {"transaction_ids": ["P1"], "days": 10, "fee_pct": 0}), 0, D0)
    res = simulate(df, cfg(), ap.adjustments)
    ev = res.events.set_index("transaction_id")
    assert ev.at["P1", "effective_date"] == D0 + dt.timedelta(days=14)


def test_fixed_obligation_cannot_be_rescheduled_and_reserve_cap():
    df = make_df(ROWS)
    with pytest.raises(InterventionError):
        apply_intervention(df, Intervention("reschedule_flexible", {"transaction_ids": ["P2"], "days": 5}), 0, D0)
    with pytest.raises(InterventionError):
        apply_intervention(df, Intervention("defer_purchase", {"transaction_ids": ["P1"], "days": 5}), 0, D0)
    with pytest.raises(InterventionError):
        apply_intervention(df, Intervention("use_reserve", {"amount": 500}), 100, D0)


def test_10_scenario_comparison_and_ranking():
    df = make_df(ROWS)
    delays = {"R1": 20}
    ivs = [Intervention("use_reserve", {"amount": 500, "on_date": D0}),
           Intervention("reschedule_flexible", {"transaction_ids": ["P1"], "days": 10, "fee_pct": 1}),
           Intervention("reschedule_flexible", {"transaction_ids": ["P2"], "days": 10}, label="Bad fixed reschedule")]
    comp, results = run_scenarios(df, cfg(opening=600, buffer=300), delays, ivs, reserve_balance=500)
    names = list(comp["scenario"])
    assert "Delayed - no action" in names and "On-time reference (no delay)" in names
    bad = comp[comp["scenario"] == "Bad fixed reschedule"].iloc[0]
    assert bad["feasible"] is False or bad["feasible"] == False  # noqa: E712
    ok = comp[comp["feasible"] & comp["rank"].notna()].sort_values("rank")
    assert ok.iloc[0]["score"] >= ok.iloc[-1]["score"]
    delayed = comp[comp["scenario"] == "Delayed - no action"].iloc[0]
    reserve = comp[comp["scenario"] == "Use existing cash reserve"].iloc[0]
    assert reserve["min_balance"] == delayed["min_balance"] + 500
    assert reserve["gap_reduction"] == delayed["max_liquidity_gap"] - reserve["max_liquidity_gap"] >= 0
    again, _ = run_scenarios(df, cfg(opening=600, buffer=300), delays, ivs, reserve_balance=500)
    assert comp.drop(columns=[]).equals(again)           # deterministic
