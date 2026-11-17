"""Shared page chrome: design system (CSS tokens), sidebar settings, KPI cards, section headings.
Presentation only - settings widgets, session keys and return values are unchanged."""
from __future__ import annotations

import datetime as dt
import pathlib

import pandas as pd
import streamlit as st

from core import state
from core.data_processor import DEFAULT_WEIGHTS, inr

ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"
VERSION = "v1.0"

_LATIN = "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD"
_LATIN_EXT = "U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF"


def _font_faces() -> str:
    """Self-hosted Inter / Manrope (served by Streamlit static serving), so no external font request is needed."""
    out = []
    for fam, weights in (("Inter", (400, 500, 600)), ("Manrope", (500, 600, 700))):
        for w in weights:
            for sub, rng in (("latin-ext", _LATIN_EXT), ("latin", _LATIN)):
                out.append(f"@font-face{{font-family:'{fam}';font-style:normal;font-weight:{w};font-display:swap;"
                           f"src:url(app/static/fonts/{fam.lower()}-{sub}-{w}-normal.woff2) format('woff2');unicode-range:{rng}}}")
    return "\n".join(out)


CSS = """
<style>
/*FONTS*/
:root{
  --rr-bg:#f5f3ee; --rr-surface:#ffffff; --rr-border:#e2ded3; --rr-border-strong:#cfc9ba;
  --rr-text:#1f2a24; --rr-muted:#6b7468; --rr-forest:#2f6b4f; --rr-forest-dark:#17261f;
  --rr-teal:#2a7f7f; --rr-amber:#b7791f; --rr-red:#b4443c;
  --rr-font:'Inter','Segoe UI',-apple-system,BlinkMacSystemFont,Roboto,'Helvetica Neue',Arial,sans-serif;
  --rr-head:'Manrope','Inter','Segoe UI',-apple-system,Arial,sans-serif;
}
html,body,.stApp{font-family:var(--rr-font)}
[data-testid="stIconMaterial"],span[class*="material-symbols"]{font-family:"Material Symbols Rounded"!important}
h1,h2,h3,h4{font-family:var(--rr-head)!important;color:var(--rr-text);letter-spacing:-.01em}
.stApp{background:var(--rr-bg)}
.block-container{padding:2rem 2.6rem 3rem;max-width:1240px}
footer{visibility:hidden}
header[data-testid="stHeader"]{background:transparent}

/* page header */
.rr-pagehead{padding:2px 0 14px;margin-bottom:18px;border-bottom:1px solid var(--rr-border)}
.rr-pagehead .eyebrow{font-size:.7rem;font-weight:600;letter-spacing:.09em;text-transform:uppercase;color:var(--rr-forest)}
.rr-pagehead h1{font-size:1.55rem;font-weight:700;margin:2px 0 2px;padding:0}
.rr-pagehead p{margin:0;color:var(--rr-muted);font-size:.92rem}

/* section headings */
.rr-section{margin:26px 0 10px}
.rr-section h3{font-size:1.02rem;font-weight:700;margin:0;padding:0;color:var(--rr-text)}
.rr-section p{margin:2px 0 0;color:var(--rr-muted);font-size:.84rem}
[data-testid="stHeading"] h2,[data-testid="stHeading"] h3{font-size:1.02rem!important;font-weight:700!important}

/* KPI cards */
.rr-card{min-height:122px;background:var(--rr-surface);border:1px solid var(--rr-border);border-radius:8px;padding:13px 15px;height:100%;
  transition:border-color .15s ease}
.rr-card:hover{border-color:var(--rr-border-strong)}
.rr-card .l{color:var(--rr-muted);font-size:.7rem;font-weight:500;text-transform:uppercase;letter-spacing:.06em}
.rr-card .v{color:var(--rr-text);font-family:var(--rr-head);font-size:1.42rem;font-weight:700;margin-top:4px;line-height:1.2}
.rr-card .s{color:var(--rr-muted);font-size:.76rem;margin-top:4px;line-height:1.35}
.rr-card.rr-ok{border-left:3px solid var(--rr-forest)}
.rr-card.rr-watch{border-left:3px solid var(--rr-teal)}
.rr-card.rr-risk{border-left:3px solid var(--rr-amber)}
.rr-card.rr-critical{border-left:3px solid var(--rr-red)}
.rr-card .v.rr-ok{color:var(--rr-forest)}.rr-card .v.rr-watch{color:var(--rr-teal)}
.rr-card .v.rr-risk{color:var(--rr-amber)}.rr-card .v.rr-critical{color:var(--rr-red)}

/* native st.metric */
[data-testid="stMetric"]{background:var(--rr-surface);border:1px solid var(--rr-border);border-radius:8px;padding:12px 14px}
[data-testid="stMetricLabel"] p{white-space:normal!important;overflow:visible!important;text-overflow:clip!important;color:var(--rr-muted);font-size:.74rem;text-transform:uppercase;letter-spacing:.05em;font-weight:500}
[data-testid="stMetricValue"]{font-family:var(--rr-head);font-weight:700;font-size:1.35rem}

/* notes, pills */
.rr-note{background:#eef3ee;border:1px solid #d7e2d9;border-left:3px solid var(--rr-forest);padding:9px 13px;border-radius:6px;color:#33443a;font-size:.86rem;margin:6px 0}
.rr-pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:.74rem;font-weight:500;border:1px solid var(--rr-border-strong);color:var(--rr-muted);background:#fff}
.rr-pill.green{color:var(--rr-forest);border-color:#b9d2c3;background:#eef5f0}
.rr-pill.amber{color:#8a5a12;border-color:#e6cfa3;background:#fbf4e6}
.rr-pill.red{color:var(--rr-red);border-color:#e3b9b5;background:#fbefee}
.rr-pill.teal{color:var(--rr-teal);border-color:#b5d6d6;background:#edf6f6}
.rr-legend{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:.78rem;color:var(--rr-muted);margin:4px 0 8px}
.rr-legend span.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:baseline}
.rr-legend span.sq{border-radius:2px}

/* inputs, buttons */
.stButton>button,.stDownloadButton>button{border-radius:6px;font-weight:500;border:1px solid var(--rr-border-strong);
  transition:background-color .15s ease,border-color .15s ease}
.stButton>button:hover,.stDownloadButton>button:hover{border-color:var(--rr-forest);color:var(--rr-forest)}
.stButton>button[kind="primary"],.stDownloadButton>button[kind="primary"]{background:var(--rr-forest);border-color:var(--rr-forest);color:#fff}
.stButton>button[kind="primary"]:hover,.stDownloadButton>button[kind="primary"]:hover{background:#245640;border-color:#245640;color:#fff}
[data-testid="stFileUploader"] section{background:var(--rr-surface);border:1.5px dashed var(--rr-border-strong);border-radius:8px;transition:border-color .15s ease}
[data-testid="stFileUploader"] section:hover{border-color:var(--rr-forest)}
[data-baseweb="tab-list"]{gap:4px;border-bottom:1px solid var(--rr-border)}
[data-baseweb="tab"]{font-weight:500}
[data-testid="stExpander"]{border:1px solid var(--rr-border);border-radius:8px;background:var(--rr-surface)}
[data-testid="stAlert"]{border-radius:6px}
[data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]){background:#eef3ee;border:1px solid #d7e2d9;border-left:3px solid #2a7f7f}
[data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]) *{color:#33443a}
[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]){background:#eef5f0;border:1px solid #cfe2d6;border-left:3px solid #2f6b4f}
[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]) *{color:#245640}
[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]){background:#fbf4e6;border:1px solid #ecd9b0;border-left:3px solid #b7791f}
[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]) *{color:#6f4a10}
[data-testid="stAlert"]:has([data-testid="stAlertContentError"]){background:#fbefee;border:1px solid #ecc6c2;border-left:3px solid #b4443c}
[data-testid="stAlert"]:has([data-testid="stAlertContentError"]) *{color:#7e2a24}
[data-testid="stVerticalBlockBorderWrapper"]{border-radius:8px}
hr{border-color:var(--rr-border)!important}
[data-testid="stDataFrame"]{border:1px solid var(--rr-border);border-radius:8px;overflow:hidden}
[data-testid="stChatMessage"]{background:var(--rr-surface);border:1px solid var(--rr-border);border-radius:8px}

/* responsive */
@media (max-width:900px){
  .block-container{padding:3.6rem 1rem 2rem}
  .rr-pagehead h1{font-size:1.3rem}
  .rr-card{min-height:0}
  .rr-card .v{font-size:1.2rem}
}
@media (max-width:640px){
  .rr-pagehead p{font-size:.85rem}
  [data-testid="stMetricValue"]{font-size:1.15rem}
}

/* sidebar */
[data-testid="stSidebar"]{border-right:1px solid #0f1b15}
[data-testid="stSidebar"] h3{font-size:.8rem!important;text-transform:uppercase;letter-spacing:.08em;color:#9fb5a8!important;font-weight:600!important}
[data-testid="stSidebar"] hr{border-color:#2c4438!important}
[data-testid="stSidebar"] [data-testid="stExpander"]{background:transparent;border:1px solid #2c4438}
[data-testid="stSidebar"] [data-testid="stExpander"] summary,[data-testid="stSidebar"] [data-testid="stExpander"] summary *{color:#e8ede9}
[data-testid="stSidebarNavLink"]{border-radius:6px;margin:1px 0;transition:background-color .15s ease}
[data-testid="stSidebarNavLink"]:hover{background:rgba(159,208,180,.10)}
[data-testid="stSidebarNavLink"][aria-current="page"]{background:rgba(159,208,180,.16);box-shadow:inset 3px 0 0 #9fd0b4;font-weight:600}
[data-testid="stSidebarNavLink"]::before{font-family:"Material Symbols Rounded";font-size:18px;margin-right:8px;color:#9fd0b4;
  font-feature-settings:"liga";font-weight:normal;line-height:1}
[data-testid="stSidebarNavLink"][href$="/Data_Centre"]::before{content:"database"}
[data-testid="stSidebarNavLink"][href$="/Dependency_Graph"]::before{content:"hub"}
[data-testid="stSidebarNavLink"][href$="/Ripple_Simulator"]::before{content:"waves"}
[data-testid="stSidebarNavLink"][href$="/Intervention_Lab"]::before{content:"science"}
[data-testid="stSidebarNavLink"][href$="/AI_Intelligence"]::before{content:"auto_awesome"}
[data-testid="stSidebarNavLink"][href$="/Reports"]::before{content:"description"}
[data-testid="stSidebarNavLink"]:has(span[label="app"])::before{content:"dashboard"}
[data-testid="stSidebarNavLink"] span[label="app"] p{font-size:0!important}
[data-testid="stSidebarNavLink"] span[label="app"] p::after{content:"Overview";font-size:.95rem}
.rr-side-desc{color:#9fb5a8;font-size:.8rem;line-height:1.45;margin:2px 0 10px}
.rr-side-ver{color:#7f9588;font-size:.72rem;margin-top:14px;padding-top:10px;border-top:1px solid #2c4438}
</style>
"""

