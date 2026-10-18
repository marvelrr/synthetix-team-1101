"""Background job runner. Invoke from the repo root: python -m engine.worker --run-id ID."""
from __future__ import annotations

import argparse
import asyncio
from collections import deque
from contextlib import closing, suppress
import logging
import os
import threading
import time

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from contracts import db, llm
from contracts.models import JobStatus, RunMode, SyntheticUser, Usage
from engine import agent, concept, evaluate
from engine.usage import usage_sink

LOG = logging.getLogger("synthetix.engine")


def get_user(conn, user_id: str) -> SyntheticUser:
    row = conn.execute("SELECT json FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        raise ValueError("user missing from run")
    return SyntheticUser.model_validate_json(row["json"])


def assert_accounting(conn, run_id: str, expected: int) -> dict:
    counts = db.status_counts(conn, run_id)
    if sum(counts.values()) != expected:
        LOG.critical("ACCOUNTING INVARIANT BROKEN run=%s expected=%s counts=%s", run_id, expected, counts)
        raise AssertionError("requested users must equal the sum of all status counts")
    return counts


class Ledger:
    """One attempt's accounting; every callback opens its own thread-local connection."""
    def __init__(self, run_id: str, user_id: str):
        self.lock = threading.RLock()
        with closing(db.connect()) as conn:
            row = conn.execute("SELECT json FROM usage WHERE user_id = ?", (user_id,)).fetchone()
        self.total = Usage.model_validate_json(row["json"]) if row else Usage(
            run_id=run_id, user_id=user_id, cost_hkd=llm.cost_hkd(0, 0))
        self.last = time.monotonic()
        self.pending_base_cost = None
        self.has_pending_call = False

    def snapshot(self) -> dict:
        return self.total.model_dump()

    def capture(self, delta: dict | None = None) -> None:
        with self.lock:
            now = time.monotonic()
            self.total.seconds += now - self.last
            self.last = now
            if delta is not None:
                if delta.get("phase") == "start":
                    self.pending_base_cost = self.total.cost_hkd
                    self.has_pending_call = True
                    self.total.llm_calls += 1
                    self.total.cost_hkd = None
                for name in ("llm_calls", "input_tokens", "output_tokens"):
                    setattr(self.total, name, getattr(self.total, name) + delta.get(name, 0))
                if delta.get("phase") != "start":
                    a = self.pending_base_cost if delta.get("phase") == "finish" and self.has_pending_call else self.total.cost_hkd
                    b = delta.get("cost_hkd")
                    self.total.cost_hkd = None if a is None or b is None else a + b
                    self.has_pending_call = False
            with closing(db.connect()) as conn:
                db.save_usage(conn, self.total)

    def reconcile(self, returned: dict, before: dict) -> None:
        # Interface doubles and alternate task adapters may return usage without the sink.
        missing = {key: max(0, returned.get(key, 0) - (getattr(self.total, key) - before[key]))
                   for key in ("llm_calls", "input_tokens", "output_tokens")}
        if any(missing.values()):
            recorded_cost = None if self.total.cost_hkd is None or before["cost_hkd"] is None else self.total.cost_hkd - before["cost_hkd"]
            cost = returned.get("cost_hkd")
            missing["cost_hkd"] = None if cost is None or recorded_cost is None else max(0, cost - recorded_cost)
            self.capture(missing)


def recover_running(conn, run_id: str) -> None:
    for user in db.load_records(conn, "users", SyntheticUser, run_id):
        if user.status == JobStatus.RUNNING:
            user.status = JobStatus.QUEUED
            user.failure_reason = None
            db.save_user(conn, user)


def _budget_state(conn, run) -> str | None:
    if run["cancel_requested"]:
        return "run cancelled"
    if run["config"].budget_hkd is None:
        return None
    records = db.load_records(conn, "usage", Usage, run["run_id"])
    if sum(record.cost_hkd for record in records if record.cost_hkd is not None) >= run["config"].budget_hkd:
        return "budget reached"
    unknown = [record for record in records if record.cost_hkd is None and record.llm_calls]
    if unknown:
        running = {row["user_id"] for row in conn.execute("SELECT user_id FROM users WHERE run_id = ? AND status = ?", (run["run_id"], JobStatus.RUNNING.value))}
        if any(record.user_id not in running for record in unknown):
            return "budget accounting failed: measured cost is unknown"
        return "budget accounting pending"
    return None


async def run_worker(run_id: str) -> dict:
    load_dotenv()
    conn = db.connect()
    browser = playwright = None
    browser_error = None
    try:
        run = db.get_run(conn, run_id)
        if run is None:
            raise ValueError("unknown run_id")
        config = run["config"]
        recover_running(conn, run_id)
        assert_accounting(conn, run_id, config.user_count)
        db.set_run_status(conn, run_id, JobStatus.RUNNING)
        initial = db.load_records(conn, "users", SyntheticUser, run_id)
        queue = deque(user.user_id for user in initial if user.status == JobStatus.QUEUED)
        semaphore = asyncio.Semaphore(config.max_concurrency)
        cancelled = budget_hit = False

        def stop_queued(reason):
            for user in db.load_records(conn, "users", SyntheticUser, run_id):
                if user.status == JobStatus.QUEUED:
                    user.status = JobStatus.FAILED if reason.startswith("budget accounting") else JobStatus.CANCELLED
                    user.failure_reason = reason
                    db.save_user(conn, user)
            queue.clear()
            assert_accounting(conn, run_id, config.user_count)

        initial_stop = _budget_state(conn, db.get_run(conn, run_id))
        if initial_stop:
            cancelled = initial_stop == "run cancelled"
            budget_hit = initial_stop == "budget reached"
            stop_queued(initial_stop)
        elif queue and config.mode == RunMode.INTERACTIVE:
            try:
                playwright = await async_playwright().start()
                cdp = os.environ.get("SYNTHETIX_CDP_URL")
                browser = (await playwright.chromium.connect_over_cdp(cdp)) if cdp else await playwright.chromium.launch(headless=True)
            except Exception as exc:
                # Every user still goes through the ordinary two-attempt failure path.
                browser_error = type(exc).__name__
                LOG.error("Browser startup failed run=%s error_type=%s", run_id, browser_error)

        async def process_user(user_id):
            async with semaphore:
                user = get_user(conn, user_id)
                if user.attempts >= 2:
                    user.status = JobStatus.FAILED
                    user.failure_reason = "restart recovery: attempt limit reached"
                    db.save_user(conn, user)
                    assert_accounting(conn, run_id, config.user_count)
                    return user
                user.status = JobStatus.RUNNING
                user.attempts += 1
                user.failure_reason = None
                db.save_user(conn, user)
                ledger = Ledger(run_id, user_id)
                token = usage_sink.set(ledger.capture)
                context = None
                stage = "browser context"
                before = ledger.snapshot()
                try:
                    if config.mode == RunMode.INTERACTIVE:
                        if browser is None:
                            stage = "browser startup"
                            raise RuntimeError(browser_error or "browser unavailable")
                        context = await browser.new_context(service_workers="block", accept_downloads=False)
                        results = []
                        for task in config.tasks:
                            stage = f"task {task.task_id}"
                            before = ledger.snapshot()
                            result, measured = await agent.run_task(context, user, task, config, run_id)
                            ledger.reconcile(measured, before)
                            results.append(result)
                            stage = f"persist task {task.task_id}"
                            db.save_task_result(conn, result)
                    else:
                        stage = "concept tasks"
                        results = concept.run_concept_tasks(user, config, run_id)
                        for result in results:
                            db.save_task_result(conn, result)
                    stage = "evaluation"
                    before = ledger.snapshot()
                    evaluation, measured = await asyncio.to_thread(evaluate.evaluate_user, user, config, results, run_id)
                    ledger.reconcile(measured, before)
                    stage = "persist task results"
                    for result in results:
                        db.save_task_result(conn, result)
                    stage = "persist evaluation"
                    db.save_evaluation(conn, evaluation)
                    stage = "persist usage"
                    ledger.capture()
                    # Completion is published only after every required record exists.
                    user.status = JobStatus.COMPLETED
                    user.failure_reason = None
                    db.save_user(conn, user)
                except Exception as exc:
                    if isinstance(getattr(exc, "usage", None), dict):
                        ledger.reconcile(exc.usage, before)
                    detail = str(exc) if isinstance(exc, evaluate.EvaluationError) else type(exc).__name__
                    reason = f"{stage}: {detail}"
                    if stage == "browser startup":
                        reason += f" ({browser_error or 'browser unavailable'})"
                    user.failure_reason = reason
                    user.status = JobStatus.QUEUED if user.attempts < 2 else JobStatus.FAILED
                    db.save_user(conn, user)
                    LOG.warning("User attempt failed run=%s user=%s attempt=%s stage=%s error_type=%s",
                                run_id, user_id, user.attempts, stage, type(exc).__name__)
                finally:
                    usage_sink.reset(token)
                    if context is not None:
                        with suppress(Exception):
                            await context.close()
                    ledger.capture()
                    counts = assert_accounting(conn, run_id, config.user_count)
                    LOG.info("User settled run=%s user=%s counts=%s", run_id, user_id, counts)
                return user

        pending = set()
        while queue or pending:
            while queue and len(pending) < config.max_concurrency:
                # This read happens before each individual scheduling decision.
                current = db.get_run(conn, run_id)
                reason = _budget_state(conn, current)
                if reason:
                    if reason == "budget accounting pending":
                        break
                    cancelled = cancelled or reason == "run cancelled"
                    budget_hit = budget_hit or reason == "budget reached"
                    stop_queued(reason)
                    break
                pending.add(asyncio.create_task(process_user(queue.popleft())))
                # Let the new user enter RUNNING before observing cancellation/budget again.
                await asyncio.sleep(0)
            if pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for completed in done:
                    user = completed.result()
                    if user.status == JobStatus.QUEUED:
                        queue.append(user.user_id)
        final = db.get_run(conn, run_id)
        final_reason = _budget_state(conn, final)
        cancelled = cancelled or bool(final["cancel_requested"])
        budget_hit = budget_hit or final_reason == "budget reached"
        counts = assert_accounting(conn, run_id, config.user_count)
        if counts["queued"] or counts["running"]:
            raise AssertionError("worker ended with unsettled users")
        db.set_run_status(conn, run_id, JobStatus.CANCELLED if cancelled or budget_hit else JobStatus.COMPLETED)
        return counts
    finally:
        if browser is not None:
            with suppress(Exception):
                await browser.close()
        if playwright is not None:
            with suppress(Exception):
                await playwright.stop()
        conn.close()


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for name in ("httpx", "httpx2", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)
    asyncio.run(run_worker(args.run_id))


if __name__ == "__main__":
    main()
