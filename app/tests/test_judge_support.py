"""All model calls are mocked; no browser or provider requests are made."""
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from app.judge_support import (LiveLimiter, access_allowed, concern_topics,
                               config_for_review, parse_bundle,
                               rating_comparisons, remote_settings_valid,
                               run_reviews)
from contracts.models import (AudienceSpec, Evaluation, JobStatus, Rating,
                              RatingDimension, RunConfig, Segment)


@pytest.fixture
def concept():
    return RunConfig(product_name="RefillHK", product_version="v1", mode="concept",
                     concept_material="Reusable cleaning refills for HK$268 per month.",
                     value_proposition="Less packaging", objective="Find confusing copy",
                     user_count=5, audience=AudienceSpec(spec_version="judge-1",
                         description="HK adults considering refills",
                         segments=[Segment(name=f"Priority {i}", weight=1,
                                           attributes={"priority": [str(i)]},
                                           authored_assumptions=["Invented testing priority"])
                                   for i in range(5)]))


def response_from_prompt(prompt):
    shape = json.loads(prompt.split("JSON shape: ", 1)[1].split("\n", 1)[0])
    shape["ratings"] = {dimension.value: {"score": 4, "not_assessable_reason": None}
                        for dimension in RatingDimension}
    shape["rating_reasons"] = "The supplied price makes the offer understandable."
    shape["strengths"] = ["A monthly price is stated."]
    shape["problems"] = [{"text": "The bottle return process is unspecified.",
                          "task_id": None, "severity": "major"}]
    shape["suggestions"] = ["Explain bottle returns."]
    return shape


def test_five_independent_reviews_accounting_and_no_browser(monkeypatch, concept):
    calls = []
    def model(system, user, **kwargs):
        calls.append(user)
        return response_from_prompt(user), {"input_tokens": 100, "output_tokens": 50}
    monkeypatch.setattr("contracts.llm.call_json", model)
    bundle = run_reviews(concept)
    config, users, results, evaluations = parse_bundle(bundle)
    assert len(calls) == len(users) == len(evaluations) == 5
    assert len({user.user_id for user in users}) == 5
    assert len({user.segment for user in users}) == 5
    assert all(user.status == JobStatus.COMPLETED for user in users)
    assert results == []
    assert all(e.ratings[RatingDimension.EASE_OF_USE].score is None for e in evaluations)
    assert bundle["provenance"]["browser_visits"] == 0
    assert bundle["usage"]["input_tokens"] == 500
    assert bundle["usage"]["llm_calls"] == 5


def test_failure_is_sanitized_and_remains_failed(monkeypatch, concept):
    def fail(*args, **kwargs):
        raise RuntimeError("DO NOT SHOW sk-secret, submitted private copy")
    monkeypatch.setattr("contracts.llm.call_json", fail)
    bundle = run_reviews(concept)
    _, users, _, evaluations = parse_bundle(bundle)
    assert all(user.status == JobStatus.FAILED for user in users)
    assert len(users) == 5 and not evaluations
    assert "sk-secret" not in json.dumps(bundle)
    assert bundle["usage"]["llm_calls"] == 5
    assert bundle["usage"]["cost_hkd"] is None


def test_one_repair_only_and_unknown_cost(monkeypatch, concept):
    calls = []
    def invalid(*args, **kwargs):
        calls.append(1)
        return {}, {"input_tokens": 1, "output_tokens": 1}
    monkeypatch.setattr("contracts.llm.call_json", invalid)
    bundle = run_reviews(concept.model_copy(update={"user_count": 1}))
    assert len(calls) == 2
    assert bundle["users"][0]["status"] == "failed"
    assert bundle["usage"]["llm_calls"] == 2


@pytest.mark.parametrize("count", [0, 6, 1.5, "5", True])
def test_review_bounds(concept, count):
    with pytest.raises(ValueError):
        config_for_review(concept, "Some supplied non-sensitive marketing material.", "HK adults", count)