PAGE_ICONS = {"Overview": ":material/dashboard:", "Data Centre": ":material/database:", "Dependency Graph": ":material/hub:",
              "Ripple Simulator": ":material/waves:", "Intervention Lab": ":material/science:",
              "AI Financial Intelligence": ":material/auto_awesome:", "Reports": ":material/description:"}


def card(label: str, value: str, sub: str = "", cls: str = ""):
    st.markdown(f'<div class="rr-card {cls}"><div class="l">{label}</div><div class="v {cls}">{value}</div>'
                f'<div class="s">{sub}</div></div>', unsafe_allow_html=True)


def hero(title: str, sub: str):
    st.markdown(f'<div class="rr-pagehead"><div class="eyebrow">RupeeRipple AI</div><h1>{title}</h1><p>{sub}</p></div>',
                unsafe_allow_html=True)


def section(title: str, caption: str = ""):
    st.markdown(f'<div class="rr-section"><h3>{title}</h3>' + (f"<p>{caption}</p>" if caption else "") + "</div>",
                unsafe_allow_html=True)


def pill(text: str, kind: str = "") -> str:
    return f'<span class="rr-pill {kind}">{text}</span>'


def legend(items):
    """items: (label, hex colour, 'dot'|'sq')"""
    html = "".join(f'<div><span class="dot {"sq" if s == "sq" else ""}" style="background:{c}"></span>{l}</div>' for l, c, s in items)
    st.markdown(f'<div class="rr-legend">{html}</div>', unsafe_allow_html=True)


