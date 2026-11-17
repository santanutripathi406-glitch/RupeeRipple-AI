"""Optional payment-delay prediction (scikit-learn). It is NEVER used by the ripple simulator.

* History comes from the user's own PAID receivables when there are enough of them (for paid rows the
  ``expected_date`` column is read as the actual payment date); otherwise a clearly-labelled synthetic
  history bundled with the app is used.
* Features for each invoice use only EARLIER invoices of the same customer (expanding statistics shifted by
  one), and the train/test split is chronological, so there is no look-ahead leakage.
* Metrics are computed on the held-out test period and compared against simple baselines.
"""
from __future__ import annotations

import datetime as dt
import pathlib
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

HISTORY_PATH = pathlib.Path(__file__).resolve().parents[1] / "data" / "payment_history_sample.csv"
MIN_ROWS = 60
LATE_GRACE_DAYS = 3
FEATURES = ["prior_avg_delay", "prior_late_rate", "prior_count", "log_amount", "terms_days"]


def generate_synthetic_history(seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    profile = {  # customer: (mean delay when late, probability late)  - purely synthetic
        "Kaveri Retail Mart": (9, 0.55), "Chennai Fashion Hub": (6, 0.45), "Coimbatore Sarees Co": (2, 0.12),
        "Madurai Silks Outlet": (8, 0.5), "Trichy Garments Co": (5, 0.35), "Salem Uniform Supply": (1, 0.08)}
    rows = []
    start = dt.date(2024, 1, 1)
    for cust, (mu, p_late) in profile.items():
        base_amt = {"Kaveri Retail Mart": 400000, "Chennai Fashion Hub": 200000}.get(cust, 150000)
        for k in range(30):
            due = start + dt.timedelta(days=int(k * 24 + rng.integers(0, 6)))
            late = rng.random() < p_late
            delay = int(max(0, rng.normal(mu, 3))) if late else int(rng.integers(0, 3))
            amt = round(float(base_amt * rng.uniform(0.6, 1.3)), 2)
            terms = int(rng.choice([15, 30, 45]))
            rows.append(dict(customer=cust, amount=amt, terms_days=terms, due_date=due,
                             paid_date=due + dt.timedelta(days=delay)))
    return pd.DataFrame(rows).sort_values(["due_date", "customer"]).reset_index(drop=True)


def load_synthetic_history() -> pd.DataFrame:
    if HISTORY_PATH.exists():
        h = pd.read_csv(HISTORY_PATH, parse_dates=["due_date", "paid_date"])
        h["due_date"], h["paid_date"] = h["due_date"].dt.date, h["paid_date"].dt.date
        return h
    return generate_synthetic_history()


def history_from_user_data(clean: pd.DataFrame) -> pd.DataFrame:
    p = clean[(clean["transaction_type"] == "receivable") & (clean["status"] == "paid")]
    return pd.DataFrame(dict(customer=p["entity_name"], amount=p["amount"], terms_days=30,
                             due_date=p["due_date"], paid_date=p["expected_date"])).reset_index(drop=True)


def _features(h: pd.DataFrame) -> pd.DataFrame:
    h = h.copy()
    h["due_date"], h["paid_date"] = pd.to_datetime(h["due_date"]), pd.to_datetime(h["paid_date"])
    h = h.sort_values(["due_date", "customer"], kind="mergesort").reset_index(drop=True)
    h["delay"] = (h["paid_date"] - h["due_date"]).dt.days.clip(lower=0)
    h["late"] = (h["delay"] > LATE_GRACE_DAYS).astype(int)
    g = h.groupby("customer")
    h["prior_avg_delay"] = g["delay"].transform(lambda s: s.shift(1).expanding().mean()).fillna(0.0)
    h["prior_late_rate"] = g["late"].transform(lambda s: s.shift(1).expanding().mean()).fillna(0.0)
    h["prior_count"] = g.cumcount()
    h["log_amount"] = np.log1p(h["amount"])
    return h


@dataclass
class ModelBundle:
    available: bool
    reason: str = ""
    source: str = ""
    metrics: dict = field(default_factory=dict)
    clf: object = None
    reg: object = None
    history: pd.DataFrame | None = None
    n_train: int = 0
    n_test: int = 0
    limitations: list = field(default_factory=lambda: [
        "Trained on a small history; estimates are indicative, not guarantees.",
        "Assumes each customer's future behaviour resembles its past behaviour.",
        "Ignores macro events, disputes and invoice-level circumstances.",
        "The ripple simulator does not use these predictions; they are only a suggestion for a delay to test."])


def train_model(history: pd.DataFrame, source: str) -> ModelBundle:
    if history is None or len(history) < MIN_ROWS:
        n = 0 if history is None else len(history)
        return ModelBundle(False, f"Only {n} paid-receivable history rows found; at least {MIN_ROWS} are needed. "
                                  "Prediction is unavailable rather than unreliable.", source)
    f = _features(history)
    cut = int(len(f) * 0.75)
    train, test = f.iloc[:cut], f.iloc[cut:]
    if train["late"].nunique() < 2 or test["late"].nunique() < 2:
        return ModelBundle(False, "History does not contain both late and on-time payments in both the training and "
                                  "test periods, so a classifier cannot be evaluated.", source)
    clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, class_weight="balanced"))
    clf.fit(train[FEATURES], train["late"])
    prob = clf.predict_proba(test[FEATURES])[:, 1]
    pred = (prob >= 0.5).astype(int)
    dummy = DummyClassifier(strategy="most_frequent").fit(train[FEATURES], train["late"])
    rule = (test["prior_late_rate"] >= 0.5).astype(int)
    reg = make_pipeline(StandardScaler(), Ridge(alpha=1.0)).fit(train[FEATURES], train["delay"])
    mae_model = mean_absolute_error(test["delay"], reg.predict(test[FEATURES]).clip(min=0))
    mae_prior = mean_absolute_error(test["delay"], test["prior_avg_delay"])
    mae_mean = mean_absolute_error(test["delay"], np.full(len(test), train["delay"].mean()))

    def cls(y, p):
        return dict(accuracy=accuracy_score(y, p), precision=precision_score(y, p, zero_division=0),
                    recall=recall_score(y, p, zero_division=0), f1=f1_score(y, p, zero_division=0))
    metrics = dict(
        classifier=dict(logistic_regression={**cls(test["late"], pred), "roc_auc": roc_auc_score(test["late"], prob)},
                        baseline_majority_class=cls(test["late"], dummy.predict(test[FEATURES])),
                        baseline_prior_late_rate_rule=cls(test["late"], rule)),
        regressor=dict(ridge_mae_days=mae_model, baseline_customer_prior_avg_mae_days=mae_prior,
                       baseline_global_mean_mae_days=mae_mean),
        test_late_share=float(test["late"].mean()))
    clf_full = clf.fit(f[FEATURES], f["late"])  # refit on all history for scoring new invoices
    reg_full = reg.fit(f[FEATURES], f["delay"])
    return ModelBundle(True, "", source, metrics, clf_full, reg_full, f, len(train), len(test))


