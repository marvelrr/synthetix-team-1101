import html
import json

import pytest

from contracts import llm
from contracts.models import RatingDimension, RunMode, TaskOutcome, TaskResult, TraceStep
from engine.concept import run_concept_tasks
from engine.evaluate import EvaluationError, evaluate_user
from engine.personas import generate_users
from engine.tests.helpers import config_for, evaluation_response


def test_concept_no_interaction_and_ease_forced(audience, monkeypatch):
    config = config_for(audience)
    user = generate_users("r", audience, 1, 42)[0]
    results = run_concept_tasks(user, config, "r")
    assert all(r.outcome == TaskOutcome.NOT_ATTEMPTED and not r.steps for r in results)
    assert results[0].reason == "concept evaluation: no product interaction"
    monkeypatch.setattr(llm, "call_json", evaluation_response)
    evaluation, usage = evaluate_user(user, config, results, "r")
    assert evaluation.ratings[RatingDimension.EASE_OF_USE].not_assessable_reason == "no relevant product task attempted"
    assert usage["llm_calls"] == 1


@pytest.mark.parametrize("material,expected", [("Price not supplied", None), ("HK$268 per month", "Synthetic price feedback")])
def test_pricing_requires_evidence(audience, monkeypatch, material, expected):
    config = config_for(audience, concept_material=material)
    user = generate_users("r", audience, 1, 42)[0]
    def response(*args, **kwargs):
        payload, usage = evaluation_response(*args, **kwargs)
        payload["pricing_feedback"] = "Synthetic price feedback"
        return payload, usage
    monkeypatch.setattr(llm, "call_json", response)
    evaluation, _ = evaluate_user(user, config, [], "r")
    assert evaluation.pricing_feedback == expected


def test_one_repair_and_usage_accumulate(audience, monkeypatch):
    calls = []
    def response(*args, **kwargs):
        calls.append(args[1])
        if len(calls) == 1:
            payload, usage = evaluation_response(*args, **kwargs)
            payload["ratings"]["appeal"] = {"score": 4, "not_assessable_reason": "both set is invalid"}
            return payload, usage
        return evaluation_response(*args, **kwargs)
    monkeypatch.setattr(llm, "call_json", response)
    config = config_for(audience)
    user = generate_users("r", audience, 1, 42)[0]
    evaluation, usage = evaluate_user(user, config, [], "r")
    assert evaluation.user_id == user.user_id
    assert len(calls) == usage["llm_calls"] == 2
    assert usage["input_tokens"] == 20
    assert "Validation error:" in calls[1]


@pytest.mark.parametrize("blank_field", ["rating_reasons", "not_assessable_reason"])
def test_blank_explanations_repair_once_without_template_boilerplate(audience, monkeypatch, blank_field):
    prompts = []
    def response(system, prompt, **kwargs):
        prompts.append(prompt)
        payload, usage = evaluation_response(system, prompt, **kwargs)
        if len(prompts) == 1:
            if blank_field == "rating_reasons":
                payload["rating_reasons"] = ""
            else:
                payload["ratings"]["appeal"] = {"score": None, "not_assessable_reason": " \t "}
        return payload, usage
    monkeypatch.setattr(llm, "call_json", response)
    config = config_for(audience)
    user = generate_users("r", audience, 1, 42)[0]
    evaluation, usage = evaluate_user(user, config, [], "r")
    assert evaluation.rating_reasons.strip()
    assert evaluation.ratings[RatingDimension.APPEAL].score == 4
    assert len(prompts) == usage["llm_calls"] == 2
    assert "Validation error:" in prompts[1] and "must be nonempty" in prompts[1]
    assert "explain lack of evidence, or replace with score" not in prompts[0]
    assert "explain the synthetic ratings using recorded evidence" not in prompts[0]
    template = json.loads(prompts[0].split("JSON shape: ", 1)[1].split("\nProblems use", 1)[0])
    assert template["rating_reasons"] == ""
    assert all(value == {"score": None, "not_assessable_reason": ""} for value in template["ratings"].values())