def note(text: str):
    st.markdown(f'<div class="rr-note">{text}</div>', unsafe_allow_html=True)


def styled(df: pd.DataFrame, money=(), dates=(), extra=None):
    """Return a Styler that shows rupee amounts with Indian digit grouping (₹4,80,000) and readable dates,
    while the underlying values stay numeric / date so sorting still works."""
    def _m(v):
        return "—" if v is None or pd.isna(v) else inr(v)

    def _d(v):
        return "—" if v is None or pd.isna(v) else pd.Timestamp(v).strftime("%d %b %Y")
    fmt = {c: _m for c in money if c in df.columns}
    fmt.update({c: _d for c in dates if c in df.columns})
    fmt.update({c: f for c, f in (extra or {}).items() if c in df.columns})
    return df.style.format(fmt)


def setup(title: str, icon: str = "💧"):
    """Call first on every page. Returns the shared context."""
    st.set_page_config(page_title=f"{title} · RupeeRipple AI", page_icon=PAGE_ICONS.get(title, ":material/water_drop:"), layout="wide")
    st.markdown(CSS.replace("/*FONTS*/", _font_faces()), unsafe_allow_html=True)
    try:
        st.logo(str(ASSETS / "logo.svg"), icon_image=str(ASSETS / "logo_icon.svg"), size="large")
    except Exception:
        pass
    state.init_state()
    _sidebar()
    return state.ctx()


