"""Synthetix shared SQLite store v1.0. Identical on both devices. Do not edit."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from pydantic import BaseModel

from contracts.models import (Evaluation, Finding, JobStatus, RunConfig,
                              SyntheticUser, TaskResult, Usage)

DB_PATH = Path("data/synthetix.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  config_json TEXT NOT NULL,
  status TEXT NOT NULL,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  is_saved_example INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, status TEXT NOT NULL,
  json TEXT NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS task_results (
  run_id TEXT NOT NULL, user_id TEXT NOT NULL, task_id TEXT NOT NULL,
  outcome TEXT NOT NULL, json TEXT NOT NULL, PRIMARY KEY (user_id, task_id)
);
CREATE TABLE IF NOT EXISTS evaluations (
  user_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
  user_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
  finding_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_run ON users(run_id, status);
"""

TABLES = {"users", "task_results", "evaluations", "usage", "findings"}


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def save_run(conn, run_id: str, config: RunConfig, is_saved_example: bool = False) -> None:
    now = time.time()
    conn.execute(
        "INSERT INTO runs (run_id, config_json, status, is_saved_example, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, config.model_dump_json(), JobStatus.QUEUED.value, int(is_saved_example), now, now),
    )
    conn.commit()


def get_run(conn, run_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    run = dict(row)
    run["config"] = RunConfig.model_validate_json(run.pop("config_json"))
    return run


def list_runs(conn) -> list[dict]:
    rows = conn.execute("SELECT run_id FROM runs ORDER BY created_at DESC").fetchall()
    return [get_run(conn, r["run_id"]) for r in rows]


def set_run_status(conn, run_id: str, status: JobStatus) -> None:
    conn.execute("UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
                 (status.value, time.time(), run_id))
    conn.commit()


def request_cancel(conn, run_id: str) -> None:
    conn.execute("UPDATE runs SET cancel_requested = 1, updated_at = ? WHERE run_id = ?",
                 (time.time(), run_id))
    conn.commit()


def set_saved_example(conn, run_id: str, value: bool = True) -> None:
    conn.execute("UPDATE runs SET is_saved_example = ?, updated_at = ? WHERE run_id = ?",
                 (int(value), time.time(), run_id))
    conn.commit()


def save_users(conn, users: list[SyntheticUser]) -> None:
    now = time.time()
    conn.executemany(
        "INSERT OR REPLACE INTO users (user_id, run_id, status, json, updated_at) VALUES (?, ?, ?, ?, ?)",
        [(u.user_id, u.run_id, u.status.value, u.model_dump_json(), now) for u in users],
    )
    conn.commit()


def save_user(conn, user: SyntheticUser) -> None:
    save_users(conn, [user])


def save_task_result(conn, r: TaskResult) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO task_results (run_id, user_id, task_id, outcome, json) VALUES (?, ?, ?, ?, ?)",
        (r.run_id, r.user_id, r.task_id, r.outcome.value, r.model_dump_json()),
    )
    conn.commit()


def save_evaluation(conn, e: Evaluation) -> None:
    conn.execute("INSERT OR REPLACE INTO evaluations (user_id, run_id, json) VALUES (?, ?, ?)",
                 (e.user_id, e.run_id, e.model_dump_json()))
    conn.commit()


def save_usage(conn, u: Usage) -> None:
    conn.execute("INSERT OR REPLACE INTO usage (user_id, run_id, json) VALUES (?, ?, ?)",
                 (u.user_id, u.run_id, u.model_dump_json()))
    conn.commit()


def replace_findings(conn, run_id: str, findings: list[Finding]) -> None:
    conn.execute("DELETE FROM findings WHERE run_id = ?", (run_id,))
    conn.executemany("INSERT INTO findings (finding_id, run_id, json) VALUES (?, ?, ?)",
                     [(f.finding_id, run_id, f.model_dump_json()) for f in findings])
    conn.commit()


def load_records(conn, table: str, model: type[BaseModel], run_id: str) -> list:
    if table not in TABLES:
        raise ValueError(f"unknown table {table}")
    rows = conn.execute(f"SELECT json FROM {table} WHERE run_id = ?", (run_id,)).fetchall()
    return [model.model_validate_json(r["json"]) for r in rows]


def status_counts(conn, run_id: str) -> dict[str, int]:
    counts = {s.value: 0 for s in JobStatus}
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM users WHERE run_id = ? GROUP BY status",
                        (run_id,)).fetchall()
    for r in rows:
        counts[r["status"]] = r["n"]
    return counts
