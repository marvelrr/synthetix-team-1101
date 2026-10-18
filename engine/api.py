"""The three-function Device 2 integration interface from shared contract v1.0."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime
import math
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from contracts import db
from contracts.models import JobStatus, RunConfig, RunMode, SyntheticUser, Usage
from engine.agent import origin
from engine.personas import generate_users


def _validated(config: RunConfig, require_pricing: bool = False) -> RunConfig:
    # Revalidate existing instances too; Pydantic instances can be mutated by a caller.
    config = RunConfig.model_validate(config.model_dump(warnings=False) if isinstance(config, RunConfig) else config)
    if config.mode == RunMode.INTERACTIVE:
        origin(config.product_url)
    ids = set()
    for task in config.tasks:
        kind, sep, value = task.success_check.partition(":")
        if not sep or not value or kind not in {"url_contains", "text_visible"}:
            raise ValueError(f"task {task.task_id}: use a nonempty url_contains: or text_visible: success check")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", task.task_id) or task.task_id in ids:
            raise ValueError("task IDs must be unique safe names, up to 80 characters")
        ids.add(task.task_id)
    if config.budget_hkd is not None and not math.isfinite(config.budget_hkd):
        raise ValueError("budget_hkd must be finite")
    if config.budget_hkd is not None and require_pricing:
        for key in ("LLM_PRICE_IN_HKD_PER_1M", "LLM_PRICE_OUT_HKD_PER_1M"):
            value = os.environ.get(key)
            if not value:
                raise ValueError(f"budget_hkd requires {key}; unknown pricing cannot enforce a budget")
            try:
                number = float(value)
            except ValueError:
                raise ValueError(f"{key} must be a finite nonnegative HKD price") from None
            if not math.isfinite(number) or number < 0:
                raise ValueError(f"{key} must be a finite nonnegative HKD price")
    return config


def start_run(config: RunConfig, is_saved_example: bool = False) -> str:
    load_dotenv()
    config = _validated(config, require_pricing=True)
    if os.environ.get("SYNTHETIX_LOCAL_INFERENCE_ALLOWED") == "0":
        from urllib.parse import urlsplit
        if urlsplit(os.environ.get("LLM_BASE_URL", "")).hostname in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Local model execution is disabled at the user's request because the laptop became hot. Review recorded results instead; obtain explicit user approval before enabling local inference.")
    now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    run_id = f"run-{now:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    users = generate_users(run_id, config.audience, config.user_count, config.seed)
    logs = Path("data/logs")
    logs.mkdir(parents=True, exist_ok=True)
    with closing(db.connect()) as conn:
        db.save_run(conn, run_id, config, is_saved_example)
        db.save_users(conn, users)
        try:
            metadata = {"contract_version": "1.0", "generator_version": "personas-1.0",
                        "agent_prompt_version": "agent-1.5", "evaluation_prompt_version": "evaluate-1.4",
                        "model": os.environ.get("LLM_MODEL"), "temperature": os.environ.get("LLM_TEMPERATURE", "0.7"),
                        "json_mode": os.environ.get("LLM_JSON_MODE", "1"), "mode": config.mode.value,
                        "seed": config.seed, "max_concurrency": config.max_concurrency,
                        "started_at_hkt": now.isoformat()}
            (logs / f"{run_id}.metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            with (logs / f"{run_id}.log").open("a", encoding="utf-8") as output:
                subprocess.Popen([sys.executable, "-m", "engine.worker", "--run-id", run_id],
                                 start_new_session=True, stdout=output, stderr=subprocess.STDOUT)
        except Exception as exc:
            for user in users:
                user.status = JobStatus.FAILED
                user.failure_reason = f"worker launch: {type(exc).__name__}"
            db.save_users(conn, users)
            db.set_run_status(conn, run_id, JobStatus.FAILED)
            raise RuntimeError(f"worker launch failed: {type(exc).__name__}") from None
    return run_id


def cancel_run(run_id: str) -> None:
    load_dotenv()
    with closing(db.connect()) as conn:
        db.request_cancel(conn, run_id)


def estimate_run(config: RunConfig) -> dict:
    load_dotenv()
    config = _validated(config)
    measured, source_runs, largest = [], 0, 0
    with closing(db.connect()) as conn:
        for run in db.list_runs(conn):
            if run["config"].mode != config.mode or run["config"].product_name.startswith("[FAKE]"):
                continue
            completed = {u.user_id for u in db.load_records(conn, "users", SyntheticUser, run["run_id"])
                         if u.status == JobStatus.COMPLETED}
            records = [u for u in db.load_records(conn, "usage", Usage, run["run_id"])
                       if u.user_id in completed and math.isfinite(u.seconds) and u.seconds >= 0]
            if not records:
                continue
            measured.extend(records)
            source_runs += 1
            if run["status"] == JobStatus.COMPLETED.value:
                largest = max(largest, len(records))
    if not measured:
        return {"available": False, "cost_hkd": None, "minutes": None, "basis": "no measured runs yet"}
    avg_seconds = sum(u.seconds for u in measured) / len(measured)
    cost = None if any(u.cost_hkd is None for u in measured) else config.user_count * sum(u.cost_hkd for u in measured) / len(measured)
    basis = (f"measured {len(measured)} completed users from {source_runs} earlier {config.mode.value} runs; "
             f"largest completed run: {largest} completed users")
    if config.user_count > largest:
        basis += "; untested at this size"
    return {"available": True, "cost_hkd": cost,
            "minutes": config.user_count * avg_seconds / config.max_concurrency / 60, "basis": basis}
