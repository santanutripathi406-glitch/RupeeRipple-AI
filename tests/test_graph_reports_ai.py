import datetime as dt
import io

import pandas as pd

from core import ai_explainer, database as db
from core.data_processor import default_settings, load_sample_raw
from core.dependency_engine import BUSINESS, build_graph, compute_criticality, graph_metrics
from core.pipeline import run_intervention_lab, run_simulation
from core.prediction_model import MIN_ROWS, _features, generate_synthetic_history, get_model, predict_receivables, train_model
from core.report import (at_risk_csv, at_risk_table, build_pdf, build_report, comparison_csv, daily_csv)
from core.validation import validate_dataframe
from tests.helpers import cfg, make_df

D0 = dt.date(2026, 1, 1)


def sample():
    return validate_dataframe(load_sample_raw(D0)).clean, default_settings(D0)


def test_14_graph_construction():
    df = make_df([("R1", "Cust", "receivable", 1000, 2, 2, "fixed", "pending"), ("P1", "Sup", "payable", 900, 3, None, "fixed", "pending"),
                  ("P2", "Sup2", "payable", 500, 9, None, "flexible", "pending")])
    c = cfg(opening=300, buffer=100)
    crit, base = compute_criticality(df, c)
    G = build_graph(df, c, crit, base)
    assert BUSINESS in G and G.has_edge("R1", BUSINESS) and G.has_edge(BUSINESS, "P1") and G.has_edge(BUSINESS, "P2")
    assert G.nodes["R1"]["kind"] == "customer" and G.nodes["P1"]["kind"] == "obligation"
    assert G.has_edge("R1", "P1") and G.edges["R1", "P1"]["basis"] == "inferred"     # P1 depends on R1 for liquidity
    assert graph_metrics(G)["customers"] == 1 and graph_metrics(G)["obligations"] == 2
    assert 0 <= crit.iloc[0]["score"] <= 100 and crit.iloc[0]["level"] in ("High", "Medium", "Low")


def test_graph_declared_edges_and_updates_when_data_changes():
    df, st = sample()
    run = run_simulation(df, st, {"txn_id": "R001", "delay_days": 10})
    G = run["graph"]
    assert G.edges["R001", "P001"]["basis"] == "declared"
    df2 = df[df["transaction_id"] != "R007"]
    assert run_simulation(df2, st, None)["graph"].number_of_nodes() == G.number_of_nodes() - 1


def test_sample_story_for_demo():
    df, st = sample()
    run = run_simulation(df, st, {"txn_id": "R001", "delay_days": 10})
    assert run["crit"].iloc[0]["transaction_id"] == "R001"
    assert run["base"].summary["breach_days"] == 0 and run["delayed"].summary["breach_days"] > 0
    assert run["delayed"].summary["max_cash_shortfall"] == 0


def test_15_report_and_export_consistency():
    df, st = sample()
    run = run_simulation(df, st, {"txn_id": "R001", "delay_days": 10})
    comp, _, _ = run_intervention_lab(df, st, {"txn_id": "R001", "delay_days": 10})
    d = pd.read_csv(io.StringIO(daily_csv(run)))
    S = run["delayed"].summary
    assert d["delayed_balance"].min() == S["min_balance"] and int(d["delayed_below_buffer"].sum()) == S["breach_days"]
    assert len(pd.read_csv(io.StringIO(at_risk_csv(run)))) == S["n_at_risk"] == len(at_risk_table(run))
    c2 = pd.read_csv(io.StringIO(comparison_csv(comp)))
    assert c2.loc[c2.scenario == "Delayed - no action", "min_balance"].iloc[0] == S["min_balance"]
    ev = ai_explainer.build_evidence(df, run, comp)
    rep = build_report(df, run, comp, ai_explainer.rules_answer("what caused it", ev), "rules", True, st)
    pdf = build_pdf(rep)
    assert pdf.startswith(b"%PDF") and len(pdf) > 2000
    assert ev["delayed"]["min_balance"] == S["min_balance"]


def test_ai_fallback_without_key_and_llm_guardrails():
    df, st = sample()
    run = run_simulation(df, st, {"txn_id": "R001", "delay_days": 10})
    comp, _, _ = run_intervention_lab(df, st, {"txn_id": "R001", "delay_days": 10})
    ev = ai_explainer.build_evidence(df, run, comp)
    r = ai_explainer.answer("Which obligations are affected?", ev)
    assert r["source"] == "rules" and "no LLM API key" in r["note"] and "Warp Yarn" in r["text"]
    for q in ai_explainer.SUGGESTED_QUESTIONS:
        assert len(ai_explainer.rules_answer(q, ev)) > 40
    ok = ai_explainer.answer("x", ev, llm_fn=lambda q, e, h: "The minimum balance is ₹75,000.")
    assert ok["source"] == "llm" and "Warning" not in ok["note"]
    bad = ai_explainer.answer("x", ev, llm_fn=lambda q, e, h: "The loss will reach ₹9,99,999 next week.")
    assert bad["source"] == "llm" and "999999" in bad["note"]
    def boom(*a): raise RuntimeError("api down")
    fb = ai_explainer.answer("x", ev, llm_fn=boom)
    assert fb["source"] == "rules" and "LLM unavailable" in fb["note"]


def test_prediction_model_unavailable_with_little_data_and_no_leakage():
    small = generate_synthetic_history().head(MIN_ROWS - 1)
    b = train_model(small, "t")
    assert not b.available and "Prediction is unavailable" in b.reason
    f = _features(generate_synthetic_history())
    first = f.groupby("customer").head(1)
    assert (first["prior_count"] == 0).all() and (first["prior_avg_delay"] == 0).all()   # first invoice sees no history
    df, _ = sample()
    bundle = get_model(df)
    assert bundle.available and bundle.n_train > bundle.n_test > 0 and "SYNTHETIC" in bundle.source
    assert 0 <= bundle.metrics["classifier"]["logistic_regression"]["roc_auc"] <= 1
    p = predict_receivables(bundle, df)
    assert p["prob_late"].between(0, 1).all()


def test_database_idempotent(tmp_path):
    path = str(tmp_path / "x.db")
    db.init_db(path)
    raw = load_sample_raw(D0)
    s1, s2 = db.save_dataset(raw, "a", path), db.save_dataset(raw, "a again", path)
    assert s1 == s2 and len(db.list_datasets(path)) == 1
    assert db.load_dataset(s1, path).equals(raw)
    h1 = db.save_simulation(s1, {"txn": "R001", "d": 10}, {"min_balance": 1}, path)
    h2 = db.save_simulation(s1, {"txn": "R001", "d": 10}, {"min_balance": 1}, path)
    assert h1 == h2 and len(db.list_simulations(path)) == 1
    db.set_setting("k", {"a": 1}, path)
    assert db.get_setting("k", None, path) == {"a": 1}
