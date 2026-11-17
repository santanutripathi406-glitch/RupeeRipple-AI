"""RupeeRipple AI - Overview Dashboard (entry point)."""
import datetime as dt

import pandas as pd
import streamlit as st

from core import charts, ui
from core.data_processor import dataset_summary, inr
from core.pipeline import health_status, run_simulation
from core.report import at_risk_table
from core.ripple_engine import BUFFER, UNCOVERED

c = ui.setup("Overview")
ui.hero("RupeeRipple AI", "Understand the ripple effect before a financial delay becomes a business disruption.")
ui.require_valid(c)

run = run_simulation(c.df, c.settings, None)          # baseline only (no delay) - shared engine
base, cfg = run["base"], run["cfg"]
S = base.summary
ds = dataset_summary(c.df)
if c.vr.n_errors:
    st.warning(f"{c.vr.n_errors} record(s) failed validation and are excluded from every calculation. "
               "Review them in the Data Centre.")

ui.section("Monitoring window", "Charts and tables below follow this date range and these transaction types.")
c1, c2 = st.columns([2, 1])
with c1:
    rng = st.slider("Date range", min_value=cfg.start_date, max_value=cfg.end_date, value=(cfg.start_date, cfg.end_date), format="DD MMM YYYY")
with c2:
    types = st.multiselect("Transaction types", sorted(c.df["transaction_type"].unique()), default=sorted(c.df["transaction_type"].unique()))

daily = base.daily[(base.daily["date"] >= rng[0]) & (base.daily["date"] <= rng[1])]
ev = base.events[(base.events["effective_date"] >= rng[0]) & (base.events["effective_date"] <= rng[1])]
ev = ev[(ev["transaction_type"].isin(types)) | (ev["transaction_type"] == "reserve")]
label, level, reason = health_status(S)

ui.section("Key indicators", "Baseline projection from the active dataset (no payment delay applied).")
cols = st.columns(6)
with cols[0]: ui.card("Available cash today", inr(cfg.opening_cash), "opening balance")
with cols[1]: ui.card("Expected incoming", inr(ev.loc[ev.direction == "in", "amount"].sum()), "in selected range")
with cols[2]: ui.card("Upcoming obligations", inr(ev.loc[ev.direction == "out", "amount"].sum()), "in selected range")
with cols[3]: ui.card("Projected min. balance", inr(daily["balance"].min()), f"on {daily.loc[daily['balance'].idxmin(), 'date']:%d %b}")
with cols[4]: ui.card("At-risk obligations", str(len(ev[(ev.direction == 'out') & ev.risk.isin([BUFFER, UNCOVERED])])), f"safety buffer {inr(cfg.buffer)}")
with cols[5]: ui.card("Financial health", label, reason[:48] + "…" if len(reason) > 48 else reason, f"rr-{level}")
with st.expander("How is financial health decided?"):
    st.markdown("- **Critical**: projected balance goes below zero / a payment cannot be covered.\n"
                "- **At risk**: balance is below the safety buffer on at least one day.\n"
                "- **Watch**: lowest balance is within 25% above the buffer.\n- **Healthy**: otherwise.\n\n"
                f"Current result: **{label}** — {reason}")

ui.section("Cash flow")
l, r = st.columns(2)
with l: st.plotly_chart(charts.cash_in_out(daily), width="stretch")
with r: st.plotly_chart(charts.balance_chart([("Projected balance", daily, charts.CYAN, "solid")], cfg.buffer), width="stretch")
st.plotly_chart(charts.timeline(base.events, rng), width="stretch")

ui.section("At-risk obligations", "Payments projected to breach the safety buffer or exceed projected cash, baseline scenario.")
ar = at_risk_table(run)
ar = ar[(ar["effective_date"] >= rng[0]) & (ar["effective_date"] <= rng[1])] if len(ar) else ar
if len(ar):
    st.dataframe(ui.styled(ar[["transaction_id", "entity_name", "effective_date", "amount", "risk", "balance_after"]], ["amount", "balance_after"], ["effective_date"]),
                 hide_index=True, width="stretch",
                 column_config={"transaction_id": "ID", "entity_name": "Payee", "effective_date": "Payment date",
                                "amount": "Amount", "risk": "Status", "balance_after": "Balance after"})
else:
    st.success("No obligation is projected to breach the safety buffer in this range under the baseline.")

l, r = st.columns([3, 2])
with l:
    ui.section("Most critical incoming payments", "Ranked by the transparent criticality score.")
    cr = run["crit"].head(5)
    st.dataframe(ui.styled(cr[["transaction_id", "entity_name", "amount", "arrival_date", "score", "level", "n_dependents"]], ["amount"], ["arrival_date"]),
                 hide_index=True, width="stretch",
                 column_config={"transaction_id": "ID", "entity_name": "Customer", "amount": "Amount",
                                "arrival_date": "Expected", "level": "Level", "n_dependents": "Deps",
                                "score": st.column_config.ProgressColumn("Criticality", min_value=0, max_value=100, format="%.0f")})
with r:
    ui.section("Financial risk summary")
    st.markdown(f"- **{ds['n_receivables']}** pending receivables ({inr(ds['receivable_total'])}) from **{ds['n_customers']}** customers\n"
                f"- **{ds['n_obligations']}** upcoming obligations ({inr(ds['obligation_total'])}); **{ds['n_flexible']}** are flexible\n"
                f"- Lowest projected balance **{inr(S['min_balance'])}** on {S['min_balance_date']:%d %b %Y}\n"
                f"- Days below buffer: **{S['breach_days']}**; at-risk obligations: **{S['n_at_risk']}**\n"
                + (f"- Most critical payment: **{cr.iloc[0]['entity_name']}** ({inr(cr.iloc[0]['amount'])}, score {cr.iloc[0]['score']:.0f})\n" if len(cr) else ""))
    ui.note("Next: open <b>Ripple Simulator</b> from the sidebar and delay the most critical payment.")
st.caption("All figures are computed live from the active dataset by the deterministic simulation engine. Synthetic demo data is labelled in the sidebar.")
