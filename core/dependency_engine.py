"""Financial dependency graph + transparent criticality scoring.

Edges
* receivable -> Business (inflow) and Business -> obligation (outflow) come straight from the data.
* receivable -> obligation "dependency" edges are of two kinds:
    - declared: the dataset's ``related_entity`` column links the two records (we do NOT claim a contract);
    - inferred: a liquidity test - if the receivable never arrived inside the horizon, the obligation's
      risk status would get worse. This is a simulation result, not proof of a contractual relationship.
"""
from __future__ import annotations

import networkx as nx
import pandas as pd

from core.data_processor import DEFAULT_WEIGHTS
from core.ripple_engine import (COVERED, RISK_RANK, Adjustments, SimConfig, simulate, risk_map)

BUSINESS = "BUSINESS"


def _clip(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def level_for(score: float) -> str:
    return "High" if score >= 60 else "Medium" if score >= 30 else "Low"


def compute_criticality(df: pd.DataFrame, cfg: SimConfig, weights: dict | None = None):
    """Return (criticality_df, base_result). Score is 0-100 = weighted sum of five 0-1 factors:
    amount, timing, dependency, buffer, flexibility (see README / UI for definitions)."""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    wsum = sum(w.values()) or 1.0
    base = simulate(df, cfg)
    ev = base.events
    recs = ev[ev["direction"] == "in"]
    recs = recs[recs["transaction_type"] == "receivable"]
    cols = ["transaction_id", "entity_name", "amount", "arrival_date", "days_until", "amount_factor",
            "timing_factor", "dependency_factor", "buffer_factor", "flexibility_factor", "score", "level",
            "dependents", "dependent_value", "n_dependents"]
    if recs.empty:
        return pd.DataFrame(columns=cols), base
    flex = dict(zip(df["transaction_id"], df["flexibility"]))
    base_risk = risk_map(base)
    total_out = max(base.summary["total_outflow"], 1.0)
    max_amt = float(recs["amount"].max())
    headroom = base.summary["min_balance"] - cfg.buffer
    rows = []
    for _, r in recs.iterrows():
        without = simulate(df, cfg, Adjustments(exclude_ids={r["transaction_id"]}))
        wr = risk_map(without)
        dep = [k for k, v in wr.items() if RISK_RANK[v] > RISK_RANK[base_risk.get(k, COVERED)]]
        oev = without.events.set_index("transaction_id")
        dep_val = float(sum(oev.at[k, "amount"] for k in dep))
        dep_fixed = float(sum(oev.at[k, "amount"] for k in dep if flex.get(k) == "fixed"))
        days_until = (r["effective_date"] - cfg.start_date).days
        f = dict(
            amount_factor=_clip(r["amount"] / max_amt),
            timing_factor=_clip(1 - days_until / max(cfg.horizon_days, 1)),
            dependency_factor=_clip(dep_val / total_out),
            buffer_factor=_clip(1 - headroom / r["amount"]),
            flexibility_factor=_clip(dep_fixed / dep_val) if dep_val > 0 else 0.0)
        score = 100 * (w["amount"] * f["amount_factor"] + w["timing"] * f["timing_factor"]
                       + w["dependency"] * f["dependency_factor"] + w["buffer"] * f["buffer_factor"]
                       + w["flexibility"] * f["flexibility_factor"]) / wsum
        rows.append(dict(transaction_id=r["transaction_id"], entity_name=r["entity_name"], amount=r["amount"],
                         arrival_date=r["effective_date"], days_until=days_until, **f,
                         score=round(score, 1), level=level_for(score), dependents=dep,
                         dependent_value=round(dep_val, 2), n_dependents=len(dep)))
    out = pd.DataFrame(rows, columns=cols).sort_values(["score", "transaction_id"], ascending=[False, True])
    return out.reset_index(drop=True), base


def declared_links(df: pd.DataFrame) -> list:
    """(receivable_id, obligation_id) pairs implied by the related_entity column."""
    active = df[df["status"] != "paid"]
    rec = active[active["transaction_type"] == "receivable"]
    obl = active[active["transaction_type"] != "receivable"]
    links = set()
    for _, o in obl.iterrows():
        if o["related_entity"]:
            for rid in rec.loc[rec["entity_name"] == o["related_entity"], "transaction_id"]:
                links.add((rid, o["transaction_id"]))
    for _, r in rec.iterrows():
        if r["related_entity"]:
            for oid in obl.loc[obl["entity_name"] == r["related_entity"], "transaction_id"]:
                links.add((r["transaction_id"], oid))
    return sorted(links)


def build_graph(df: pd.DataFrame, cfg: SimConfig, crit: pd.DataFrame, base) -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_node(BUSINESS, kind="business", label="Business", amount=0.0, date=None, risk="",
               score=0.0, level="")
    crit_map = crit.set_index("transaction_id") if len(crit) else pd.DataFrame()
    rmap = risk_map(base)
    ev = base.events
    for _, e in ev.iterrows():
        tid = e["transaction_id"]
        if e["transaction_type"] == "reserve":
            continue
        if e["direction"] == "in":
            sc = float(crit_map.at[tid, "score"]) if tid in getattr(crit_map, "index", []) else 0.0
            G.add_node(tid, kind="customer", label=e["entity_name"], amount=e["amount"], date=e["effective_date"],
                       risk="", score=sc, level=level_for(sc), flexibility=e["flexibility"],
                       txn_type=e["transaction_type"])
            G.add_edge(tid, BUSINESS, kind="inflow", amount=e["amount"], date=e["effective_date"], basis="data")
        else:
            G.add_node(tid, kind="obligation", label=e["entity_name"], amount=e["amount"], date=e["effective_date"],
                       risk=rmap.get(tid, ""), score=0.0, level="", flexibility=e["flexibility"],
                       txn_type=e["transaction_type"])
            G.add_edge(BUSINESS, tid, kind="outflow", amount=e["amount"], date=e["effective_date"], basis="data")
    declared = set(declared_links(df))
    for rid, oid in declared:
        if rid in G and oid in G:
            G.add_edge(rid, oid, kind="dependency", basis="declared", amount=G.nodes[oid]["amount"], date=None)
    for rid, row in (crit_map.iterrows() if len(crit_map) else []):
        for oid in row["dependents"]:
            if rid in G and oid in G and not G.has_edge(rid, oid):
                G.add_edge(rid, oid, kind="dependency", basis="inferred", amount=G.nodes[oid]["amount"], date=None)
    return G


def graph_metrics(G: nx.DiGraph) -> dict:
    inflow = sum(d["amount"] for _, _, d in G.edges(data=True) if d["kind"] == "inflow")
    outflow = sum(d["amount"] for _, _, d in G.edges(data=True) if d["kind"] == "outflow")
    dep = [(u, v, d) for u, v, d in G.edges(data=True) if d["kind"] == "dependency"]
    return dict(nodes=G.number_of_nodes(), edges=G.number_of_edges(),
                customers=sum(1 for _, d in G.nodes(data=True) if d["kind"] == "customer"),
                obligations=sum(1 for _, d in G.nodes(data=True) if d["kind"] == "obligation"),
                inflow_value=inflow, outflow_value=outflow, declared_edges=sum(1 for *_, d in dep if d["basis"] == "declared"),
                inferred_edges=sum(1 for *_, d in dep if d["basis"] == "inferred"))


def downstream(G: nx.DiGraph, rid: str) -> list:
    return sorted(v for _, v, d in G.out_edges(rid, data=True) if d["kind"] == "dependency")
