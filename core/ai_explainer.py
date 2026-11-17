"""Two-layer explanation engine.
Layer A (deterministic): every number comes from the Python engines and is packed into ``evidence``.
Layer B (optional LLM): receives ONLY that evidence and is told not to invent anything. If no key is configured,
the call fails, or the reply contains figures that are not in the evidence, the rules-engine text is used/flagged."""
from __future__ import annotations

import json
import os
import re
import urllib.request

import pandas as pd

from core.data_processor import inr

SUGGESTED_QUESTIONS = [
    "What caused the financial risk?",
    "Which customer payment is most important?",
    "Which obligations are affected?",
    "When is the risk expected to occur?",
    "Which intervention performed best?",
    "What assumptions influence the result?",
]


def _d(x):
    return None if x is None else str(x)


def build_evidence(df: pd.DataFrame, run: dict, comp: pd.DataFrame | None) -> dict:
    """Structured, verified facts. Pure data - no prose."""
    base, delayed, cfg = run["base"].summary, run["delayed"].summary, run["cfg"]
    names = dict(zip(df["transaction_id"], df["entity_name"]))
    amounts = dict(zip(df["transaction_id"], df["amount"]))
    delay_items = [dict(transaction_id=k, customer=names.get(k), amount=amounts.get(k), delay_days=v)
                   for k, v in run["delays"].items()]
    crit = run["crit"]
    top = crit.head(3)
    ev = run["delayed"].events
    risky = ev[(ev["direction"] == "out") & ev["risk"].isin(["Breaches buffer", "Cannot be covered"])]
    worse = run["delta"]["newly_at_risk"]
    best = None
    scen = []
    if comp is not None and len(comp):
        for _, r in comp.iterrows():
            if not r.get("feasible", False):
                scen.append(dict(scenario=r["scenario"], feasible=False, note=r.get("note", "")))
                continue
            scen.append(dict(scenario=r["scenario"], feasible=True, min_balance=r["min_balance"],
                             max_liquidity_gap=r["max_liquidity_gap"], breach_days=int(r["breach_days"]),
                             affected_obligations=int(r["affected_obligations"]), cost=r["cost"],
                             score=None if pd.isna(r["score"]) else r["score"],
                             rank=None if pd.isna(r["rank"]) else int(r["rank"]),
                             assumptions=r.get("assumptions", ""), tradeoffs=r.get("tradeoffs", "")))
        ranked = [s for s in scen if s.get("rank") == 1]
        best = ranked[0] if ranked else None
    return dict(
        currency="INR", synthetic_note="Figures are simulation outputs; not financial advice.",
        settings=dict(opening_cash=cfg.opening_cash, safety_buffer=cfg.buffer, start=_d(cfg.start_date),
                      end=_d(cfg.end_date), horizon_days=cfg.horizon_days),
        delays=delay_items,
        baseline={k: _d(v) if hasattr(v, "isoformat") else v for k, v in base.items() if k != "at_risk_ids"},
        delayed={k: _d(v) if hasattr(v, "isoformat") else v for k, v in delayed.items() if k != "at_risk_ids"},
        newly_at_risk=[dict(transaction_id=k, payee=names.get(k), amount=amounts.get(k)) for k in worse],
        at_risk_obligations=[dict(transaction_id=r["transaction_id"], payee=r["entity_name"], amount=r["amount"],
                                  due=_d(r["effective_date"]), status=r["risk"],
                                  balance_after=r["balance_after"]) for _, r in risky.iterrows()],
        top_critical_receivables=[dict(transaction_id=r["transaction_id"], customer=r["entity_name"],
                                       amount=r["amount"], arrival=_d(r["arrival_date"]), score=r["score"],
                                       level=r["level"], dependents=r["n_dependents"],
                                       dependent_value=r["dependent_value"]) for _, r in top.iterrows()],
        scenarios=scen, best_scenario=best,
        assumptions=ASSUMPTIONS)


