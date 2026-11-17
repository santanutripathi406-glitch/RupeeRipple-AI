"""Report content, CSV exports and PDF generation. All numbers come from the same engine results
that the pages display, so exports and screens always agree."""
from __future__ import annotations

import datetime as dt
import io

import pandas as pd

from core.data_processor import SAMPLE_BUSINESS, dataset_summary, inr
from core.ripple_engine import BUFFER, UNCOVERED


def transactions_csv(df: pd.DataFrame) -> str:
    return df.to_csv(index=False)


def daily_csv(run: dict) -> str:
    b, d = run["base"].daily, run["delayed"].daily
    out = b[["date", "inflow", "outflow", "balance"]].rename(columns={"inflow": "baseline_inflow", "outflow": "baseline_outflow", "balance": "baseline_balance"})
    out["delayed_inflow"], out["delayed_outflow"], out["delayed_balance"] = d["inflow"].values, d["outflow"].values, d["balance"].values
    out["delayed_below_buffer"] = d["below_buffer"].values
    return out.to_csv(index=False)


def at_risk_table(run: dict) -> pd.DataFrame:
    ev = run["delayed"].events
    o = ev[(ev["direction"] == "out") & ev["risk"].isin([BUFFER, UNCOVERED])]
    base_r = dict(zip(run["base"].events["transaction_id"], run["base"].events["risk"]))
    t = o[["transaction_id", "entity_name", "transaction_type", "effective_date", "amount", "flexibility", "risk",
           "balance_before", "balance_after", "uncovered_amount"]].copy()
    t["baseline_risk"] = t["transaction_id"].map(base_r).fillna("")
    return t.reset_index(drop=True)


def at_risk_csv(run: dict) -> str:
    return at_risk_table(run).to_csv(index=False)


def comparison_csv(comp: pd.DataFrame) -> str:
    return comp.to_csv(index=False)


def build_report(df, run, comp, explanation_text: str, source_label: str, is_sample: bool, settings: dict) -> dict:
    s = dataset_summary(df)
    bs, ds = run["base"].summary, run["delayed"].summary
    return dict(
        title="RupeeRipple AI - Financial Ripple Simulation Report",
        generated=dt.datetime.now().strftime("%d %b %Y %H:%M"),
        business=SAMPLE_BUSINESS if is_sample else "Uploaded business dataset",
        is_sample=is_sample, settings=settings, dataset=s, base=bs, delayed=ds, run=run, comp=comp,
        explanation=explanation_text, explanation_source=source_label)


