"""Explicit development fixtures. Never enable this module for a real demo.

No browser visits or model evaluations occur here. Product names and every
fixture explanation are marked FAKE so the records cannot imply observation.
For cancellation coverage use product_version="fake-cancel-demo"; that scenario
requests cancellation halfway through. Ordinary runs can be cancelled via API.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime
from fractions import Fraction
import random
import secrets
import threading
import time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from contracts import db
from contracts.models import (Evaluation, JobStatus, Problem, Rating,
                              RatingDimension, RunConfig, RunMode,
                              SyntheticUser, TaskOutcome, TaskResult, Usage)

FIXTURE = "FAKE development fixture; no browser visit or model evaluation occurred"


def _users(run_id: str, config: RunConfig) -> list[SyntheticUser]:
    weights = [Fraction(str(segment.weight)) for segment in config.audience.segments]
    quotas = [config.user_count * weight / sum(weights) for weight in weights]
    counts = [int(quota) for quota in quotas]
    for index in sorted(range(len(quotas)), key=lambda i: (-(quotas[i] - counts[i]), i))[:config.user_count - sum(counts)]:
        counts[index] += 1
    rng = random.Random(config.seed)
    users = []
    for segment, count in zip(config.audience.segments, counts):
        for _ in range(count):
            profile = {key: rng.choice(values) if values else "unspecified"
                       for key, values in segment.attributes.items()}
            profile["language"] = rng.choice(segment.languages or ["en"])
            users.append(SyntheticUser(
                user_id=f"{run_id}-u{len(users) + 1:05d}", run_id=run_id,
                segment=segment.name, profile=profile,
                sourced_facts=list(segment.sourced_facts),
                authored_assumptions=[*segment.authored_assumptions, FIXTURE],
                generator_version="fake-development-1.0"))
    return users


def _results(user: SyntheticUser, config: RunConfig, index: int) -> tuple[list[TaskResult], Evaluation]:
    tasks = []
    problems = []
    for task_index, task in enumerate(config.tasks):
        if config.mode == RunMode.CONCEPT:
            outcome = TaskOutcome.NOT_ATTEMPTED
        elif (index + task_index) % 5 == 2:
            outcome = TaskOutcome.BLOCKED
        elif (index + task_index) % 5 == 3:
            outcome = TaskOutcome.FAILED
        else:
            outcome = TaskOutcome.COMPLETED
        tasks.append(TaskResult(run_id=user.run_id, user_id=user.user_id,
                                task_id=task.task_id, outcome=outcome,
                                reason=f"{FIXTURE}: {outcome.value}"))
        if outcome in {TaskOutcome.BLOCKED, TaskOutcome.FAILED}:
            problems.append(Problem(text=f"[FAKE] {'Core task could not continue' if outcome == TaskOutcome.BLOCKED else 'Task navigation was unclear'}",
                                    task_id=task.task_id,
                                    severity="blocker" if outcome == TaskOutcome.BLOCKED else "major"))
    if index % 2 == 0:
        problems.append(Problem(text="[FAKE] Prefer clearer labels", severity="minor"))
    ratings = {}
    for dimension_index, dimension in enumerate(RatingDimension):
        if dimension == RatingDimension.EASE_OF_USE and (config.mode == RunMode.CONCEPT or not tasks):
            rating = Rating(not_assessable_reason="no relevant product task attempted")
        elif (index + dimension_index) % 6 == 0:
            rating = Rating(not_assessable_reason="[FAKE] Fixture demonstrates an unassessable rating")
        else:
            rating = Rating(score=1 + (index + dimension_index) % 5)
        ratings[dimension] = rating
    evaluation = Evaluation(
        run_id=user.run_id, user_id=user.user_id, mode=config.mode,
        ratings=ratings, rating_reasons=FIXTURE,
        strengths=["[FAKE] Fixture demonstrates a reported strength"],
        problems=problems, suggestions=["[FAKE] Clarify the navigation labels"],
        pricing_feedback=None)
    return tasks, evaluation


def _advance(run_id: str, config: RunConfig, users: list[SyntheticUser]) -> None:
    # Each worker thread owns its own SQLite connection.
    with closing(db.connect()) as conn:
        db.set_run_status(conn, run_id, JobStatus.RUNNING)
        started = time.monotonic()
        active = []
        next_user = 0
        cancelled = False
        try:
            while next_user < len(users) or active:
                elapsed = time.monotonic() - started
                if config.product_version == "fake-cancel-demo" and elapsed >= 10:
                    db.request_cancel(conn, run_id)
                run = db.get_run(conn, run_id)
                cancelled = cancelled or bool(run["cancel_requested"])
                if cancelled:
                    for user in users[next_user:]:
                        user.status = JobStatus.CANCELLED
                        user.failure_reason = "run cancelled"
                        db.save_user(conn, user)
                    next_user = len(users)
                # Spread starts over about 20 seconds, while respecting concurrency.
                due = min(len(users), 1 + int(elapsed / 20 * len(users)))
                while not cancelled and next_user < due and len(active) < config.max_concurrency:
                    user = users[next_user]
                    user.status = JobStatus.RUNNING
                    user.attempts = 1
                    db.save_user(conn, user)
                    active.append((next_user, user, time.monotonic()))
                    next_user += 1
                for index, user, entered in list(active):
                    if time.monotonic() - entered < 20 / len(users):
                        continue
                    if (index + 1) % 7 == 0:
                        user.status = JobStatus.FAILED
                        user.failure_reason = f"evaluation: {FIXTURE}; injected development failure"
                    else:
                        tasks, evaluation = _results(user, config, index)
                        for result in tasks:
                            db.save_task_result(conn, result)
                        db.save_evaluation(conn, evaluation)
                        user.status = JobStatus.COMPLETED
                    db.save_usage(conn, Usage(run_id=run_id, user_id=user.user_id,
                                             seconds=time.monotonic() - entered, cost_hkd=None))
                    db.save_user(conn, user)
                    active.remove((index, user, entered))
                assert sum(db.status_counts(conn, run_id).values()) == config.user_count
                time.sleep(0.05)
            db.set_run_status(conn, run_id, JobStatus.CANCELLED if cancelled else JobStatus.COMPLETED)
        except Exception as exc:
            for user in users:
                if user.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                    user.status = JobStatus.FAILED
                    user.failure_reason = f"fake development worker: {type(exc).__name__}"
                    db.save_user(conn, user)
            db.set_run_status(conn, run_id, JobStatus.FAILED)


def start_run(config: RunConfig, is_saved_example: bool = False) -> str:
    load_dotenv()
    if is_saved_example:
        raise ValueError("Fake development runs cannot become saved examples")
    config = RunConfig.model_validate(config.model_dump())
    config = config.model_copy(update={"product_name": "[FAKE] " + config.product_name.removeprefix("[FAKE] ")})
    run_id = f"fake-run-{datetime.now(ZoneInfo('Asia/Hong_Kong')):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    users = _users(run_id, config)
    with closing(db.connect()) as conn:
        db.save_run(conn, run_id, config)
        db.save_users(conn, users)
    threading.Thread(target=_advance, args=(run_id, config, users), daemon=True,
                     name=f"synthetix-fake-{run_id}").start()
    return run_id


def cancel_run(run_id: str) -> None:
    load_dotenv()
    with closing(db.connect()) as conn:
        db.request_cancel(conn, run_id)


def estimate_run(config: RunConfig) -> dict:
    load_dotenv()
    RunConfig.model_validate(config.model_dump())
    return {"available": False, "cost_hkd": None, "minutes": None,
            "basis": "fake development engine has no measured runs"}