def get_model(clean: pd.DataFrame) -> ModelBundle:
    user_h = history_from_user_data(clean)
    if len(user_h) >= MIN_ROWS:
        return train_model(user_h, "Your uploaded paid receivables")
    return train_model(load_synthetic_history(), "Bundled SYNTHETIC payment history (demo data)")


def predict_receivables(bundle: ModelBundle, clean: pd.DataFrame) -> pd.DataFrame:
    cols = ["transaction_id", "customer", "amount", "history_invoices", "prob_late", "expected_delay_days", "note"]
    if not bundle.available:
        return pd.DataFrame(columns=cols)
    h = bundle.history
    rec = clean[(clean["transaction_type"] == "receivable") & (clean["status"] != "paid")]
    rows = []
    for _, r in rec.iterrows():
        ch = h[h["customer"] == r["entity_name"]]
        if ch.empty:
            rows.append(dict(transaction_id=r["transaction_id"], customer=r["entity_name"], amount=r["amount"],
                             history_invoices=0, prob_late=np.nan, expected_delay_days=np.nan,
                             note="No payment history for this customer"))
            continue
        x = pd.DataFrame([dict(prior_avg_delay=ch["delay"].mean(), prior_late_rate=ch["late"].mean(),
                               prior_count=len(ch), log_amount=np.log1p(r["amount"]),
                               terms_days=float(ch["terms_days"].median()))])[FEATURES]
        rows.append(dict(transaction_id=r["transaction_id"], customer=r["entity_name"], amount=r["amount"],
                         history_invoices=len(ch), prob_late=float(bundle.clf.predict_proba(x)[0, 1]),
                         expected_delay_days=float(max(0.0, bundle.reg.predict(x)[0])), note=""))
    return pd.DataFrame(rows, columns=cols)