def build_pdf(rep: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], textColor=colors.HexColor("#0b1426"))
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=colors.HexColor("#0f766e"))
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=colors.HexColor("#475569"))

    def money(x):  # reportlab core fonts lack the rupee glyph
        return inr(x).replace("₹", "Rs ")

    def clean(t):
        return str(t).replace("₹", "Rs ").replace("**", "").replace("_", "").replace("·", "-").replace("−", "-")

    def tbl(rows, widths=None):
        t = Table(rows, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#94a3b8")),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return t

    b, d, ds, run, comp = rep["base"], rep["delayed"], rep["dataset"], rep["run"], rep["comp"]
    st = []
    st += [Paragraph(rep["title"], h1), Paragraph(f"Generated {rep['generated']}", small)]
    if rep["is_sample"]:
        st.append(Paragraph("Data shown is SYNTHETIC demonstration data for a fictional business.", small))
    st.append(Paragraph("Simulation output for decision support only. Not financial advice. No transactions are executed.", small))
    st += [Paragraph("1. Business overview", h2), Paragraph(clean(
        f"{rep['business']}. Opening cash {money(rep['settings']['opening_cash'])}; safety buffer {money(d['buffer'])}; "
        f"window {d['start_date']} to {d['end_date']} ({d['horizon_days']} days)."), body)]
    st += [Paragraph("2. Dataset summary", h2), Paragraph(clean(
        f"{ds['n_transactions']} records ({ds['n_active']} active, {ds['n_paid']} paid). {ds['n_receivables']} receivables worth "
        f"{money(ds['receivable_total'])} from {ds['n_customers']} customers; {ds['n_obligations']} obligations worth "
        f"{money(ds['obligation_total'])} to {ds['n_payees']} payees ({ds['n_flexible']} flexible)."), body)]
    G = run["graph"]
    from core.dependency_engine import graph_metrics
    gm = graph_metrics(G)
    st += [Paragraph("3. Financial dependency summary", h2), Paragraph(clean(
        f"Graph: {gm['nodes']} nodes, {gm['edges']} edges ({gm['declared_edges']} declared and {gm['inferred_edges']} inferred dependency edges). "
        "Inferred edges come from a liquidity test and do not prove contractual relationships."), body)]
    crit = run["crit"].head(5)
    if len(crit):
        st.append(tbl([["Receivable", "Customer", "Amount", "Expected", "Score", "Level", "Dependents"]] + [
            [r.transaction_id, r.entity_name, money(r.amount), str(r.arrival_date), r.score, r.level, r.n_dependents] for r in crit.itertuples()]))
    st.append(Paragraph("4. Baseline cash-flow results", h2))
    st.append(tbl([["Metric", "Baseline (no delay)"], ["Minimum balance", money(b["min_balance"])], ["Minimum balance date", str(b["min_balance_date"])],
                   ["Days below buffer", b["breach_days"]], ["At-risk obligations", b["n_at_risk"]], ["Closing balance", money(b["closing_balance"])]], [70 * mm, 70 * mm]))
    dl = run["delays"]
    st.append(Paragraph("5. Delayed-payment simulation", h2))
    st.append(Paragraph(clean("Delay applied: " + (", ".join(f"{k} by {v} day(s)" for k, v in dl.items()) or "none")), body))
    st.append(tbl([["Metric", "Baseline", "Delayed"], ["Minimum balance", money(b["min_balance"]), money(d["min_balance"])],
                   ["Liquidity gap vs buffer", money(b["max_liquidity_gap"]), money(d["max_liquidity_gap"])],
                   ["Max cash shortfall (below zero)", money(b["max_cash_shortfall"]), money(d["max_cash_shortfall"])],
                   ["Days below buffer", b["breach_days"], d["breach_days"]], ["First breach", str(b["first_breach_date"]), str(d["first_breach_date"])],
                   ["Recovery date", str(b["recovery_date"]), str(d["recovery_date"])], ["At-risk obligations", b["n_at_risk"], d["n_at_risk"]]],
                  [60 * mm, 50 * mm, 50 * mm]))
    st.append(Paragraph("6. At-risk obligations", h2))
    ar = at_risk_table(run)
    if len(ar):
        st.append(tbl([["ID", "Payee", "Due", "Amount", "Status", "Balance after"]] + [
            [r.transaction_id, r.entity_name, str(r.effective_date), money(r.amount), r.risk, money(r.balance_after)] for r in ar.itertuples()]))
    else:
        st.append(Paragraph("No obligations are projected to be at risk.", body))
    st.append(Paragraph("7. Intervention comparison", h2))
    if comp is not None and len(comp):
        rows = [["Scenario", "Min balance", "Gap", "Breach days", "Affected", "Cost", "Score", "Rank"]]
        for r in comp[comp["feasible"]].itertuples():
            rows.append([r.scenario, money(r.min_balance), money(r.max_liquidity_gap), r.breach_days, r.affected_obligations, money(r.cost),
                         "-" if pd.isna(r.score) else r.score, "-" if pd.isna(r.rank) else int(r.rank)])
        st.append(tbl(rows))
        bad = comp[~comp["feasible"]]
        for r in bad.itertuples():
            st.append(Paragraph(clean(f"Not feasible - {r.scenario}: {r.note}"), small))
    st.append(Paragraph("8. Explanation of the selected scenario", h2))
    st.append(Paragraph(clean(f"[{rep['explanation_source']}]"), small))
    for para in clean(rep["explanation"]).split("\n"):
        if para.strip():
            st.append(Paragraph(para.replace("- ", "&bull; ", 1) if para.startswith("- ") else para, body))
    st.append(Paragraph("9. Assumptions and limitations", h2))
    from core.ai_explainer import ASSUMPTIONS
    for a in ASSUMPTIONS + ["Opening cash, buffer and reserve are user-entered values.", "The model of obligations is deterministic; real counterparties may behave differently."]:
        st.append(Paragraph("&bull; " + clean(a), body))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                      title=rep["title"]).build(st)
    return buf.getvalue()
