"""CSV / table validation. Nothing is silently dropped: every rejected or adjusted
record produces a row in ``ValidationResult.issues`` explaining why."""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import pandas as pd

REQUIRED_COLUMNS = [
    "transaction_id", "entity_name", "entity_type", "transaction_type", "amount",
    "due_date", "expected_date", "status", "related_entity", "flexibility",
]
ENTITY_TYPES = {"customer", "supplier", "employee", "landlord", "utility", "government", "other"}
TRANSACTION_TYPES = {"receivable", "payable", "payroll", "rent", "utilities", "other"}
STATUSES = {"pending", "overdue", "paid"}
FLEXIBILITY = {"fixed", "flexible"}
ENUMS = {
    "entity_type": ENTITY_TYPES,
    "transaction_type": TRANSACTION_TYPES,
    "status": STATUSES,
    "flexibility": FLEXIBILITY,
}
ISSUE_COLUMNS = ["row", "transaction_id", "column", "severity", "message"]


@dataclass
class ValidationResult:
    clean: pd.DataFrame
    issues: pd.DataFrame
    fatal: list = field(default_factory=list)
    n_rows: int = 0

    @property
    def n_valid(self) -> int:
        return len(self.clean)

    @property
    def n_errors(self) -> int:
        return int((self.issues["severity"] == "error").sum()) if len(self.issues) else 0

    @property
    def n_warnings(self) -> int:
        return int((self.issues["severity"] == "warning").sum()) if len(self.issues) else 0

    @property
    def ok(self) -> bool:
        return not self.fatal and self.n_valid > 0


def read_csv_bytes(data: bytes):
    """Return (raw_df_of_strings, error_message_or_None)."""
    if not data or not data.strip():
        return None, "The file is empty."
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    try:
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    except Exception as exc:
        return None, f"The file could not be parsed as CSV: {exc}"
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df, None


def _issue(rows, row, tid, col, sev, msg):
    rows.append({"row": row, "transaction_id": tid, "column": col, "severity": sev, "message": msg})


def _parse_amount(value):
    s = str(value).strip().replace("₹", "").replace("Rs.", "").replace("Rs", "").replace(",", "")
    if s == "":
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def validate_dataframe(raw: pd.DataFrame) -> ValidationResult:
    empty = pd.DataFrame(columns=REQUIRED_COLUMNS)
    no_issues = pd.DataFrame(columns=ISSUE_COLUMNS)
    if raw is None or len(raw.columns) == 0:
        return ValidationResult(empty, no_issues, ["No data loaded."], 0)
    df = raw.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        return ValidationResult(
            empty, no_issues,
            [f"Missing required column(s): {', '.join(missing)}. "
             "Download the CSV template for the expected schema."], len(df))
    if len(df) == 0:
        return ValidationResult(empty, no_issues, ["The dataset has no rows."], 0)

    df = df[REQUIRED_COLUMNS].reset_index(drop=True)
    for c in REQUIRED_COLUMNS:
        df[c] = df[c].fillna("").astype(str).str.strip()
    for c in ENUMS:
        df[c] = df[c].str.lower()

    issues, bad = [], set()
    ids = df["transaction_id"]
    dup_mask = ids.ne("") & ids.duplicated(keep=False)
    amounts = df["amount"].map(_parse_amount)
    due = pd.to_datetime(df["due_date"].replace("", pd.NA), errors="coerce", format="mixed")
    exp = pd.to_datetime(df["expected_date"].replace("", pd.NA), errors="coerce", format="mixed")

    for i in df.index:
        r = df.loc[i]
        rn, tid = i + 2, r["transaction_id"]  # +2: header row, 1-based
        if tid == "":
            _issue(issues, rn, tid, "transaction_id", "error", "transaction_id is missing.")
            bad.add(i)
        if dup_mask.loc[i]:
            others = [str(j + 2) for j in df.index[ids == tid] if j != i]
            _issue(issues, rn, tid, "transaction_id", "error",
                   f"Duplicate transaction_id '{tid}' (also on row {', '.join(others)}). "
                   "Rows are excluded until IDs are unique.")
            bad.add(i)
        if r["entity_name"] == "":
            _issue(issues, rn, tid, "entity_name", "error", "entity_name is missing.")
            bad.add(i)
        for c, allowed in ENUMS.items():
            if r[c] == "":
                _issue(issues, rn, tid, c, "error", f"{c} is missing.")
                bad.add(i)
            elif r[c] not in allowed:
                _issue(issues, rn, tid, c, "error",
                       f"{c} '{r[c]}' is not valid. Allowed: {', '.join(sorted(allowed))}.")
                bad.add(i)
        a = amounts.at[i]
        if pd.isna(a):
            _issue(issues, rn, tid, "amount", "error", "amount is missing or not a number.")
            bad.add(i)
        elif a <= 0:
            _issue(issues, rn, tid, "amount", "error",
                   f"amount {a:g} must be greater than zero (zero and negative amounts are not accepted).")
            bad.add(i)
        if pd.isna(due.at[i]):
            msg = ("due_date is missing." if r["due_date"] == ""
                   else f"due_date '{r['due_date']}' is not a valid date (use YYYY-MM-DD).")
            _issue(issues, rn, tid, "due_date", "error", msg)
            bad.add(i)
        if r["expected_date"] != "" and pd.isna(exp.at[i]):
            _issue(issues, rn, tid, "expected_date", "error",
                   f"expected_date '{r['expected_date']}' is not a valid date (use YYYY-MM-DD).")
            bad.add(i)
        elif r["expected_date"] == "" and not pd.isna(due.at[i]):
            _issue(issues, rn, tid, "expected_date", "warning",
                   "expected_date is blank; due_date is used instead.")
        if r["transaction_type"] == "receivable" and r["entity_type"] not in ("customer", ""):
            _issue(issues, rn, tid, "entity_type", "warning", "A receivable is normally owed by a customer.")

    good = [i for i in df.index if i not in bad]
    clean = df.loc[good].copy()
    clean["amount"] = amounts.loc[good].astype(float).round(2)
    clean["due_date"] = due.loc[good].dt.date
    exp_filled = exp.loc[good].where(exp.loc[good].notna(), due.loc[good])
    clean["expected_date"] = exp_filled.dt.date
    clean = clean.reset_index(drop=True)
    return ValidationResult(clean, pd.DataFrame(issues, columns=ISSUE_COLUMNS), [], len(df))
