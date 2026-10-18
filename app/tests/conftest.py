from __future__ import annotations

import pytest

from contracts.models import (AudienceSpec, Evaluation, JobStatus, Problem, Rating,
                              RatingDimension, RunConfig, Segment, SyntheticUser,
                              TaskOutcome, TaskResult, TaskSpec)


@pytest.fixture(autouse=True)
def no_live_llm(monkeypatch):
    def deny(*args, **kwargs):
        raise RuntimeError("Tests must explicitly mock contracts.llm.call_json")
    monkeypatch.setattr("contracts.llm.call_json", deny)


@pytest.fixture
def records():
    run_id = "run-test"
    config = RunConfig(product_name="RefillHK", product_version="v1", mode="interactive",
                       product_url="http://localhost:8101", value_proposition="Reusable cleaning refills",
                       objective="Find friction", user_count=6,
                       audience=AudienceSpec(spec_version="test-1", description="Test assumptions",
                                             segments=[Segment(name="A", weight=1, attributes={}),
                                                       Segment(name="B", weight=1, attributes={})]),
                       tasks=[TaskSpec(task_id="T1", instruction="Find price", success_check="text_visible:HK$268"),
                              TaskSpec(task_id="T2", instruction="Check area", success_check="text_visible:Kwun Tong")])
    users = [SyntheticUser(user_id=f"{run_id}-u{i}", run_id=run_id, segment="A" if i < 3 else "B",
                           profile={}, generator_version="test", status=status)
             for i, status in enumerate([JobStatus.COMPLETED, JobStatus.COMPLETED, JobStatus.COMPLETED,
                                         JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.RUNNING], 1)]
    evaluations = []
    for index, user in enumerate(users[:4]):
        ratings = {dim: Rating(score=4) for dim in RatingDimension}
        ratings[RatingDimension.APPEAL] = [Rating(score=5), Rating(score=3),
                                           Rating(not_assessable_reason="Insufficient context"), Rating(score=5)][index]
        problems = ([Problem(text="Price hidden", task_id="T1", severity="blocker")] if index == 0 else
                    [Problem(text="Price hard to locate", task_id="T1", severity="minor")] if index == 1 else
                    [Problem(text="Unclear value", severity="major")] if index == 2 else [])
        evaluations.append(Evaluation(run_id=run_id, user_id=user.user_id, mode="interactive",
                                      ratings=ratings, rating_reasons="Recorded task evidence", problems=problems))
    outcomes = [("T1", [TaskOutcome.COMPLETED, TaskOutcome.FAILED, TaskOutcome.NOT_ATTEMPTED]),
                ("T2", [TaskOutcome.BLOCKED, TaskOutcome.COMPLETED, TaskOutcome.COMPLETED])]
    results = [TaskResult(run_id=run_id, user_id=user.user_id, task_id=tid, outcome=outcome,
                          reason="Recorded evidence")
               for tid, task_outcomes in outcomes for user, outcome in zip(users[:3], task_outcomes)]
    return run_id, config, users, results, evaluations