ASSUMPTIONS = [
    "Paid items are assumed already reflected in opening cash.",
    "Receipts arrive on expected_date (plus any simulated delay); payments are made on due_date.",
    "Within a day, receipts are applied before payments; balances are end-of-day.",
    "A projected buffer breach is not a default: it means projected cash falls below the chosen safety buffer.",
    "Dependency links marked 'inferred' come from a liquidity test, not from contracts.",
    "Interventions require agreement from the other party and are not executed by this application."]


def _when(s):
    return s["first_breach_date"] if s else None


def rules_answer(question: str, ev: dict) -> str:
    q = question.lower()
    b, d = ev["baseline"], ev["delayed"]
    dl = ev["delays"][0] if ev["delays"] else None
    has_breach = d["breach_days"] > 0
    if any(k in q for k in ("assum", "limit", "influence")):
        return "**Assumptions behind these results**\n" + "\n".join(f"- {a}" for a in ev["assumptions"])
    if any(k in q for k in ("intervention", "best", "recommend", "fix", "reduce")):
        bs = ev["best_scenario"]
        if not bs:
            return "No ranked intervention is available yet. Configure interventions in the Intervention Lab."
        txt = (f"**Best-performing simulated option: {bs['scenario']}** (score {bs['score']}). "
               f"It leaves a minimum balance of {inr(bs['min_balance'])}, a liquidity gap of {inr(bs['max_liquidity_gap'])}, "
               f"{bs['breach_days']} buffer-breach day(s) and {bs['affected_obligations']} affected obligation(s), "
               f"versus {inr(d['min_balance'])}, {inr(d['max_liquidity_gap'])}, {d['breach_days']} and {d['n_at_risk']} with no action. "
               f"Cost in the simulation: {inr(bs['cost'])}.\n\n**Assumptions:** {bs['assumptions']}\n\n**Trade-offs:** {bs['tradeoffs']}")
        others = [s for s in ev["scenarios"] if s.get("feasible") and s.get("rank") and s["rank"] > 1]
        if others:
            txt += "\n\n**Other options:** " + "; ".join(f"#{s['rank']} {s['scenario']} (score {s['score']})" for s in sorted(others, key=lambda s: s['rank']))
        return txt + "\n\n_This is a simulation, not financial advice; no action is executed by the app._"
    if any(k in q for k in ("when", "date", "timing", "occur")):
        if not has_breach:
            return (f"In the current simulation the projected balance stays at or above the {inr(d['buffer'])} buffer; "
                    f"the lowest projected balance is {inr(d['min_balance'])} on {d['min_balance_date']}.")
        rec = f" It is projected to return above the buffer on {d['recovery_date']}." if d["recovery_date"] else " It does not recover within the simulation window."
        return (f"The first projected buffer breach is on **{d['first_breach_date']}**, with the lowest balance of "
                f"**{inr(d['min_balance'])}** on {d['min_balance_date']}. The balance is below the buffer on {d['breach_days']} day(s).{rec}")
    if any(k in q for k in ("important", "critical", "customer", "payment")):
        t = ev["top_critical_receivables"]
        if not t:
            return "There are no pending receivables inside the simulation window."
        lines = [f"- **{x['customer']}** ({x['transaction_id']}): {inr(x['amount'])} expected {x['arrival']}; criticality {x['score']}/100 ({x['level']}); "
                 f"if it did not arrive, {x['dependents']} later obligation(s) worth {inr(x['dependent_value'])} would get riskier." for x in t]
        return "**Most critical incoming payments (by the configurable criticality score)**\n" + "\n".join(lines) + \
            "\n\nDependency links marked inferred come from a liquidity test, not from contracts."
    if any(k in q for k in ("affect", "obligation", "which", "impact")):
        n = ev["newly_at_risk"]
        if not ev["at_risk_obligations"]:
            return "No obligation is projected to breach the safety buffer or go uncovered in the current simulation."
        txt = f"**{d['n_at_risk']} obligation(s) are at risk in the delayed scenario** (baseline: {b['n_at_risk']}).\n" + "\n".join(
            f"- {o['payee']} ({o['transaction_id']}), {inr(o['amount'])} due {o['due']}: {o['status']}" for o in ev["at_risk_obligations"])
        if n:
            txt += "\n\nNewly affected by the delay: " + ", ".join(f"{x['payee']} ({x['transaction_id']})" for x in n) + "."
        return txt + "\n\n'Breaches buffer' means projected cash falls under the safety buffer; only 'Cannot be covered' means projected cash is insufficient for that payment."
    # default: cause / summary
    if not dl:
        return (f"No payment delay is configured. In the baseline the lowest projected balance is {inr(b['min_balance'])} "
                f"against a {inr(b['buffer'])} buffer, with {b['breach_days']} breach day(s) and {b['n_at_risk']} at-risk obligation(s).")
    cause = (f"**Cause:** the simulated {dl['delay_days']}-day delay of {dl['customer']}'s payment ({dl['transaction_id']}, {inr(dl['amount'])}) "
             f"removes that cash from the days when scheduled payments fall due. ")
    effect = (f"Baseline minimum balance {inr(b['min_balance'])} becomes **{inr(d['min_balance'])}** on {d['min_balance_date']}; "
              f"the liquidity gap versus the buffer is **{inr(d['max_liquidity_gap'])}**, with {d['breach_days']} breach day(s) "
              f"and {d['n_at_risk']} at-risk obligation(s) (baseline {b['n_at_risk']}). ")
    tail = ("" if has_breach else "The delay does not push the balance under the safety buffer in this window. ")
    note = ("Cash falls below zero on at least one day, meaning some payments could not be covered from projected cash." if d["max_cash_shortfall"] > 0
            else "Projected cash stays above zero, so this is a buffer breach, not an inability to pay.") if has_breach else ""
    return cause + effect + tail + note