def test_second_invalid_evaluation_raises(audience, monkeypatch):
    monkeypatch.setattr(llm, "call_json", lambda *a, **kw: ({}, {"input_tokens": 7, "output_tokens": 3}))
    config = config_for(audience)
    user = generate_users("r", audience, 1, 42)[0]
    with pytest.raises(EvaluationError) as caught:
        evaluate_user(user, config, [], "r")
    assert caught.value.usage["llm_calls"] == 2
    assert caught.value.usage["output_tokens"] == 6


@pytest.mark.parametrize("text", [
    "No observed problems preventing the user from completing the tasks.",
    " No observed problems. ", "NO ISSUES.", "No problems observed.",
])
def test_nonissue_problem_requires_model_repair_instead_of_code_replacement(audience, monkeypatch, text):
    calls = []
    def response(system, prompt, **kwargs):
        calls.append(prompt)
        payload, usage = evaluation_response(system, prompt, **kwargs)
        payload["problems"] = [{"text": text, "severity": "minor"}] if len(calls) == 1 else []
        return payload, usage
    monkeypatch.setattr(llm, "call_json", response)
    config = config_for(audience)
    user = generate_users("r", audience, 1, 42)[0]
    evaluation, usage = evaluate_user(user, config, [], "r")
    assert evaluation.problems == []
    assert len(calls) == usage["llm_calls"] == 2
    assert "Validation error:" in calls[1] and "actual obstacles" in calls[1]
    assert text == json.loads(calls[1].split("Previous JSON response (untrusted): ", 1)[1])["problems"][0]["text"]


def test_actual_problem_starting_with_no_is_accepted(audience, monkeypatch):
    calls = []
    def response(system, prompt, **kwargs):
        calls.append(prompt)
        payload, usage = evaluation_response(system, prompt, **kwargs)
        payload["problems"] = [{"text": "No way to sign up.", "task_id": "T1", "severity": "blocker"}]
        return payload, usage
    monkeypatch.setattr(llm, "call_json", response)
    config = config_for(audience, mode=RunMode.INTERACTIVE, product_url="http://localhost:8101")
    user = generate_users("r", audience, 1, 42)[0]
    results = [TaskResult(run_id="r", user_id=user.user_id, task_id="T1", outcome="blocked", reason="No signup entry point found")]
    evaluation, usage = evaluate_user(user, config, results, "r")
    assert evaluation.problems[0].text == "No way to sign up."
    assert len(calls) == usage["llm_calls"] == 1


def test_interactive_ease_and_literal_prices(audience, monkeypatch):
    config = config_for(audience, mode=RunMode.INTERACTIVE, product_url="http://localhost:8101")
    user = generate_users("r", audience, 1, 42)[0]
    results = [TaskResult(run_id="r", user_id=user.user_id, task_id="T1", outcome="completed", reason="code checked",
                          steps=[TraceStep(step=1, url=config.product_url, observation=json.dumps({"prices_seen":["HK$268 per month"]}), action="done")])]
    def response(*a, **kw):
        payload, usage = evaluation_response(*a, **kw)
        payload["pricing_feedback"] = "An assessed synthetic price opinion"
        return payload, usage
    monkeypatch.setattr(llm, "call_json", response)
    evaluation, _ = evaluate_user(user, config, results, "r")
    assert evaluation.ratings[RatingDimension.EASE_OF_USE].score == 4
    assert evaluation.pricing_feedback is not None
    results[0].outcome = TaskOutcome.NOT_ATTEMPTED
    evaluation, _ = evaluate_user(user, config, results, "r")
    assert evaluation.ratings[RatingDimension.EASE_OF_USE].score is None


