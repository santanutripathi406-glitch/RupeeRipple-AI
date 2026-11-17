"""AI Financial Intelligence - evidence-based explanations + optional payment-delay model."""
import pandas as pd
import streamlit as st

from core import state, ui
from core.ai_explainer import SUGGESTED_QUESTIONS, answer, build_evidence, llm_config
from core.data_processor import inr
from core.pipeline import run_intervention_lab, run_simulation
from core.prediction_model import MIN_ROWS, get_model, predict_receivables

c = ui.setup("AI Financial Intelligence", "🧠")
ui.hero("AI Financial Intelligence", "Plain-language explanations built only from verified simulation output.")
ui.require_valid(c)
sc = state.ensure_sim_cfg(c)
run = run_simulation(c.df, c.settings, sc)
comp, _, _ = run_intervention_lab(c.df, c.settings, sc, st.session_state.get("scen_ivs"))
ev = build_evidence(c.df, run, comp)
key, model_name = llm_config()

ui.section("Key findings", "Verified engine output that every explanation is built from.")
k = st.columns(4)
with k[0]: ui.card("Lowest projected balance", inr(ev["delayed"]["min_balance"]), f"baseline {inr(ev['baseline']['min_balance'])}")
with k[1]: ui.card("Liquidity gap vs buffer", inr(ev["delayed"]["max_liquidity_gap"]), f"{ev['delayed']['breach_days']} day(s) below the buffer")
with k[2]: ui.card("At-risk obligations", str(ev["delayed"]["n_at_risk"]), f"baseline {ev['baseline']['n_at_risk']}")
with k[3]: ui.card("Best simulated option", ev["best_scenario"]["scenario"] if ev["best_scenario"] else "n/a", f"score {ev['best_scenario']['score']}" if ev["best_scenario"] else "no ranked option yet")
ui.section("Assistant")
tab_chat, tab_model, tab_ev = st.tabs(["Explain the result", "Payment-delay model (ML)", "Evidence used"])
with tab_chat:
    st.markdown(ui.pill("Explanation engine", "") + " " + ui.pill(("Configured LLM (" + model_name + ") with rules-engine fallback") if key else "Built-in rules engine (no LLM API key configured)", "teal" if key else "green"), unsafe_allow_html=True)
    if not run["delays"]:
        ui.note("No payment delay is active; answers describe the baseline. Set a delay in the Ripple Simulator for a richer explanation.")
    q = None
    cols = st.columns(3)
    for i, s in enumerate(SUGGESTED_QUESTIONS):
        if cols[i % 3].button(s, key=f"sq{i}", width="stretch"):
            q = s
    typed = st.chat_input("Ask about the simulation (e.g. 'Which obligations are affected?')")
    q = typed or q
    hist = st.session_state.setdefault("chat", [])
    if q:
        res = answer(q, ev, [{"role": m["role"], "content": m["content"]} for m in hist])
        hist += [dict(role="user", content=q), dict(role="assistant", content=res["text"], note=res["note"], source=res["source"])]
        st.session_state.last_ai = dict(text=res["text"], source=res["source"], note=res["note"])
    if not hist:
        st.info("Pick a suggested question or type your own. Answers cite only figures the engine calculated.")
    for m in hist:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m["role"] == "assistant":
                st.markdown(ui.pill("LLM" if m["source"] == "llm" else "Rules engine", "teal" if m["source"] == "llm" else "green") + f' <span style="color:#6b7468;font-size:.8rem">{m["note"]}</span>', unsafe_allow_html=True)
    if hist and st.button("Clear conversation"):
        st.session_state.chat = []
        st.rerun()
    st.caption("Estimates and assumptions are labelled. This is decision support, not financial advice.")

with tab_model:
    st.markdown("An optional scikit-learn model estimates how likely each pending receivable is to be paid late. "
                "**The ripple simulator does not use it**; it only suggests delays worth testing.")
    bundle = get_model(c.df)
    st.markdown(f"Training data: **{bundle.source}**")
    if not bundle.available:
        st.warning(bundle.reason)
    else:
        m = bundle.metrics
        st.caption(f"Chronological split: {bundle.n_train} training / {bundle.n_test} test invoices. Late = paid more than 3 days after due date. "
                   f"Late share in test period: {m['test_late_share']:.0%}.")
        cl = pd.DataFrame(m["classifier"]).T.rename_axis("model").reset_index()
        st.markdown("**Late-payment classifier (test period)**")
        st.dataframe(cl, hide_index=True, width="stretch", column_config={k: st.column_config.NumberColumn(format="%.2f") for k in cl.columns[1:]})
        r = m["regressor"]
        st.markdown("**Delay-days regressor — mean absolute error (days, lower is better)**")
        st.dataframe(pd.DataFrame({"model": ["Ridge regression", "Baseline: customer's prior average", "Baseline: global mean"],
                                   "MAE (days)": [r["ridge_mae_days"], r["baseline_customer_prior_avg_mae_days"], r["baseline_global_mean_mae_days"]]}),
                     hide_index=True, width="stretch")
        if r["ridge_mae_days"] >= r["baseline_customer_prior_avg_mae_days"]:
            st.info("On this test period the regression model does **not** beat the simple 'customer's prior average delay' baseline, so treat expected-delay figures as rough.")
        preds = predict_receivables(bundle, c.df)
        if len(preds):
            st.markdown("**Pending receivables**")
            st.dataframe(preds, hide_index=True, width="stretch",
                         column_config={"prob_late": st.column_config.ProgressColumn("P(late)", min_value=0, max_value=1, format="%.2f"),
                                        "expected_delay_days": st.column_config.NumberColumn("Indicative delay (days)", format="%.1f")})
        with st.expander("Limitations"):
            st.markdown("\n".join(f"- {x}" for x in bundle.limitations) +
                        f"\n- Needs at least {MIN_ROWS} paid-receivable history rows from your data; otherwise the bundled synthetic history is used and labelled.")

with tab_ev:
    st.caption("This structured evidence (computed by Python) is all the explanation layer may use.")
    st.json(ev, expanded=False)
