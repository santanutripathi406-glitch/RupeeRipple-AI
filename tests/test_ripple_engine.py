import datetime as dt

from core.ripple_engine import (BUFFER, COVERED, UNCOVERED, Adjustments, compare, contributors, simulate)
from tests.helpers import D0, cfg, day, make_df


def bal(res, n):
    return float(res.daily.loc[res.daily["date"] == D0 + dt.timedelta(days=n), "balance"].iloc[0])


def test_1_opening_cash_balance_is_correct():
    res = simulate(make_df([("R1", "A", "receivable", 100, 50, 50, "fixed", "pending")]), cfg(opening=1234.5))
    assert bal(res, 0) == 1234.5 and res.summary["opening_cash"] == 1234.5
    assert (res.daily["balance"] == 1234.5).all()


def test_2_incoming_payment_processed_on_arrival_date_only():
    res = simulate(make_df([("R1", "A", "receivable", 500, 3, 3, "fixed", "pending")]), cfg())
    assert bal(res, 2) == 1000 and bal(res, 3) == 1500 and bal(res, 30) == 1500


def test_3_outgoing_payment_processed_on_due_date_only():
    res = simulate(make_df([("P1", "S", "payable", 300, 5, None, "fixed", "pending")]), cfg())
    assert bal(res, 4) == 1000 and bal(res, 5) == 700


def test_4_delayed_receivable_not_counted_before_simulated_arrival():
    df = make_df([("R1", "A", "receivable", 500, 3, 3, "fixed", "pending")])
    res = simulate(df, cfg(), Adjustments(shifts={"R1": 10}))
    assert bal(res, 3) == 1000 and bal(res, 12) == 1000 and bal(res, 13) == 1500
    # an outgoing payment must not be counted before its due date even if shifted earlier than start
    df2 = make_df([("P1", "S", "payable", 100, 4, None, "flexible", "pending")])
    assert bal(simulate(df2, cfg(), Adjustments(shifts={"P1": -20})), 0) == 900   # clamped to start, not earlier


def test_5_multiple_transactions_same_date_receipts_first_no_double_count():
    df = make_df([("R1", "A", "receivable", 500, 2, 2, "fixed", "pending"), ("P1", "S", "payable", 1400, 2, None, "fixed", "pending"),
                  ("P2", "S2", "payable", 100, 2, None, "fixed", "pending")])
    res = simulate(df, cfg())
    assert bal(res, 2) == 0.0                            # 1000 + 500 - 1400 - 100, each counted once
    assert res.summary["total_inflow"] == 500 and res.summary["total_outflow"] == 1500
    ev = res.events.set_index("transaction_id")
    assert ev.at["P1", "balance_before"] == 1500          # receipts applied before payments
    assert ev.at["P1", "risk"] == BUFFER and ev.at["P2", "risk"] == BUFFER
    assert simulate(df, cfg()).daily.equals(res.daily)   # deterministic


def test_6_negative_cash_balance_and_uncovered_payment():
    df = make_df([("P1", "S", "payable", 1500, 1, None, "fixed", "pending")])
    res = simulate(df, cfg())
    assert bal(res, 1) == -500 and res.summary["max_cash_shortfall"] == 500
    assert res.summary["n_uncovered"] == 1 and res.events.iloc[0]["risk"] == UNCOVERED
    assert res.events.iloc[0]["uncovered_amount"] == 500


def test_7_safety_buffer_breach_detected():
    df = make_df([("P1", "S", "payable", 900, 2, None, "fixed", "pending"), ("R1", "A", "receivable", 900, 6, 6, "fixed", "pending")])
    s = simulate(df, cfg()).summary
    assert s["breach_days"] == 4 and s["first_breach_date"] == D0 + dt.timedelta(days=2)
    assert s["last_breach_date"] == D0 + dt.timedelta(days=5) and s["recovery_date"] == D0 + dt.timedelta(days=6)
    assert s["min_balance"] == 100 and s["max_liquidity_gap"] == 100 and s["max_cash_shortfall"] == 0
    assert s["n_buffer_only"] == 1 and s["n_uncovered"] == 0     # breach != inability to pay


def test_8_no_breach_when_cash_stays_above_buffer():
    df = make_df([("P1", "S", "payable", 500, 2, None, "fixed", "pending")])
    s = simulate(df, cfg()).summary
    assert s["breach_days"] == 0 and s["first_breach_date"] is None and s["n_at_risk"] == 0
    assert s["min_balance"] == 500 and contributors(simulate(df, cfg())).empty


def test_paid_items_excluded_and_events_after_horizon_reported():
    df = make_df([("P1", "S", "payable", 500, 2, None, "fixed", "paid"), ("P2", "S", "payable", 100, 99, None, "fixed", "pending")])
    s = simulate(df, cfg()).summary
    assert s["total_outflow"] == 0 and s["events_beyond_horizon"] == 1


def test_compare_and_contributors():
    df = make_df([("R1", "A", "receivable", 900, 1, 1, "fixed", "pending"), ("P1", "S", "payable", 1500, 3, None, "fixed", "pending")])
    base, late = simulate(df, cfg()), simulate(df, cfg(), Adjustments(shifts={"R1": 5}))
    d = compare(base, late)
    assert d["min_balance_change"] < 0 and d["newly_at_risk"] == ["P1"]
    assert list(contributors(late)["transaction_id"]) == ["P1"]