def test_no_arbitrary_or_local_provider():
    base = {"LLM_API_KEY": "test-only", "LLM_MODEL": "test-model"}
    assert remote_settings_valid({**base, "LLM_BASE_URL": "https://api.deepseek.com/v1"})
    for endpoint in ("http://localhost:11434", "https://attacker.example", "http://api.deepseek.com",
                     "https://api.deepseek.com.evil.example", "https://user:pass@api.deepseek.com",
                     "https://api.deepseek.com?key=leak"):
        assert not remote_settings_valid({**base, "LLM_BASE_URL": endpoint})
    assert not remote_settings_valid({"LLM_BASE_URL": "https://api.deepseek.com"})


def test_access_code_required():
    assert access_allowed("sample-judge-code", "sample-judge-code")
    assert not access_allowed("sample-judge-code", "wrong")
    assert not access_allowed("", "")


def test_process_limit_and_next_day():
    guard = LiveLimiter(5)
    day = datetime(2026, 10, 19, tzinfo=timezone.utc)
    assert guard.acquire(5, day)
    assert not guard.acquire(1, day)
    guard.release()
    assert not guard.acquire(1, day)
    assert guard.acquire(1, datetime(2026, 10, 20, tzinfo=timezone.utc))
    guard.release()


def test_conservative_daily_allowance():
    assert LiveLimiter().daily_profiles == 5
    assert LiveLimiter(1000).daily_profiles == 15
    assert LiveLimiter(0).daily_profiles == 1


def test_keyword_topics_deduplicate_user_and_show_evidence():
    evaluation = Evaluation(run_id="run", user_id="u", mode="concept",
                            ratings={dimension: Rating(score=4) for dimension in RatingDimension},
                            rating_reasons="Based on supplied copy",
                            problems=[{"text": "The price and bottle return cost are unclear.",
                                       "severity": "major"},
                                      {"text": "The trial price is unclear.", "severity": "minor"}])
    topics = concern_topics([evaluation, evaluation])
    price = next(topic for topic in topics if topic["topic"] == "Price and value")
    assert price["supporting_user_ids"] == ["u"]
    assert price["denominator"] == 1
    assert len(price["evidence"]) == 2
    rows = rating_comparisons([evaluation, evaluation])
    assert all(row["Eligible profiles"] == 1 for row in rows)


def test_recorded_streamlit_view_has_no_model_calls(monkeypatch):
    from streamlit.testing.v1 import AppTest
    calls = []
    def deny(*args, **kwargs):
        calls.append(1)
        raise AssertionError("Unexpected model request during UI verification")
    monkeypatch.setattr("contracts.llm.call_json", deny)
    monkeypatch.setenv("SYNTHETIX_JUDGE_LIVE_ENABLED", "0")
    entry = Path(__file__).resolve().parents[1] / "judge_demo.py"
    app = AppTest.from_file(str(entry)).run(timeout=30)
    assert not app.exception and not calls
    assert app.metric[0].value == "5" and app.metric[1].value == "5"
    assert len(app.dataframe) == 6
    assert not app.text_area


def test_live_form_preload_does_not_submit_or_expose_server_secrets(monkeypatch):
    from streamlit.testing.v1 import AppTest
    calls = []
    def deny(*args, **kwargs):
        calls.append(1)
        raise AssertionError("Unexpected model request during UI verification")
    monkeypatch.setattr("contracts.llm.call_json", deny)
    for key, value in {
        "SYNTHETIX_JUDGE_LIVE_ENABLED": "1",
        "SYNTHETIX_JUDGE_ACCESS_CODE": "sample-test-access-only",
        "LLM_BASE_URL": "https://api.deepseek.com", "LLM_MODEL": "test-model",
        "LLM_API_KEY": "sample-test-key-only",
    }.items():
        monkeypatch.setenv(key, value)
    entry = Path(__file__).resolve().parents[1] / "judge_demo.py"
    app = AppTest.from_file(str(entry)).run(timeout=30)
    assert not app.exception and app.text_area[0].value == ""
    assert "sample-test-key-only" not in str(app)
    assert "sample-test-access-only" not in str(app)
    app.button[0].click().run(timeout=30)
    assert not app.exception and len(app.text_area[0].value) > 20
    app.button[1].click().run(timeout=30)
    assert app.error and not app.exception and not calls
