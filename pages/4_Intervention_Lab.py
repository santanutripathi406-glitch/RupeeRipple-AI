"""Intervention Lab - compare counterfactual scenarios side by side."""
import pandas as pd
import streamlit as st

from core import charts, database as db, state, ui
from core.data_processor import inr
from core.intervention_engine import DEFAULT_RANK_WEIGHTS, Intervention, KINDS, default_interventions
from core.pipeline import active_cfg, delays_from, run_intervention_lab, run_simulation

c = ui.setup("Intervention Lab", "🧪")
ui.hero("Intervention Lab", "Test what-if actions against the delayed-payment scenario. Nothing is executed or sent to anyone.")
ui.require_valid(c)
sc = state.ensure_sim_cfg(c)
cfg = active_cfg(c.settings, sc)
delays = delays_from(sc)
if not delays:
    st.warning("No payment delay is active, so there is nothing to mitigate. Set a delay in the Ripple Simulator first.")
    st.page_link("pages/3_Ripple_Simulator.py", label="Go to Ripple Simulator", icon=":material/waves:")
    st.stop()
txn = list(delays)[0]
d_row = c.df[c.df.transaction_id == txn].iloc[0]
st.markdown(f"**Active delay:** {d_row.entity_name} ({txn}, {inr(d_row.amount)}) is **{delays[txn]} day(s) late**. Reserve available: **{inr(c.settings['reserve_balance'])}**.")

ui.section("Configure interventions", "Each option is a simulated assumption; the other party must agree.")
defaults = {iv.kind: iv for iv in default_interventions(c.df, cfg, delays, c.settings["reserve_balance"])}
chosen = []
flex_ob = c.df[(c.df.flexibility == "flexible") & (c.df.status != "paid") & (c.df.transaction_type != "receivable")]
fmt = lambda i: f"{i} · {c.df.loc[c.df.transaction_id == i, 'entity_name'].iloc[0]} · {inr(c.df.loc[c.df.transaction_id == i, 'amount'].iloc[0])}"
t1, t2, t3, t4 = st.tabs(list(KINDS.values()))
with t1:
    on = st.checkbox("Include", value=True, key="iv_on_1")
    days = st.slider("Customer pays this many days earlier than the delayed date", 1, 60, 5)
    disc = st.number_input("Early-payment discount offered (%)", 0.0, 20.0, 1.0, 0.5)
    st.caption("Assumes the customer agrees. The discount is a simulated cost.")
    if on: chosen.append(Intervention("earlier_payment", {"transaction_id": txn, "days_earlier": days, "discount_pct": disc}))
with t2:
    on = st.checkbox("Include", value=True, key="iv_on_2")
    pool = flex_ob[flex_ob.transaction_type != "other"]["transaction_id"].tolist()
    pre = [i for i in (defaults.get("reschedule_flexible").params["transaction_ids"] if "reschedule_flexible" in defaults else []) if i in pool]
    ids = st.multiselect("Flexible obligations to reschedule", pool, default=pre, format_func=fmt)
    days = st.slider("Defer by (days)", 1, 60, 14, key="rs_days")
    fee = st.number_input("Extension / late fee (% of amount)", 0.0, 20.0, 1.0, 0.5)
    st.caption("Only obligations marked *flexible* qualify, and each payee must explicitly agree — suppliers are not assumed to agree.")
    if on: chosen.append(Intervention("reschedule_flexible", {"transaction_ids": ids, "days": days, "fee_pct": fee}))
with t3:
    on = st.checkbox("Include", value=True, key="iv_on_3")
    pool = flex_ob[flex_ob.transaction_type == "other"]["transaction_id"].tolist()
    ids3 = st.multiselect("Planned purchases to defer", pool, default=pool, format_func=fmt)
    days3 = st.slider("Defer by (days)", 1, 90, 30, key="df_days")
    if not pool: st.info("No flexible 'other' obligations (planned purchases) in the dataset.")
    if on and pool: chosen.append(Intervention("defer_purchase", {"transaction_ids": ids3, "days": days3}))
with t4:
    on = st.checkbox("Include", value=True, key="iv_on_4")
    amt = st.number_input("Reserve amount to use (₹)", 0.0, value=float(min(c.settings["reserve_balance"], 100000.0)), step=10000.0)
    st.caption(f"Cannot exceed the available reserve ({inr(c.settings['reserve_balance'])}). Not a loan or new funding.")
    if on: chosen.append(Intervention("use_reserve", {"amount": amt, "on_date": cfg.start_date}))

with st.expander("Ranking weights"):
    rw = {"gap": st.slider("Weight: liquidity-gap reduction", 0.0, 1.0, DEFAULT_RANK_WEIGHTS["gap"], 0.05),
          "days": st.slider("Weight: fewer breach days", 0.0, 1.0, DEFAULT_RANK_WEIGHTS["days"], 0.05),
          "affected": st.slider("Weight: fewer affected obligations", 0.0, 1.0, DEFAULT_RANK_WEIGHTS["affected"], 0.05)}
    st.caption("Score = 100 × Σ weight × (reduction ÷ delayed-scenario value), each term capped to 0–1. Ties are broken by lower cost. Cost is shown, not scored.")