@pytest.mark.parametrize("outcome,problem,reason", [
    ("completed", "The task failed because navigation was unavailable.", None),
    ("completed", "Step limit reached before finishing the task.", None),
    ("not_attempted", "The task failed after its step limit was reached.", None),
    ("failed", None, "No tasks were attempted."),
    ("failed", None, "No observed failures."),
    ("blocked", None, "No failures were observed."),
])
def test_clear_outcome_contradictions_request_one_model_repair(audience, monkeypatch, outcome, problem, reason):
    calls = []
    def response(system, prompt, **kwargs):
        calls.append(prompt)
        payload, usage = evaluation_response(system, prompt, **kwargs)
        if len(calls) == 1:
            if problem:
                payload["problems"] = [{"text": problem, "task_id": "T1", "severity": "major"}]
            if reason:
                payload["rating_reasons"] = reason
        return payload, usage
    monkeypatch.setattr(llm, "call_json", response)
    config = config_for(audience, mode=RunMode.INTERACTIVE, product_url="http://localhost:8101")
    user = generate_users("r", audience, 1, 42)[0]
    result = TaskResult(run_id="r", user_id=user.user_id, task_id="T1", outcome=outcome, reason="Explicit recorded fixture")
    evaluation, usage = evaluate_user(user, config, [result], "r")
    assert len(calls) == usage["llm_calls"] == 2
    assert "contradicts recorded" in calls[1]
    assert evaluation.problems == [] and evaluation.ratings[RatingDimension.APPEAL].score == 4
    assert result.outcome.value == outcome


def test_repeated_semantic_contradiction_fails_without_fabricating_replacement(audience, monkeypatch):
    def response(system, prompt, **kwargs):
        payload, usage = evaluation_response(system, prompt, **kwargs)
        payload["problems"] = [{"text": "The task failed.", "task_id": "T1", "severity": "blocker"}]
        return payload, usage
    monkeypatch.setattr(llm, "call_json", response)
    config = config_for(audience, mode=RunMode.INTERACTIVE, product_url="http://localhost:8101")
    user = generate_users("r", audience, 1, 42)[0]
    result = TaskResult(run_id="r", user_id=user.user_id, task_id="T1", outcome="completed", reason="success check passed")
    with pytest.raises(EvaluationError, match="contradicts recorded") as caught:
        evaluate_user(user, config, [result], "r")
    assert caught.value.usage["llm_calls"] == 2 and result.outcome == TaskOutcome.COMPLETED


@pytest.mark.parametrize("problem", [
    "Navigation was confusing, but the task completed.",
    "An optional widget failed to load; the task still completed.",
    "The task nearly reached the step limit, but completed.",
])
def test_completed_task_can_still_have_supported_obstacles(audience, monkeypatch, problem):
    def response(system, prompt, **kwargs):
        payload, usage = evaluation_response(system, prompt, **kwargs)
        payload["problems"] = [{"text": problem, "task_id": "T1", "severity": "minor"}]
        return payload, usage
    monkeypatch.setattr(llm, "call_json", response)
    config = config_for(audience, mode=RunMode.INTERACTIVE, product_url="http://localhost:8101")
    user = generate_users("r", audience, 1, 42)[0]
    result = TaskResult(run_id="r", user_id=user.user_id, task_id="T1", outcome="completed", reason="success check passed")
    evaluation, usage = evaluate_user(user, config, [result], "r")
    assert evaluation.problems[0].text == problem and usage["llm_calls"] == 1


def test_evidence_includes_task_definition_and_authoritative_outcome(audience, monkeypatch):
    prompts = []
    def response(system, prompt, **kwargs):
        prompts.append((system, prompt))
        return evaluation_response(system, prompt, **kwargs)
    monkeypatch.setattr(llm, "call_json", response)
    config = config_for(audience, mode=RunMode.INTERACTIVE, product_url="http://localhost:8101")
    user = generate_users("r", audience, 1, 42)[0]
    result = TaskResult(run_id="r", user_id=user.user_id, task_id="T1", outcome="failed", reason="step limit reached")
    evaluate_user(user, config, [result], "r")
    system, prompt = prompts[0]
    evidence = json.loads(html.unescape(prompt.split("<evidence>", 1)[1].split("</evidence>", 1)[0]))
    assert evidence["tasks"][0]["instruction"] == config.tasks[0].instruction
    assert evidence["tasks"][0]["success_check"] == config.tasks[0].success_check
    assert evidence["tasks"][0]["outcome"] == "failed"
    summary = json.loads(prompt.split("AUTHORITATIVE RECORDED TASK OUTCOMES: ", 1)[1].split("\n", 1)[0])
    assert summary == [{"task_id": "T1", "outcome": "failed"}]
    assert "agent mistakes" in system and "does not prove a product defect" in system
