"""Shared Streamlit session state so every page works on the same validated dataset."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import streamlit as st

from core import database as db
from core.data_processor import dataset_hash, default_settings, load_sample_raw, suggest_start_date
from core.dependency_engine import compute_criticality
from core.pipeline import settings_cfg
from core.validation import validate_dataframe

PERSIST_KEYS = ["opening_cash", "buffer", "horizon_days", "reserve_balance", "weights", "start_date"]


def _persist_settings():
    snap = {k: st.session_state.settings[k] for k in PERSIST_KEYS}
    if st.session_state.get("_saved_settings") != snap:
        db.set_setting("settings", snap)
        st.session_state["_saved_settings"] = snap


def _reset_derived():
    for k in ("sim_cfg", "scen_ivs", "chat", "last_ai"):
        st.session_state.pop(k, None)


def init_state():
    if st.session_state.get("_init"):
        return
    try:
        db.init_db()
        source = db.get_setting("active_source", "sample")
        saved = db.get_setting("settings", None)
    except Exception:  # database unavailable (read-only host): run in-memory
        source, saved = "sample", None
    raw = None
    if source != "sample":
        raw = db.load_dataset(source)
        if raw is None:
            source = "sample"
    if source == "sample":
        raw = load_sample_raw()
    settings = default_settings()
    if saved:
        for k in PERSIST_KEYS:
            if k in saved and not (k == "start_date" and source == "sample"):
                settings[k] = saved[k]
    st.session_state.update(raw=raw, source=source, settings=settings, _init=True)


def load_sample():
    st.session_state.update(raw=load_sample_raw(), source="sample", settings=default_settings())
    _reset_derived()
    try:
        db.set_setting("active_source", "sample")
        _persist_settings()
    except Exception:
        pass


def set_dataset(raw, name: str):
    """Make ``raw`` (string DataFrame) the active dataset. Safe to call repeatedly with the same data."""
    sha = dataset_hash(raw)
    changed = sha != dataset_hash(st.session_state.raw)
    st.session_state.raw = raw
    try:
        sha = db.save_dataset(raw, name)
        db.set_setting("active_source", sha)
    except Exception:
        pass
    if st.session_state.source == "sample" or changed:
        st.session_state.source = sha
        vr = validate_dataframe(raw)
        if vr.ok:
            st.session_state.settings["start_date"] = suggest_start_date(vr.clean).isoformat()
    if changed:
        _reset_derived()
    try:
        _persist_settings()
    except Exception:
        pass


def ctx() -> SimpleNamespace:
    vr = validate_dataframe(st.session_state.raw)
    return SimpleNamespace(raw=st.session_state.raw, vr=vr, df=vr.clean, settings=st.session_state.settings,
                           source=st.session_state.source, is_sample=st.session_state.source == "sample",
                           sha=dataset_hash(st.session_state.raw))


def ensure_sim_cfg(c) -> dict:
    """Default simulation: delay the most critical receivable by 10 days."""
    sc = st.session_state.get("sim_cfg")
    ids = set(c.df["transaction_id"]) if c.vr.ok else set()
    if sc and sc.get("txn_id") in ids:
        return sc
    txn = None
    if c.vr.ok:
        crit, _ = compute_criticality(c.df, settings_cfg(c.settings), c.settings.get("weights"))
        if len(crit):
            txn = crit.iloc[0]["transaction_id"]
    sc = dict(txn_id=txn, delay_days=10, buffer=None, horizon_days=None)
    st.session_state.sim_cfg = sc
    return sc