def llm_config():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("ANTHROPIC_API_KEY", "")
        except Exception:
            key = ""
    return key, os.environ.get("RUPEERIPPLE_LLM_MODEL", "claude-sonnet-5-5")


SYSTEM_PROMPT = ("You explain small-business cash-flow simulation results. Use ONLY the JSON evidence provided. "
                 "Do not invent transactions, dates, amounts or calculations and do not do new arithmetic. "
                 "Quote figures exactly as given. Label estimates and assumptions. Never state that the business "
                 "has defaulted; a projected buffer breach is not a default. This is not financial advice.")


def _call_llm(question: str, ev: dict, history: list, key: str, model: str) -> str:
    msgs = [m for m in history[-6:] if m["role"] in ("user", "assistant")]
    msgs.append({"role": "user", "content": f"EVIDENCE (JSON):\n{json.dumps(ev, default=str)}\n\nQUESTION: {question}"})
    body = json.dumps({"model": model, "max_tokens": 700, "system": SYSTEM_PROMPT, "messages": msgs}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST",
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()


def _numbers(text: str) -> set:
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*\.?\d*", text) if len(n.replace(",", "")) >= 4}


def unverified_numbers(text: str, ev: dict) -> list:
    """Figures of 4+ digits in the reply that appear nowhere in the evidence (formatted or raw)."""
    pool = json.dumps(ev, default=str)
    allowed = _numbers(pool) | {str(int(float(x))) for x in re.findall(r"-?\d+\.?\d*", pool) if x not in ("", "-")}
    return sorted(n for n in _numbers(text) if n.split(".")[0] not in allowed and n not in allowed)


def answer(question: str, ev: dict, history: list | None = None, llm_fn=None) -> dict:
    """Returns {text, source, note}. ``llm_fn`` can be injected for testing."""
    history = history or []
    key, model = llm_config()
    fallback = rules_answer(question, ev)
    if not key and llm_fn is None:
        return dict(text=fallback, source="rules", note="Built-in rules engine (no LLM API key configured).")
    try:
        text = (llm_fn or (lambda q, e, h: _call_llm(q, e, h, key, model)))(question, ev, history)
        if not text:
            raise ValueError("empty LLM reply")
        bad = unverified_numbers(text, ev)
        note = f"Generated by configured LLM ({model}) from verified engine output."
        if bad:
            note += f" Warning: these figures were not found in the evidence - verify before use: {', '.join(bad)}."
        return dict(text=text, source="llm", note=note)
    except Exception as exc:
        return dict(text=fallback, source="rules", note=f"LLM unavailable ({type(exc).__name__}); showing built-in rules-engine explanation.")
