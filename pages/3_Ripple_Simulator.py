"""Ripple Effect Simulator - delay one receivable and watch the shock propagate."""
import streamlit as st

from core import charts, database as db, state, ui
from core.ai_explainer import ASSUMPTIONS
from core.data_processor import inr
from core.dependency_engine import build_graph
from core.pipeline import active_cfg, run_simulation
from core.prediction_model import get_model, predict_receivables
from core.report import at_risk_table

c = ui.setup("Ripple Simulator", "🌊")
ui.hero("Ripple Effect Simulator", "Delay an incoming customer payment and see which obligations, and which days, become risky.")
ui.require_valid(c)
sc = state.ensure_sim_cfg(c)
rec = c.df[(c.df["transaction_type"] == "receivable") & (c.df["status"] != "paid")]
if rec.empty:
    st.info("There are no pending receivables to delay. Add some in the Data Centre.")
    st.stop()

g = c.settings
cur = rec[rec["transaction_id"] == sc["txn_id"]]
cur_customer = cur["entity_name"].iloc[0] if len(cur) else rec["entity_name"].iloc[0]
ui.section("Scenario configuration", "Choose the receivable to delay and the simulation window.")
with st.container(border=True):
    col = st.columns(5)
    customers = sorted(rec["entity_name"].unique())
    customer = col[0].selectbox("Customer", customers, index=customers.index(cur_customer) if cur_customer in customers else 0)
    opts = rec[rec["entity_name"] == customer]
    ids = list(opts["transaction_id"])
    idx = ids.index(sc["txn_id"]) if sc["txn_id"] in ids else 0
    txn = col[1].selectbox("Receivable", ids, index=idx,
                           format_func=lambda i: f"{i} · {inr(opts.loc[opts.transaction_id == i, 'amount'].iloc[0])} · due {opts.loc[opts.transaction_id == i, 'expected_date'].iloc[0]}")
    delay = col[2].slider("Payment delay (days)", 0, 90, int(sc["delay_days"]), help="How many days later than expected the customer pays.")
    horizon = col[3].slider("Simulation period (days)", 15, 180, int(sc["horizon_days"] or g["horizon_days"]))
    buf = col[4].number_input("Safety buffer (₹)", min_value=0.0, value=float(sc["buffer"] or g["buffer"]), step=10000.0)
    sc.update(txn_id=txn, delay_days=int(delay),
              horizon_days=None if int(horizon) == int(g["horizon_days"]) else int(horizon),
              buffer=None if float(buf) == float(g["buffer"]) else float(buf))

run = run_simulation(c.df, c.settings, sc)
B, D, delta, cfg = run["base"].summary, run["delayed"].summary, run["delta"], run["cfg"]
row = rec[rec.transaction_id == txn].iloc[0]
arrives = run["delayed"].events.query("transaction_id == @txn")
arr_txt = f"{arrives['effective_date'].iloc[0]:%d %b %Y}" if len(arrives) else "after the simulation window"
ui.section("Simulation results")
st.markdown(f"**Scenario:** {row.entity_name}'s payment of **{inr(row.amount)}** (expected {row.expected_date:%d %b %Y}) arrives **{delay} day(s) late → {arr_txt}**.")

m = st.columns(6)
m[0].metric("Minimum balance", inr(D["min_balance"]), inr(D["min_balance"] - B["min_balance"]) if delta["min_balance_change"] else None)
m[1].metric("Liquidity gap vs buffer", inr(D["max_liquidity_gap"]), inr(delta["gap_change"]) if delta["gap_change"] else None, delta_color="inverse")
m[2].metric("Days below buffer", D["breach_days"], delta["breach_days_change"] or None, delta_color="inverse")
m[3].metric("First buffer breach", f"{D['first_breach_date']:%d %b}" if D["first_breach_date"] else "None")
m[4].metric("At-risk obligations", D["n_at_risk"], delta["at_risk_change"] or None, delta_color="inverse")
m[5].metric("Recovery date", f"{D['recovery_date']:%d %b}" if D["recovery_date"] else ("—" if not D["first_breach_date"] else "Not in window"))

if D["max_cash_shortfall"] > 0:
    st.error(f"Projected cash falls **{inr(D['max_cash_shortfall'])} below zero** at its lowest point: at least one payment could not be covered from projected cash. "
             "This is a projection, not a statement that the business has defaulted.")
