"""Plotly figures (light editorial fintech theme). Pure functions of engine outputs."""
from __future__ import annotations

import networkx as nx
import plotly.graph_objects as go

from core.data_processor import inr
from core.dependency_engine import BUSINESS

NAVY, CARD, TEAL, CYAN, GREEN, AMBER, RED, MUTED = "#ffffff", "#ffffff", "#2f6b4f", "#2a7f7f", "#2f6b4f", "#b7791f", "#b4443c", "#8a9288"
INK, GRID = "#1f2a24", "#ece8de"
RISK_COLOR = {"Covered": GREEN, "Breaches buffer": AMBER, "Cannot be covered": RED, "": MUTED}


def _layout(fig, title="", height=380):
    fig.update_layout(template="plotly_white", title=dict(text=title, font=dict(size=14, color=INK), x=0, xanchor="left"), height=height,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#ffffff",
                      margin=dict(l=10, r=10, t=48, b=10), legend=dict(orientation="h", y=-0.18, font=dict(size=11)),
                      font=dict(family="Inter, Segoe UI, sans-serif", color=INK, size=12),
                      hoverlabel=dict(bgcolor="#ffffff", bordercolor="#cfc9ba", font=dict(color=INK, size=12)))
    fig.update_xaxes(gridcolor=GRID, linecolor="#cfc9ba", zeroline=False)
    fig.update_yaxes(gridcolor=GRID, linecolor="#cfc9ba", zeroline=False)
    return fig


def _short(v):
    a, sign = abs(v), ("−" if v < 0 else "")
    if a >= 1e7:
        return f"{sign}₹{a / 1e7:g}Cr"
    if a >= 1e5:
        return f"{sign}₹{a / 1e5:g}L"
    if a >= 1e3:
        return f"{sign}₹{a / 1e3:g}k"
    return f"{sign}₹{a:g}"


def _inr_axis(fig, vmin, vmax):
    """Y-axis ticks in Indian units (₹50k, ₹2L, ₹1Cr) instead of western k/M."""
    import math
    vmin, vmax = min(float(vmin), 0.0), max(float(vmax), 0.0)
    span = max(vmax - vmin, 1.0)
    step = 10_000_000
    for st_ in (10_000, 20_000, 25_000, 50_000, 100_000, 200_000, 250_000, 500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000):
        if span / st_ <= 6:
            step = st_
            break
    lo, hi = math.floor(vmin / step) * step, math.ceil(vmax / step) * step
    vals = [lo + i * step for i in range(int(round((hi - lo) / step)) + 1)]
    fig.update_yaxes(tickvals=vals, ticktext=[_short(v) for v in vals])


def cash_in_out(daily):
    fig = go.Figure()
    fig.add_bar(x=daily["date"], y=daily["inflow"], name="Cash in", marker_color=GREEN, customdata=[inr(v) for v in daily["inflow"]],
                hovertemplate="%{x|%d %b %Y}<br>Cash in: %{customdata}<extra></extra>")
    fig.add_bar(x=daily["date"], y=-daily["outflow"], name="Cash out", marker_color=RED, customdata=[inr(v) for v in daily["outflow"]],
                hovertemplate="%{x|%d %b %Y}<br>Cash out: %{customdata}<extra></extra>")
    fig.update_layout(barmode="relative")
    _inr_axis(fig, -daily["outflow"].max(), daily["inflow"].max())
    return _layout(fig, "Cash-in vs cash-out")


def balance_chart(series, buffer, title="Projected daily cash balance", height=380, breach_shading=True):
    """series: list of (name, daily_df, color, dash)."""
    fig = go.Figure()
    for name, daily, color, dash in series:
        fig.add_scatter(x=daily["date"], y=daily["balance"], name=name, mode="lines",
                        line=dict(color=color, width=2.5, dash=dash, shape="hv"),
                        customdata=[inr(v) for v in daily["balance"]],
                        hovertemplate="%{x|%d %b %Y}<br>" + name + ": %{customdata}<extra></extra>")
    fig.add_hline(y=buffer, line=dict(color=AMBER, dash="dot"), annotation_text=f"Safety buffer {inr(buffer)}",
                  annotation_position="top left")
    fig.add_hline(y=0, line=dict(color=RED, width=1))
    if breach_shading and series:
        last = series[-1][1]
        below = last[last["below_buffer"]]
        if len(below):
            fig.add_vrect(x0=below["date"].iloc[0], x1=below["date"].iloc[-1], fillcolor=AMBER, opacity=0.10, line_width=0)
    _inr_axis(fig, min(d["balance"].min() for _, d, _, _ in series) if series else 0,
              max([d["balance"].max() for _, d, _, _ in series] + [buffer]))
    return _layout(fig, title, height)


