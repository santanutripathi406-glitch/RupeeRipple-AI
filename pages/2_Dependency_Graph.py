"""Financial Dependency Graph with transparent, configurable criticality scores."""
import streamlit as st

from core import charts, ui
from core.data_processor import inr
from core.dependency_engine import build_graph, downstream, graph_metrics
from core.pipeline import run_simulation
from core import state

c = ui.setup("Dependency Graph", "🕸️")
ui.hero("Financial Dependency Graph", "Who pays you, who you pay, and which incoming payment the rest of the month depends on.")
ui.require_valid(c)
sc = state.ensure_sim_cfg(c)
run = run_simulation(c.df, c.settings, sc)
crit = run["crit"]
if crit.empty:
    st.info("No pending receivables fall inside the simulation window, so there is no incoming-payment graph yet.")
    st.stop()

ui.section("Network view", "Who pays the business, who the business pays, and how risk concentrates.")
l, r, t = st.columns([2, 1, 1])
sel = l.selectbox("Highlight a receivable", crit["transaction_id"],
                  format_func=lambda i: f"{i} · {crit.loc[crit.transaction_id == i, 'entity_name'].iloc[0]} · {inr(crit.loc[crit.transaction_id == i, 'amount'].iloc[0])}")
use_delay = r.toggle("Show risk under the active delay scenario", value=False, help="Otherwise node risk shows the baseline (no delay).")
show_all = t.toggle("Show all dependency edges", value=False)
sim = run["delayed"] if (use_delay and run["delays"]) else run["base"]
G = build_graph(c.df, run["cfg"], crit, sim)
affected = set(run["delta"]["newly_at_risk"]) if (use_delay and run["delays"]) else set()
gm = graph_metrics(G)
m = st.columns(5)
m[0].metric("Nodes", gm["nodes"]); m[1].metric("Incoming sources", gm["customers"]); m[2].metric("Obligations", gm["obligations"])
m[3].metric("Declared edges", gm["declared_edges"]); m[4].metric("Inferred edges", gm["inferred_edges"])
st.plotly_chart(charts.dependency_graph(G, sel, affected, show_all), width="stretch")
ui.note("<b>Reading the graph.</b> Circles are incoming payments (red/amber/teal = high/medium/low criticality); squares are obligations "
        "(green covered · amber breaches buffer · red cannot be covered). Solid cyan lines are links <b>declared in your data</b> "
        "(<code>related_entity</code>). Dotted cyan lines are <b>inferred</b> by a liquidity test — they show which obligations would get riskier "
        "if that payment never arrived in the window, and do <b>not</b> prove any contractual relationship.")

row = crit[crit.transaction_id == sel].iloc[0]
deps = downstream(G, sel)
st.subheader(f"{row.entity_name} · {sel}")
st.markdown(f"Criticality **{row.score:.0f}/100 ({row.level})**. If this payment did not arrive inside the window, "
            f"**{len(deps)}** later obligation(s) worth **{inr(row.dependent_value)}** would become riskier: "
            + (", ".join(deps) if deps else "none") + ".")

ui.section("Criticality scores", "Five transparent factors, weighted in the sidebar.")
st.dataframe(ui.styled(crit[["transaction_id", "entity_name", "amount", "arrival_date", "days_until", "amount_factor", "timing_factor", "dependency_factor",
                   "buffer_factor", "flexibility_factor", "score", "level", "n_dependents", "dependent_value"]], ["amount", "dependent_value"], ["arrival_date"]),
             hide_index=True, width="stretch",
             column_config={"transaction_id": "ID", "entity_name": "Customer", "amount": "Amount", "arrival_date": "Expected", "days_until": "Days until",
                            "level": "Level", "n_dependents": "Dependents", "dependent_value": "Dependent value", "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.1f"),
                            **{k: st.column_config.NumberColumn(k.replace("_factor", ""), format="%.2f") for k in
                               ["amount_factor", "timing_factor", "dependency_factor", "buffer_factor", "flexibility_factor"]}})
w = c.settings["weights"]
with st.expander("Scoring formula (configurable in the sidebar)"):
    st.markdown(f"""**Score (0–100) = 100 × Σ weightᵢ × factorᵢ / Σ weights**, every factor in 0–1:

| Factor | Weight | Definition |
|---|---|---|
| amount | {w['amount']:.2f} | payment ÷ largest pending receivable |
| timing | {w['timing']:.2f} | 1 − days until arrival ÷ window length (sooner = more critical) |
| dependency | {w['dependency']:.2f} | value of obligations that become riskier if the payment never arrives ÷ total outgoing in window |
| buffer | {w['buffer']:.2f} | 1 − (baseline lowest balance − buffer) ÷ payment (little headroom = more critical) |
| flexibility | {w['flexibility']:.2f} | share of those dependent obligations that are *fixed* (cannot be rescheduled) |

Levels: **High** ≥ 60 · **Medium** 30–60 · **Low** < 30.""")
