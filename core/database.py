"""SQLite persistence: datasets, settings, simulation runs, scenario results, report metadata.
All inserts are idempotent (unique hashes) so repeated imports/saves never create duplicates."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import sqlite3

import pandas as pd

DEFAULT_DB = pathlib.Path(__file__).resolve().parents[1] / "data" / "rupeeripple.db"


def db_path() -> str:
    return os.environ.get("RUPEERIPPLE_DB", str(DEFAULT_DB))


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str | None = None) -> None:
    with connect(path) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS datasets(
            id INTEGER PRIMARY KEY, name TEXT, sha TEXT UNIQUE, n_rows INTEGER, csv_text TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS simulations(
            id INTEGER PRIMARY KEY, dataset_sha TEXT, config_hash TEXT UNIQUE, config_json TEXT,
            summary_json TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS scenarios(
            id INTEGER PRIMARY KEY, config_hash TEXT, scenario TEXT, metrics_json TEXT, created_at TEXT,
            UNIQUE(config_hash, scenario));
        CREATE TABLE IF NOT EXISTS reports(
            id INTEGER PRIMARY KEY, dataset_sha TEXT, title TEXT, fmt TEXT, created_at TEXT);
        """)


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _js(obj) -> str:
    return json.dumps(obj, default=str, sort_keys=True)


def save_dataset(raw: pd.DataFrame, name: str, path: str | None = None) -> str:
    csv_text = raw.to_csv(index=False)
    sha = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()[:16]
    with connect(path) as c:
        c.execute("INSERT OR IGNORE INTO datasets(name, sha, n_rows, csv_text, created_at) VALUES(?,?,?,?,?)",
                  (name, sha, len(raw), csv_text, _now()))
    return sha


def load_dataset(sha: str, path: str | None = None):
    with connect(path) as c:
        r = c.execute("SELECT csv_text FROM datasets WHERE sha=?", (sha,)).fetchone()
    if not r:
        return None
    import io
    return pd.read_csv(io.StringIO(r["csv_text"]), dtype=str, keep_default_na=False)


def list_datasets(path: str | None = None) -> pd.DataFrame:
    with connect(path) as c:
        rows = c.execute("SELECT name, sha, n_rows, created_at FROM datasets ORDER BY id DESC").fetchall()
    return pd.DataFrame([dict(r) for r in rows], columns=["name", "sha", "n_rows", "created_at"])


def set_setting(key: str, value, path: str | None = None) -> None:
    with connect(path) as c:
        c.execute("INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, _js(value)))


def get_setting(key: str, default=None, path: str | None = None):
    with connect(path) as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def config_hash(dataset_sha: str, config: dict) -> str:
    return hashlib.sha256((dataset_sha + _js(config)).encode("utf-8")).hexdigest()[:16]


def save_simulation(dataset_sha: str, config: dict, summary: dict, path: str | None = None) -> str:
    h = config_hash(dataset_sha, config)
    with connect(path) as c:
        c.execute("INSERT OR IGNORE INTO simulations(dataset_sha, config_hash, config_json, summary_json, created_at) "
                  "VALUES(?,?,?,?,?)", (dataset_sha, h, _js(config), _js(summary), _now()))
    return h


def save_scenarios(chash: str, comparison: pd.DataFrame, path: str | None = None) -> int:
    n = 0
    with connect(path) as c:
        for _, r in comparison.iterrows():
            cur = c.execute("INSERT OR REPLACE INTO scenarios(config_hash, scenario, metrics_json, created_at) VALUES(?,?,?,?)",
                            (chash, r["scenario"], _js({k: (None if pd.isna(v) else v) for k, v in r.items()
                                                      if k not in ("assumptions", "tradeoffs")}), _now()))
            n += cur.rowcount
    return n


def list_simulations(path: str | None = None) -> pd.DataFrame:
    with connect(path) as c:
        rows = c.execute("SELECT config_hash, dataset_sha, config_json, summary_json, created_at FROM simulations ORDER BY id DESC").fetchall()
    out = []
    for r in rows:
        s, cfg = json.loads(r["summary_json"]), json.loads(r["config_json"])
        out.append(dict(saved_at=r["created_at"], dataset=r["dataset_sha"], delayed_txn=cfg.get("txn_id"),
                        delay_days=cfg.get("delay_days"), min_balance=s.get("min_balance"),
                        breach_days=s.get("breach_days"), at_risk=s.get("n_at_risk")))
    return pd.DataFrame(out, columns=["saved_at", "dataset", "delayed_txn", "delay_days", "min_balance", "breach_days", "at_risk"])


def save_report_meta(dataset_sha: str, title: str, fmt: str, path: str | None = None) -> None:
    with connect(path) as c:
        c.execute("INSERT INTO reports(dataset_sha, title, fmt, created_at) VALUES(?,?,?,?)", (dataset_sha, title, fmt, _now()))


def list_reports(path: str | None = None) -> pd.DataFrame:
    with connect(path) as c:
        rows = c.execute("SELECT title, fmt, dataset_sha, created_at FROM reports ORDER BY id DESC").fetchall()
    return pd.DataFrame([dict(r) for r in rows], columns=["title", "fmt", "dataset_sha", "created_at"])
