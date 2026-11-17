"""Reports and Export - PDF report and CSV downloads that match what the app displays."""
import streamlit as st

from core import database as db, state, ui
from core.ai_explainer import build_evidence, rules_answer
from core.data_processor import inr
from core.pipeline import run_intervention_lab, run_simulation
from core.report import (at_risk_csv, at_risk_table, build_pdf, build_report, comparison_csv, daily_csv, transactions_csv)

c = ui.setup("Reports", "📄")
ui.hero("Reports and Export", "A shareable simulation report and CSVs that exactly match the numbers shown in the app.")
ui.require_valid(c)
sc = state.ensure_sim_cfg(c)
run = run_simulation(c.df, c.settings, sc)
comp, _, _ = run_intervention_lab(c.df, c.settings, sc, st.session_state.get("scen_ivs"))
ev = build_evidence(c.df, run, comp)

parts = [rules_answer("What caused the financial risk?", ev), rules_answer("Which obligations are affected?", ev),
         rules_answer("Which intervention performed best?", ev)]
source = "Built-in rules engine"
last = st.session_state.get("last_ai")
if last and st.checkbox("Also include the latest AI Financial Intelligence answer", value=False):
    parts.append(f"Latest AI answer ({last['source']}): {last['text']}")
    source = "Built-in rules engine + latest AI answer"
explanation = "\n\n".join(parts)
rep = build_report(c.df, run, comp, explanation, source, c.is_sample, c.settings)

D, B = run["delayed"].summary, run["base"].summary
ui.section("Report preview", "Headline results from the same engine run as every other page.")
m = st.columns(4)
m[0].metric("Baseline min. balance", inr(B["min_balance"]))
m[1].metric("Delayed min. balance", inr(D["min_balance"]))
m[2].metric("Days below buffer", D["breach_days"])
m[3].metric("At-risk obligations", D["n_at_risk"])
with st.expander("Report text", expanded=True):
    st.markdown(f"**{rep['business']}** · generated {rep['generated']}\n\n"
                f"Window {D['start_date']} → {D['end_date']} · opening cash {inr(D['opening_cash'])} · buffer {inr(D['buffer'])}\n\n"
                f"**Explanation ({source})**\n\n{explanation}")
if c.is_sample:
    st.caption("Data in this report is synthetic demonstration data.")

ui.section("Downloads", "PDF report and CSV exports.")
def _log(title, fmt):
    try:
        db.save_report_meta(c.sha, title, fmt)
    except Exception:
        pass
pdf = build_pdf(rep)
st.download_button("Download PDF report", pdf, "rupeeripple_report.pdf", "application/pdf", type="primary", icon=":material/download:",
                   on_click=_log, args=("Simulation report", "pdf"))
a, b = st.columns(2)
items = [("Transactions", transactions_csv(c.df), "transactions.csv"), ("Daily cash-flow projection", daily_csv(run), "daily_cashflow.csv"),
         ("At-risk obligations", at_risk_csv(run), "at_risk_obligations.csv"), ("Scenario comparison", comparison_csv(comp), "scenario_comparison.csv")]
for i, (label, data, fn) in enumerate(items):
    (a if i % 2 == 0 else b).download_button(f"{label} (CSV)", data, fn, "text/csv", on_click=_log, args=(label, "csv"), width="stretch", icon=":material/download:")
st.caption("Exports are generated from the same engine run as the screens, so values match.")

with st.expander("Saved simulation runs and report log"):
    st.markdown("**Saved simulations**")
    st.dataframe(ui.styled(db.list_simulations(), ["min_balance"]), hide_index=True, width="stretch")
    st.markdown("**Exports log**")
    st.dataframe(db.list_reports(), hide_index=True, width="stretch")
