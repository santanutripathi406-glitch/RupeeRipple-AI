"""Sample data, templates, defaults and dataset summaries."""
from __future__ import annotations

import datetime as dt
import hashlib
import pathlib

import pandas as pd

from core.validation import REQUIRED_COLUMNS, read_csv_bytes

ROOT = pathlib.Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / "data" / "sample_data.csv"
SAMPLE_ANCHOR = dt.date(2026, 1, 1)   # day 0 of the committed sample file
SAMPLE_BUSINESS = "Madurai Handloom Traders (synthetic demo business)"

DEFAULT_WEIGHTS = {"amount": 0.25, "timing": 0.15, "dependency": 0.30, "buffer": 0.20, "flexibility": 0.10}
SAMPLE_SETTINGS = {"opening_cash": 500000.0, "buffer": 150000.0, "horizon_days": 60,
                   "reserve_balance": 150000.0, "weights": dict(DEFAULT_WEIGHTS)}


def default_settings(start: dt.date | None = None) -> dict:
    s = dict(SAMPLE_SETTINGS)
    s["weights"] = dict(DEFAULT_WEIGHTS)
    s["start_date"] = (start or dt.date.today()).isoformat()
    return s


def load_sample_raw(shift_to: dt.date | None = None) -> pd.DataFrame:
    """Read the committed synthetic CSV; shift all dates so that day 0 equals ``shift_to`` (default today)."""
    raw, err = read_csv_bytes(SAMPLE_PATH.read_bytes())
    if err:  # pragma: no cover
        raise RuntimeError(err)
    target = shift_to or dt.date.today()
    delta = (target - SAMPLE_ANCHOR).days
    for c in ("due_date", "expected_date"):
        raw[c] = (pd.to_datetime(raw[c]) + pd.Timedelta(days=delta)).dt.strftime("%Y-%m-%d")
    return raw


def template_csv() -> str:
    rows = [
        ["INV-001", "Example Customer", "customer", "receivable", "100000", "2026-01-15", "2026-01-18", "pending", "", "fixed"],
        ["BILL-001", "Example Supplier", "supplier", "payable", "60000", "2026-01-20", "", "pending", "Example Customer", "flexible"],
        ["PAY-001", "Staff Payroll", "employee", "payroll", "90000", "2026-01-31", "", "pending", "", "fixed"],
    ]
    return pd.DataFrame(rows, columns=REQUIRED_COLUMNS).to_csv(index=False)


def dataset_hash(raw: pd.DataFrame) -> str:
    return hashlib.sha256(raw.to_csv(index=False).encode("utf-8")).hexdigest()[:16]


def suggest_start_date(clean: pd.DataFrame) -> dt.date:
    if clean is None or clean.empty:
        return dt.date.today()
    return min(min(clean["due_date"]), min(clean["expected_date"]))


def dataset_summary(clean: pd.DataFrame) -> dict:
    if clean is None or clean.empty:
        return {}
    active = clean[clean["status"] != "paid"]
    rec = active[active["transaction_type"] == "receivable"]
    out = active[active["transaction_type"] != "receivable"]
    return dict(
        n_transactions=len(clean), n_active=len(active), n_paid=int((clean["status"] == "paid").sum()),
        n_receivables=len(rec), n_obligations=len(out),
        receivable_total=float(rec["amount"].sum()), obligation_total=float(out["amount"].sum()),
        n_customers=int(rec["entity_name"].nunique()), n_payees=int(out["entity_name"].nunique()),
        n_flexible=int((out["flexibility"] == "flexible").sum()),
        first_date=min(min(active["due_date"]), min(active["expected_date"])) if len(active) else None,
        last_date=max(max(active["due_date"]), max(active["expected_date"])) if len(active) else None,
        by_type=active.groupby("transaction_type")["amount"].agg(["count", "sum"]).reset_index())


def inr(x: float) -> str:
    """Format a rupee amount with Indian digit grouping."""
    neg = x < 0
    s = f"{abs(round(x)):d}"
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return f"{'-' if neg else ''}₹{s}"
