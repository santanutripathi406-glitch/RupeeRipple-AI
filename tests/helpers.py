import datetime as dt

import pandas as pd

from core.ripple_engine import SimConfig
from core.validation import REQUIRED_COLUMNS, validate_dataframe

D0 = dt.date(2026, 1, 1)


def day(n):
    return (D0 + dt.timedelta(days=n)).isoformat()


def make_df(rows):
    """rows: (id, name, ttype, amount, due_off, exp_off|None, flex, status)"""
    recs = []
    for tid, name, tt, amt, due, exp, flex, status in rows:
        recs.append(dict(transaction_id=tid, entity_name=name, entity_type="customer" if tt == "receivable" else "supplier",
                         transaction_type=tt, amount=str(amt), due_date=day(due), expected_date="" if exp is None else day(exp),
                         status=status, related_entity="", flexibility=flex))
    vr = validate_dataframe(pd.DataFrame(recs, columns=REQUIRED_COLUMNS))
    assert vr.ok and not vr.n_errors, vr.issues
    return vr.clean


def cfg(opening=1000.0, buffer=200.0, horizon=30):
    return SimConfig(opening, buffer, D0, horizon)