def _sidebar():
    s = st.session_state.settings
    with st.sidebar:
        st.markdown('<div class="rr-side-desc">Cash-flow ripple intelligence for small businesses: see how one late payment spreads, '
                    'and what to do about it.</div>', unsafe_allow_html=True)
        st.markdown(pill("Synthetic sample data" if st.session_state.source == "sample" else "Your dataset",
                         "teal" if st.session_state.source == "sample" else "green"), unsafe_allow_html=True)
        st.markdown("### Settings")
        s["opening_cash"] = float(st.number_input("Opening cash balance (₹)", min_value=0.0, value=float(s["opening_cash"]), step=10000.0))
        st.caption(inr(s["opening_cash"]))
        s["buffer"] = float(st.number_input("Minimum cash safety buffer (₹)", min_value=0.0, value=float(s["buffer"]), step=10000.0))
        st.caption(inr(s["buffer"]))
        s["reserve_balance"] = float(st.number_input("Available cash reserve (₹)", min_value=0.0, value=float(s["reserve_balance"]), step=10000.0,
                                                     help="Separate from opening cash; only used by the 'Use existing cash reserve' intervention."))
        st.caption(inr(s["reserve_balance"]))
        s["start_date"] = st.date_input("Simulation start date", value=dt.date.fromisoformat(str(s["start_date"]))).isoformat()
        s["horizon_days"] = int(st.slider("Simulation window (days)", 15, 180, int(s["horizon_days"])))
        with st.expander("Criticality score weights"):
            w = dict(s.get("weights") or DEFAULT_WEIGHTS)
            for k, lab in (("amount", "Payment amount"), ("timing", "Time until payment"), ("dependency", "Dependent obligations"),
                           ("buffer", "Buffer headroom"), ("flexibility", "Inflexible dependents")):
                w[k] = st.slider(lab, 0.0, 1.0, float(w.get(k, DEFAULT_WEIGHTS[k])), 0.05)
            s["weights"] = w
        try:
            state._persist_settings()
        except Exception:
            pass
        st.caption("Synthetic data and simulations only. Not financial advice.")
        st.markdown(f'<div class="rr-side-ver">RupeeRipple AI · {VERSION}</div>', unsafe_allow_html=True)


def require_valid(c) -> None:
    """Show an empty/error state and stop the page when the dataset is unusable."""
    if c.vr.ok:
        return
    st.error("The active dataset cannot be used yet.")
    for f in c.vr.fatal:
        st.warning(f)
    if c.vr.n_valid == 0 and not c.vr.fatal:
        st.warning("All records have validation errors. Fix them in the Data Centre.")
    st.page_link("pages/1_Data_Centre.py", label="Open the Data Centre to load or repair data", icon=":material/database:")
    st.stop()