elif D["breach_days"] > 0:
    st.warning(f"The balance dips **{inr(D['max_liquidity_gap'])} below the safety buffer** but stays above zero. "
               "This is a *buffer breach*, not an inability to pay.")
else:
    st.success("With this delay the projected balance never drops below the safety buffer in the window.")

series = [("Baseline (on time)", run["base"].daily, charts.CYAN, "solid"), ("With delay", run["delayed"].daily, charts.AMBER, "solid")]
ui.section("Cash-flow comparison", "Baseline (teal) against the delayed-receipt scenario (amber).")
st.plotly_chart(charts.balance_chart(series, cfg.buffer, "Baseline vs delayed cash balance", 420), width="stretch")

a, b = st.columns(2)
with a: st.plotly_chart(charts.cash_in_out(run["base"].daily), width="stretch")
with b: st.plotly_chart(charts.cash_in_out(run["delayed"].daily), width="stretch")
st.caption("Left: baseline cash in/out. Right: with the delayed receipt.")

ui.section("Financial impact", "Obligations made riskier by the delay are outlined and joined by red edges.")
affected = set(delta["newly_at_risk"])
G = build_graph(c.df, cfg, run["crit"], run["delayed"])
st.plotly_chart(charts.dependency_graph(G, txn, affected), width="stretch")
st.caption("Highlighted (white outline, red edge) nodes are obligations whose risk gets worse because of the delay. Dotted cyan edges are inferred by a liquidity test.")

ui.section("Affected obligations", "Status with the delay, next to the baseline status.")
ar = at_risk_table(run)
if len(ar):
    st.dataframe(ui.styled(ar[["transaction_id", "entity_name", "transaction_type", "effective_date", "amount", "flexibility", "risk", "baseline_risk", "balance_after"]],
                           ["amount", "balance_after"], ["effective_date"]),
                 hide_index=True, width="stretch",
                 column_config={"transaction_id": "ID", "entity_name": "Payee", "transaction_type": "Type", "flexibility": "Flexibility",
                                "effective_date": "Payment date", "amount": "Amount", "risk": "Status with delay",
                                "baseline_risk": "Baseline status", "balance_after": "Balance after"})
else:
    st.success("No obligations are at risk in this scenario.")
ct = run["contributors"]
if len(ct):
    ui.section("Contributing payments", "Obligations paid between the first and last buffer-breach day.")
    st.dataframe(ui.styled(ct, ["amount", "balance_after"], ["effective_date"]), hide_index=True, width="stretch",
                 column_config={"transaction_id": "ID", "entity_name": "Payee", "transaction_type": "Type", "effective_date": "Payment date",
                                "amount": "Amount", "flexibility": "Flexibility", "risk": "Status", "balance_after": "Balance after"})
    st.caption(f"These payments fall between the first ({D['first_breach_date']}) and last ({D['last_breach_date']}) breach days; "
               f"the delayed receipt of {inr(row.amount)} is the root cause in this scenario. {len(delta['newly_at_risk'])} obligation(s) are newly at risk versus baseline.")

with st.expander("Assumptions used (always visible)"):
    st.markdown("\n".join(f"- {a}" for a in ASSUMPTIONS) +
                "\n- Items dated before the start date are projected on the start date.\n- Same-day items: receipts first, then payments ordered by due date and ID.")

p = predict_receivables(get_model(c.df), c.df)
if len(p) and txn in set(p["transaction_id"]):
    pr = p[p.transaction_id == txn].iloc[0]
    if not (pr.prob_late != pr.prob_late):
        st.caption(f"💡 Optional ML hint (not used by the simulator): the payment-delay model estimates a {pr.prob_late:.0%} chance this customer pays late, "
                   f"with an indicative delay of about {pr.expected_delay_days:.0f} day(s). See AI Financial Intelligence for model limits.")

if st.button("Save this simulation to the database"):
    h = db.save_simulation(c.sha, dict(txn_id=txn, delay_days=int(delay), buffer=cfg.buffer, horizon_days=cfg.horizon_days,
                                       opening_cash=cfg.opening_cash, start=str(cfg.start_date)), D)
    st.success(f"Saved (run id {h}). Re-saving identical settings does not create duplicates.")
