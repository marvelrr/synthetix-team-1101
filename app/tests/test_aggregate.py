from __future__ import annotations

import json

import pytest

from app.aggregate import aggregate, build_findings
from contracts.models import JobStatus, Problem, Rating, RatingDimension, TaskOutcome


def test_means_shares_and_na_exclusion(records):
    _, config, users, results, evaluations = records
    report = aggregate(config, users, results, evaluations)
    assert report["ratings"]["appeal"] == {"counts": {1: 0, 2: 0, 3: 1, 4: 0, 5: 1},
                                            "eligible": 2, "not_assessable": 1, "missing": 0, "mean": 4}
    assert report["appeal_signal"] == {"numerator": 1, "denominator": 2, "share": .5}
    assert report["adoption_interest_signal"] == {"numerator": 3, "denominator": 3, "share": 1}
    assert report["coverage"]["completed"] == 3
    assert report["coverage"]["status_counts"]["failed"] == 1
    assert report["coverage"]["status_counts"]["cancelled"] == 1
    assert report["coverage"]["accounting_valid"]
    assert sum(report["coverage"]["status_counts"].values()) == config.user_count


def test_missing_evaluation_excluded_not_zero(records):
    _, config, users, results, evaluations = records
    report = aggregate(config, users, results, evaluations[:1])
    data = report["ratings"]["appeal"]
    assert data["mean"] == 5 and data["eligible"] == 1 and data["missing"] == 2
    assert report["appeal_signal"]["denominator"] == 1


def test_task_outcomes_among_completed_only(records):
    _, config, users, results, evaluations = records
    extra = results[0].model_copy(update={"user_id": users[3].user_id})
    report = aggregate(config, users, results + [extra], evaluations)
    assert report["tasks"]["T1"]["completion"] == {"numerator": 1, "denominator": 3, "share": 1 / 3}
    assert report["tasks"]["T1"]["outcome_counts"]["not_attempted"] == 1
    assert report["tasks"]["T2"]["completion"]["share"] == 2 / 3


def test_duplicate_users_results_evaluations_count_once(records):
    _, config, users, results, evaluations = records
    report = aggregate(config, users * 3, results * 4, evaluations * 2)
    assert report["coverage"]["completed"] == 3
    assert report["ratings"]["appeal"]["eligible"] == 2
    assert report["tasks"]["T2"]["eligible"] == 3


def test_duplicate_status_last_record_wins(records):
    _, config, users, results, evaluations = records
    replacement = users[-1].model_copy(update={"status": JobStatus.CANCELLED})
    report = aggregate(config, users + [replacement], results, evaluations)
    assert report["coverage"]["status_counts"]["cancelled"] == 2
    assert report["coverage"]["settled"] and not report["coverage"]["interim"]


def test_individual_mode_for_one_requested_or_one_completed(records):
    _, config, users, results, evaluations = records
    assert aggregate(config.model_copy(update={"user_count": 1}), users[:1], results, evaluations)["individual_mode"]
    only_one = [u.model_copy(update={"status": JobStatus.FAILED}) if i in (1, 2) else u
                for i, u in enumerate(users)]
    assert aggregate(config, only_one, results, evaluations)["individual_mode"]
    assert not aggregate(config, users, results, evaluations)["individual_mode"]


def test_interim_for_unsettled_or_missing_users(records):
    _, config, users, results, evaluations = records
    assert aggregate(config, users, results, evaluations)["coverage"]["interim"]
    report = aggregate(config, users[:-1], results, evaluations)
    assert report["coverage"]["interim"] and not report["coverage"]["accounting_valid"]


def test_empty_eligible_values_are_none(records):
    _, config, users, _, _ = records
    report = aggregate(config, users, [], [])
    assert report["ratings"]["appeal"]["mean"] is None
    assert report["appeal_signal"]["share"] is None
    assert report["tasks"]["T1"]["completion"]["share"] is None


def test_segments_unweighted(records):
    _, config, users, results, evaluations = records
    report = aggregate(config, users, results, evaluations)
    assert report["segments"]["A"]["completed"] == 2
    assert report["segments"]["A"]["appeal_signal"]["denominator"] == 2
    assert report["segments"]["B"]["completed"] == 1
    assert report["segments"]["B"]["appeal_signal"]["share"] is None


def test_findings_code_counts_and_ranks_deduplicated(records, monkeypatch):
    run_id, config, users, results, evaluations = records
    prompts = []
    def label(system, user):
        batch = json.loads(user)["problems"]
        prompts.append(batch)
        return {"labels": [{"index": p["index"], "theme": "Price visibility" if p["task_id"] else "Unclear value"}
                           for p in batch]}, {}
    monkeypatch.setattr("contracts.llm.call_json", label)
    findings = build_findings(run_id, config, results * 2, evaluations[:3] * 2)
    assert not findings.fallback_used
    assert len(findings) == 2 and len(prompts) == 1
    assert findings[0].severity == "blocker"
    assert findings[0].supporting_user_ids == [users[0].user_id, users[1].user_id]
    assert findings[0].eligible_denominator == 2  # not_attempted excluded
    assert findings[0].finding_id == f"{run_id}-f001"
    assert findings[1].eligible_denominator == 3
    assert findings[1].evidence_refs == [f"{users[2].user_id}:evaluation"]


def test_findings_fallback_separates_task_and_severity(records):
    run_id, config, _, results, evaluations = records
    findings = build_findings(run_id, config, results, evaluations[:3])
    assert findings.fallback_used and "Fallback grouping" in findings.method
    assert [f.severity for f in findings] == ["blocker", "major", "minor"]
    assert len(findings[0].supporting_user_ids) == 1  # singleton blocker retained


def test_invalid_theme_payload_falls_back(records, monkeypatch):
    run_id, config, _, results, evaluations = records
    monkeypatch.setattr("contracts.llm.call_json", lambda *args: ({"labels": [{"index": True, "theme": "x"}]}, {}))
    assert build_findings(run_id, config, results, evaluations[:3]).fallback_used


def test_unattempted_task_cannot_contribute_support(records):
    run_id, config, users, results, evaluations = records
    evaluations[2].problems = [Problem(text="No browser visit", task_id="T1", severity="blocker")]
    findings = build_findings(run_id, config, results, evaluations[:3])
    assert all(users[2].user_id not in f.supporting_user_ids for f in findings)


def test_theme_requests_batched_at_most_150(records, monkeypatch):
    run_id, config, _, results, evaluations = records
    evaluations[0].problems = [Problem(text=f"Problem {i}", severity="minor") for i in range(301)]
    sizes = []
    def label(system, user):
        batch = json.loads(user)["problems"]
        sizes.append(len(batch))
        return {"labels": [{"index": i, "theme": "Shared theme"} for i in range(len(batch))]}, {}
    monkeypatch.setattr("contracts.llm.call_json", label)
    findings = build_findings(run_id, config, results, evaluations[:1])
    assert sizes == [150, 150, 1]
    assert len(findings) == 1 and len(findings[0].supporting_user_ids) == 1
