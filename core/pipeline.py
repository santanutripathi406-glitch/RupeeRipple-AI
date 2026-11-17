"""Single entry point that every page uses, so all pages show numbers from the same engine run."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from core.dependency_engine import build_graph, compute_criticality
from core.intervention_engine import default_interventions, run_scenarios
from core.ripple_engine import Adjustments, SimConfig, compare, contributors, simulate


def settings_cfg(settings: dict) -> SimConfig:
    return SimConfig(float(settings["opening_cash"]), float(settings["buffer"]),
                     dt.date.fromisoformat(str(settings["start_date"])), int(settings["horizon_days"]))


def active_cfg(settings: dict, sim_cfg: dict | None) -> SimConfig:
    """Simulation config = global settings, optionally overridden by simulator-page buffer/period."""
    base = settings_cfg(settings)
    sim_cfg = sim_cfg or {}
    return SimConfig(base.opening_cash, float(sim_cfg.get("buffer") or base.buffer), base.start_date,
                     int(sim_cfg.get("horizon_days") or base.horizon_days))


def delays_from(sim_cfg: dict | None) -> dict:
    sim_cfg = sim_cfg or {}
    if sim_cfg.get("txn_id") and int(sim_cfg.get("delay_days", 0)) != 0:
        return {sim_cfg["txn_id"]: int(sim_cfg["delay_days"])}
    return {}


def run_simulation(df: pd.DataFrame, settings: dict, sim_cfg: dict | None) -> dict:
    cfg = active_cfg(settings, sim_cfg)
    delays = delays_from(sim_cfg)
    ref = simulate(df, cfg)
    delayed = simulate(df, cfg, Adjustments(shifts=dict(delays)))
    crit, _ = compute_criticality(df, cfg, settings.get("weights"))
    return dict(cfg=cfg, delays=delays, base=ref, delayed=delayed, delta=compare(ref, delayed),
                contributors=contributors(delayed), crit=crit,
                graph=build_graph(df, cfg, crit, delayed if delays else ref))


def run_intervention_lab(df: pd.DataFrame, settings: dict, sim_cfg: dict | None, interventions: list | None = None):
    cfg = active_cfg(settings, sim_cfg)
    delays = delays_from(sim_cfg)
    ivs = interventions if interventions is not None else default_interventions(df, cfg, delays, settings["reserve_balance"])
    comp, results = run_scenarios(df, cfg, delays, ivs, settings["reserve_balance"])
    return comp, results, ivs


def health_status(summary: dict) -> tuple:
    """Transparent rules -> (label, level, reason). Level in {'ok','watch','risk','critical'}."""
    if summary["n_uncovered"] > 0 or summary["min_balance"] < 0:
        return ("Critical", "critical", "Projected cash is insufficient to cover at least one payment (balance below zero).")
    if summary["breach_days"] > 0:
        return ("At risk", "risk", f"Balance is below the safety buffer on {summary['breach_days']} projected day(s).")
    if summary["min_balance"] < 1.25 * summary["buffer"]:
        return ("Watch", "watch", "Balance stays above the buffer, but the lowest point is within 25% of it (thin headroom).")
    return ("Healthy", "ok", "Balance stays comfortably (>125%) above the safety buffer throughout the window.")