if not chosen:
    st.info("Select at least one intervention above."); st.stop()
from core.intervention_engine import run_scenarios
comp, results = run_scenarios(c.df, cfg, delays, chosen, c.settings["reserve_balance"], rank_weights=rw)
st.session_state.scen_ivs = chosen

ui.section("Scenario ranking", "Baseline first, then each intervention against the delayed, no-action case.")
for _, r in comp[~comp["feasible"]].iterrows():
    st.error(f"Not feasible — {r['scenario']}: {r['note']}")
ok = comp[comp["feasible"]].copy()
best = ok[ok["rank"].notna()].sort_values("rank").head(1)
if len(best):
    b = best.iloc[0]
    st.success(f"**Best simulated option: {b.scenario}** — liquidity gap {inr(b.max_liquidity_gap)} (was {inr(ok[ok.scenario == 'Delayed - no action'].max_liquidity_gap.iloc[0])}), "
               f"{int(b.breach_days)} breach day(s), cost {inr(b.cost)}, score {b.score}.")
show = ok[["rank", "scenario", "min_balance", "max_liquidity_gap", "breach_days", "affected_obligations", "recovery_date", "gap_reduction", "breach_days_reduction", "cost", "score"]].copy()
show["rank"] = show["rank"].map(lambda v: "—" if pd.isna(v) else str(int(v)))
def _improvement(name, gap_saved, days_saved):
    if name.startswith("On-time"):
        return "Reference"
    if name.startswith("Delayed"):
        return "Baseline for comparison"
    return (f"Gap {'−' if gap_saved >= 0 else '+'}{inr(abs(gap_saved))} · "
            f"breach days {'−' if days_saved >= 0 else '+'}{abs(int(days_saved))}")


show["improvement"] = [_improvement(n, g, d) for n, g, d in zip(show["scenario"], show["gap_reduction"], show["breach_days_reduction"])]
show = show[["rank", "scenario", "min_balance", "max_liquidity_gap", "breach_days", "affected_obligations", "recovery_date", "cost", "score", "improvement"]]
show["recovery_date"] = show["recovery_date"].map(lambda v: "—" if v is None or pd.isna(v) else pd.Timestamp(v).strftime("%d %b %Y"))
show["score"] = show["score"].map(lambda v: "—" if pd.isna(v) else f"{v:.1f}")
st.dataframe(ui.styled(show, ["min_balance", "max_liquidity_gap", "cost"]),
             hide_index=True, width="stretch",
             column_config={"rank": "Rank", "scenario": "Scenario", "min_balance": "Min. balance", "max_liquidity_gap": "Liquidity gap",
                            "breach_days": "Breach days", "affected_obligations": "Affected", "recovery_date": "Recovery",
                            "cost": "Cost", "score": "Score", "improvement": "Improvement vs delayed"})
st.plotly_chart(charts.scenario_bars(comp), width="stretch")

ui.section("Side-by-side comparison", "Select scenarios to compare directly.")
names = list(ok["scenario"])
pick = st.multiselect("Scenarios to compare", names, default=[n for n in ["Delayed - no action"] + list(best["scenario"]) if n in names][:3] or names[:2])
if pick:
    cols = st.columns(len(pick))
    for col, nm in zip(cols, pick):
        r = ok[ok.scenario == nm].iloc[0]
        with col:
            st.markdown(f"**{nm}**")
            st.metric("Min. balance", inr(r.min_balance)); st.metric("Liquidity gap", inr(r.max_liquidity_gap))
            st.metric("Breach days", int(r.breach_days)); st.metric("Affected obligations", int(r.affected_obligations))
            st.metric("Cost (simulated)", inr(r.cost))
            st.caption(f"Recovery: {r.recovery_date or 'n/a'}")
    pal = [charts.CYAN, charts.AMBER, charts.GREEN, charts.RED, "#a78bfa", "#f472b6"]
    st.plotly_chart(charts.balance_chart([(n, results[n].daily, pal[i % len(pal)], "solid") for i, n in enumerate(pick)], cfg.buffer,
                                         "Cash balance by scenario", 400, breach_shading=False), width="stretch")

ui.section("Assumptions and trade-offs")
for _, r in ok.iterrows():
    if r.assumptions or r.tradeoffs:
        with st.expander(r.scenario):
            st.markdown(f"**Assumptions:** {r.assumptions}\n\n**Trade-offs:** {r.tradeoffs or '—'}")
if st.button("Save scenario results to the database"):
    h = db.save_simulation(c.sha, dict(txn_id=txn, delay_days=delays[txn], buffer=cfg.buffer, horizon_days=cfg.horizon_days,
                                       opening_cash=cfg.opening_cash, start=str(cfg.start_date)), results["Delayed - no action"].summary)
    n = db.save_scenarios(h, comp)
    st.success(f"Saved {n} scenario row(s) under run {h}.")
st.caption("Simulation only: the app never contacts customers or suppliers, arranges loans or moves money.")
