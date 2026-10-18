"""Remote-only, session-owned concept reviews for the hosted judging demo.

No browser, database, local inference, or submitted-text logging is used here.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hmac
import os
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4

from app.aggregate import aggregate
from contracts.models import (Evaluation, JobStatus, RatingDimension,
                              RunConfig, RunMode, SyntheticUser, TaskResult)
from engine.concept import run_concept_tasks
from engine.evaluate import evaluate_user
from engine.personas import generate_users
from engine.usage import empty_usage, merge_usage

MAX_TEXT_CHARS = 8_000
MAX_AUDIENCE_CHARS = 600
MAX_PROFILES = 5
SESSION_COOLDOWN_SECONDS = 90


def remote_settings_valid(settings: dict) -> bool:
    """A hosted demo cannot accidentally point at a local model or arbitrary host."""
    try:
        parsed = urlsplit(str(settings.get("LLM_BASE_URL", "")))
        port = parsed.port
    except ValueError:
        return False
    return (parsed.scheme == "https" and parsed.hostname == "api.deepseek.com"
            and port in (None, 443) and parsed.username is None
            and parsed.password is None and parsed.path.rstrip("/") in ("", "/v1")
            and not parsed.query and not parsed.fragment
            and bool(str(settings.get("LLM_API_KEY", "")).strip())
            and bool(str(settings.get("LLM_MODEL", "")).strip()))


def access_allowed(expected: str, supplied: str) -> bool:
    """An access code is required for paid public inference; never persist it."""
    return bool(expected) and hmac.compare_digest(expected.encode("utf-8"), supplied.encode("utf-8"))


def configure_remote(settings: dict) -> None:
    """Use the frozen wrapper with SDK network retries disabled, server-side only."""
    if not remote_settings_valid(settings):
        raise ValueError("Hosted live reviews require the configured DeepSeek HTTPS endpoint.")
    from openai import OpenAI
    from contracts import llm
    for key in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
                "LLM_PRICE_IN_HKD_PER_1M", "LLM_PRICE_OUT_HKD_PER_1M"):
        if key in settings:
            os.environ[key] = str(settings[key])
    os.environ["SYNTHETIX_LOCAL_INFERENCE_ALLOWED"] = "0"
    os.environ["LLM_JSON_MODE"] = "1"
    os.environ["LLM_TEMPERATURE"] = "0.2"
    os.environ["LLM_TIMEOUT_SECONDS"] = "60"
    llm._client = OpenAI(base_url=os.environ["LLM_BASE_URL"],
                         api_key=os.environ["LLM_API_KEY"], max_retries=0)


class LiveLimiter:
    """Process-wide bounded allowance; restarting the cloud process resets it.

    Each reserved profile allows at most two calls (one review and one repair).
    The lock is held throughout a run so paid runs never execute concurrently.
    This is an operational guard, not a financial/billing guarantee.
    """
    def __init__(self, daily_profiles: int = 5):
        self.daily_profiles = max(1, min(int(daily_profiles), 15))
        self._lock = threading.Lock()
        self._day = ""
        self._used = 0

    def acquire(self, count: int, now: datetime | None = None) -> bool:
        if type(count) is not int or not 1 <= count <= MAX_PROFILES:
            return False
        if not self._lock.acquire(blocking=False):
            return False
        day = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
        if day != self._day:
            self._day, self._used = day, 0
        if self._used + count > self.daily_profiles:
            self._lock.release()
            return False
        self._used += count
        return True

    def release(self) -> None:
        self._lock.release()


def config_for_review(recorded_config: RunConfig, material: str,
                      audience_description: str, count: int) -> RunConfig:
    if type(count) is not int or not 1 <= count <= MAX_PROFILES:
        raise ValueError("Choose one to five profiles.")
    if not isinstance(material, str) or not 20 <= len(material.strip()) <= MAX_TEXT_CHARS:
        raise ValueError("Supply 20 to 8,000 characters of non-sensitive product copy.")
    if not isinstance(audience_description, str) or not 3 <= len(audience_description.strip()) <= MAX_AUDIENCE_CHARS:
        raise ValueError("Describe the audience in 3 to 600 characters.")
    # Explicit priorities remain authored assumptions, not inferred demographics.
    audience = recorded_config.audience.model_copy(deep=True)
    audience.description = audience_description.strip()
    return RunConfig(
        product_name="Submitted product copy", product_version="judge-input",
        mode=RunMode.CONCEPT, concept_material=material.strip(),
        value_proposition="Evaluate only the supplied product/marketing material.",
        objective="Identify confusing wording, missing information, strengths, and reasons for hesitation for this intended audience: " + audience.description,
        audience=audience, user_count=count, seed=42, max_concurrency=1, tasks=[],
    )


def run_reviews(config: RunConfig, progress=None) -> dict:
    """Return actual outcomes; partial failures stay failed, no fabricated ratings."""
    if config.mode != RunMode.CONCEPT or not 1 <= config.user_count <= MAX_PROFILES:
        raise ValueError("Hosted demo supports one to five concept profiles only.")
    run_id = "judge-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8]
    users = generate_users(run_id, config.audience, config.user_count, config.seed)
    evaluations, task_results = [], []
    usage = empty_usage()
    started = time.monotonic()
    for index, user in enumerate(users):
        user.status, user.attempts = JobStatus.RUNNING, 1
        results = run_concept_tasks(user, config, run_id)
        try:
            evaluation, delta = evaluate_user(user, config, results, run_id)
            merge_usage(usage, delta)
            evaluations.append(evaluation)
            task_results.extend(results)
            user.status = JobStatus.COMPLETED
        except Exception as exc:
            delta = getattr(exc, "usage", None)
            if delta:
                merge_usage(usage, delta)
            else:
                usage["cost_hkd"] = None
            user.status = JobStatus.FAILED
            # Provider exceptions can include credentials or input: never expose them.
            user.failure_reason = "Review could not be validated or the AI provider was unavailable."
        if progress:
            progress(index + 1, len(users), user.status.value)
    summary = aggregate(config, users, task_results, evaluations)
    if sum(summary["coverage"]["status_counts"].values()) != config.user_count:
        raise RuntimeError("User accounting invariant failed.")
    return {"config": config.model_dump(mode="json"),
            "users": [user.model_dump(mode="json") for user in users],
            "task_results": [result.model_dump(mode="json") for result in task_results],
            "evaluations": [evaluation.model_dump(mode="json") for evaluation in evaluations],
            "usage": usage,
            "provenance": {"run_id": run_id, "mode": "concept", "kind": "live-session",
                           "model": os.environ.get("LLM_MODEL", "configured remote model"),
                           "recorded_at": datetime.now(timezone.utc).isoformat(),
                           "wall_seconds": round(time.monotonic() - started, 2),
                           "browser_visits": 0}}


def parse_bundle(payload: dict) -> tuple[RunConfig, list, list, list]:
    config = RunConfig.model_validate(payload["config"])
    users = [SyntheticUser.model_validate(item) for item in payload["users"]]
    results = [TaskResult.model_validate(item) for item in payload.get("task_results", [])]
    evaluations = [Evaluation.model_validate(item) for item in payload.get("evaluations", [])]
    if len({user.user_id for user in users}) != config.user_count:
        raise ValueError("Recorded user accounting is invalid.")
    identities = {(user.run_id, user.user_id) for user in users}
    if len({run_id for run_id, _ in identities}) != 1:
        raise ValueError("A report must contain one run only.")
    if any((item.run_id, item.user_id) not in identities for item in [*results, *evaluations]):
        raise ValueError("A report contains unrelated records.")
    by_id = {evaluation.user_id: evaluation for evaluation in evaluations}
    result_ids = {(result.user_id, result.task_id) for result in results}
    for user in users:
        if user.status != JobStatus.COMPLETED:
            continue
        evaluation = by_id.get(user.user_id)
        if (evaluation is None or evaluation.mode != config.mode or
                any((user.user_id, task.task_id) not in result_ids for task in config.tasks)):
            raise ValueError("Completed profiles require a valid evaluation and every task result.")
    return config, users, results, evaluations


TOPIC_TERMS = {
    "Price and value": ("price", "pricing", "cost", "afford", "value for money"),
    "Trial and cancellation": ("trial", "cancel", "subscription terms"),
    "Delivery and coverage": ("deliver", "district", "coverage", "service area"),
    "Bottle return and collection": ("bottle", "return", "collection"),
    "Trust and evidence": ("trust", "evidence", "claim", "privacy", "proof"),
}


def concern_topics(evaluations: list[Evaluation]) -> list[dict]:
    """Transparent keyword index, with exact supporting text and unique-user counts.

    A problem may match several topics. These are navigation aids, not model themes.
    """
    grouped = defaultdict(list)
    unique = {evaluation.user_id: evaluation for evaluation in evaluations}
    for evaluation in unique.values():
        for problem in evaluation.problems:
            matched = False
            for topic, terms in TOPIC_TERMS.items():
                if any(term in problem.text.casefold() for term in terms):
                    grouped[topic].append({"user_id": evaluation.user_id,
                                           "text": problem.text, "severity": problem.severity})
                    matched = True
            if not matched:
                grouped["Other observations"].append({"user_id": evaluation.user_id,
                                                      "text": problem.text, "severity": problem.severity})
    return sorted([{"topic": topic, "supporting_user_ids": sorted({item["user_id"] for item in evidence}),
                    "denominator": len(unique), "evidence": evidence}
                   for topic, evidence in grouped.items()],
                  key=lambda item: (-len(item["supporting_user_ids"]), item["topic"]))


def rating_comparisons(evaluations: list[Evaluation]) -> list[dict]:
    rows = []
    unique = {item.user_id: item for item in evaluations}
    for dimension in RatingDimension:
        scores = [evaluation.ratings[dimension].score for evaluation in unique.values()
                  if evaluation.ratings[dimension].score is not None]
        rows.append({"Dimension": dimension.value.replace("_", " ").title(),
                     "Eligible profiles": len(scores),
                     "Not assessable": len(unique) - len(scores),
                     "Mean / 5": round(sum(scores) / len(scores), 2) if scores else None,
                     "Lowest": min(scores) if scores else None,
                     "Highest": max(scores) if scores else None})
    return rows