def timeline(events, window=None):
    fig = go.Figure()
    for direction, color, name in (("in", GREEN, "Incoming"), ("out", RED, "Outgoing")):
        e = events[events["direction"] == direction]
        if window:
            e = e[(e["effective_date"] >= window[0]) & (e["effective_date"] <= window[1])]
        fig.add_scatter(x=e["effective_date"], y=e["amount"] * (1 if direction == "in" else -1), mode="markers",
                        name=name, marker=dict(size=(e["amount"] / max(events["amount"].max(), 1) * 28 + 8),
                                               color=color, opacity=0.85, line=dict(width=1, color="#ffffff")),
                        text=e["entity_name"] + " (" + e["transaction_id"] + ")",
                        hovertemplate="%{text}<br>%{x|%d %b %Y}<br>%{customdata}<extra></extra>",
                        customdata=[inr(v) for v in e["amount"]])
    fig.add_hline(y=0, line=dict(color=MUTED, width=1))
    ins, outs = events[events["direction"] == "in"]["amount"], events[events["direction"] == "out"]["amount"]
    _inr_axis(fig, -(outs.max() if len(outs) else 0), ins.max() if len(ins) else 0)
    fig.update_yaxes(title="Incoming (+) / outgoing (−)")
    return _layout(fig, "Upcoming payment timeline")


def dependency_graph(G: nx.DiGraph, selected: str | None = None, affected: set | None = None, show_all_deps=False,
                     height=760):
    affected = affected or set()
    recs = sorted([n for n, d in G.nodes(data=True) if d["kind"] == "customer"], key=lambda n: (G.nodes[n]["date"], n))
    obls = sorted([n for n, d in G.nodes(data=True) if d["kind"] == "obligation"], key=lambda n: (G.nodes[n]["date"], n))
    pos = {BUSINESS: (0.0, 0.0)}

    def spread(n):
        return [0.0] if n == 1 else [8.0 - i * 16.0 / (n - 1) for i in range(n)]
    for n, y in zip(recs, spread(len(recs))):
        pos[n] = (-1.0, y)
    for n, y in zip(obls, spread(len(obls))):
        pos[n] = (1.0, y)
    fig = go.Figure()
    max_in = max([G.nodes[n]["amount"] for n in recs] + [1])

    def line(u, v, color, width, dash="solid", hover=None):
        fig.add_scatter(x=[pos[u][0], pos[v][0]], y=[pos[u][1], pos[v][1]], mode="lines", showlegend=False,
                        line=dict(color=color, width=width, dash=dash), hoverinfo="text" if hover else "skip", text=hover)

    for u, v, d in G.edges(data=True):
        if d["kind"] == "inflow":
            line(u, v, "rgba(47,107,79,.42)", 1.2 + 3.2 * G.nodes[u]["amount"] / max_in)
        elif d["kind"] == "outflow":
            hot = v in affected
            line(u, v, RED if hot else "rgba(138,146,136,.38)", 2.6 if hot else 1.0)
        elif d["kind"] == "dependency" and (show_all_deps or u == selected):
            declared = d["basis"] == "declared"
            line(u, v, CYAN, 2.0 if declared else 1.2, "solid" if declared else "dot",
                 hover=f"{'Declared in data (related_entity)' if declared else 'Inferred by liquidity test (not a proven contract)'}")
    for kind, nodes, symbol in (("customer", recs, "circle"), ("obligation", obls, "square")):
        xs = [pos[n][0] for n in nodes]
        ys = [pos[n][1] for n in nodes]
        colors, sizes, borders, widths, texts, hovers = [], [], [], [], [], []
        mx = max([G.nodes[x]["amount"] for x in nodes] + [1])
        for n in nodes:
            d = G.nodes[n]
            if kind == "customer":
                colors.append({"High": RED, "Medium": AMBER, "Low": GREEN}.get(d["level"], GREEN))
                sizes.append(13 + 20 * d["amount"] / mx)
                sel = n == selected
                borders.append(INK if sel else "#ffffff")
                widths.append(3 if sel else 1.5)
                hovers.append(f"<b>{d['label']}</b> ({n})<br>Incoming {inr(d['amount'])}<br>Expected {d['date']}"
                              f"<br>Criticality {d['score']}/100 ({d['level']})")
            else:
                colors.append(RISK_COLOR.get(d["risk"], MUTED))
                sizes.append(11 + 14 * d["amount"] / mx)
                hot = n in affected
                borders.append(INK if hot else "#ffffff")
                widths.append(3 if hot else 1.5)
                hovers.append(f"<b>{d['label']}</b> ({n})<br>{d['txn_type']} - {d['flexibility']}<br>Pay {inr(d['amount'])} on {d['date']}"
                              f"<br>Risk: {d['risk'] or 'n/a'}")
            texts.append(f"{d['label'][:22]}<br><span style='color:#6b7468'>{inr(d['amount'])} · {d['date'].strftime('%d %b')}</span>")
        fig.add_scatter(x=xs, y=ys, mode="markers+text", name=kind,
                        marker=dict(size=sizes, color=colors, symbol=symbol, opacity=1, line=dict(width=widths, color=borders)),
                        text=texts, textposition="middle left" if kind == "customer" else "middle right",
                        textfont=dict(size=10, color=INK), hovertext=hovers, hoverinfo="text", showlegend=False)
    fig.add_scatter(x=[0], y=[0], mode="markers+text", text=["<b>BUSINESS</b>"], textposition="top center", textfont=dict(size=11, color=INK),
                    marker=dict(size=40, color="#17261f", symbol="diamond", opacity=1, line=dict(width=2, color="#ffffff")),
                    hoverinfo="text", hovertext="Central business entity", showlegend=False)
    # legend (presentation only)
    for name, color, symbol in (("Incoming - high criticality", RED, "circle"), ("Incoming - medium", AMBER, "circle"),
                                ("Incoming - low", GREEN, "circle"), ("Obligation - covered", GREEN, "square"),
                                ("Obligation - breaches buffer", AMBER, "square"), ("Obligation - cannot be covered", RED, "square")):
        fig.add_scatter(x=[None], y=[None], mode="markers", name=name, marker=dict(size=9, color=color, symbol=symbol), showlegend=True)
    for name, color, dash in (("Declared link", CYAN, "solid"), ("Inferred link", CYAN, "dot")):
        fig.add_scatter(x=[None], y=[None], mode="lines", name=name, line=dict(color=color, width=2, dash=dash), showlegend=True)
    fig.update_xaxes(visible=False, range=[-2.7, 2.7])
    fig.update_yaxes(visible=False)
    _layout(fig, "Financial dependency graph", height)
    fig.update_layout(legend=dict(orientation="h", y=-0.04, x=0, font=dict(size=10)), plot_bgcolor="#fbfaf7")
    return fig


def scenario_bars(comp):
    c = comp[comp["feasible"]]
    fig = go.Figure()
    fig.add_bar(x=c["scenario"], y=c["min_balance"], name="Minimum balance", marker_color=GREEN, customdata=[inr(v) for v in c["min_balance"]],
                hovertemplate="%{x}<br>Minimum balance: %{customdata}<extra></extra>")
    fig.add_bar(x=c["scenario"], y=c["max_liquidity_gap"], name="Liquidity gap vs buffer", marker_color=AMBER,
                customdata=[inr(v) for v in c["max_liquidity_gap"]], hovertemplate="%{x}<br>Liquidity gap: %{customdata}<extra></extra>")
    _inr_axis(fig, c["min_balance"].min(), max(c["min_balance"].max(), c["max_liquidity_gap"].max()))
    fig.update_layout(barmode="group")
    fig.update_xaxes(tickangle=-20)
    _layout(fig, "Scenario comparison", 470)
    fig.update_layout(legend=dict(orientation="h", y=-0.62, x=0, font=dict(size=11)), margin=dict(l=10, r=10, t=48, b=20))
    return fig
