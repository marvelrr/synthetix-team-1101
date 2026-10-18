import re
from contextlib import closing

import pytest

from contracts import db
from contracts.models import Evaluation, JobStatus, RatingDimension, TaskResult, Usage
from engine import api, worker
from engine.tests.helpers import config_for, save_fixture


def test_start_saves_queued_users_and_launches_worker(audience, monkeypatch):
    launches = []
    monkeypatch.setattr(api.subprocess, "Popen", lambda args, **kwargs: launches.append((args, kwargs)))
    config = config_for(audience, count=10)
    run_id = api.start_run(config, is_saved_example=True)
    assert re.fullmatch(r"run-\d{8}-\d{6}-[0-9a-f]{4}", run_id)
    with closing(db.connect()) as conn:
        assert db.get_run(conn, run_id)["is_saved_example"] == 1
        assert db.status_counts(conn, run_id)["queued"] == 10
    args, kwargs = launches[0]
    assert args[1:] == ["-m", "engine.worker", "--run-id", run_id]
    assert kwargs["start_new_session"] is True
    assert kwargs["stdout"].name == f"data/logs/{run_id}.log"


def test_launch_failure_settles_every_user(audience, monkeypatch):
    def failure(*a, **kw): raise OSError("test fixture error")
    monkeypatch.setattr(api.subprocess, "Popen", failure)
    with pytest.raises(RuntimeError, match="worker launch failed"):
        api.start_run(config_for(audience, count=2))
    with closing(db.connect()) as conn:
        run = db.list_runs(conn)[0]
        assert run["status"] == "failed"
        assert db.status_counts(conn, run["run_id"])["failed"] == 2


def test_budget_requires_known_prices_but_estimate_can_be_unavailable(audience):
    config = config_for(audience, budget_hkd=10)
    with pytest.raises(ValueError, match="budget_hkd requires LLM_PRICE"):
        api.start_run(config)
    assert api.estimate_run(config) == {"available": False, "cost_hkd": None, "minutes": None, "basis": "no measured runs yet"}


def test_config_instance_revalidated(audience):
    config = config_for(audience)
    config.user_count = "10"
    with pytest.raises(ValueError): api.start_run(config)
    config = config_for(audience)
    config.tasks[0].success_check = "model_says:done"
    with pytest.raises(ValueError, match="success check"): api.start_run(config)
    config = config_for(audience)
    config.tasks[0].task_id = "../outside"
    with pytest.raises(ValueError, match="safe names"): api.start_run(config)


def test_cancel_sets_flag(audience):
    with closing(db.connect()) as conn:
        save_fixture(conn, config_for(audience))
    api.cancel_run("fixture")
    with closing(db.connect()) as conn:
        assert db.get_run(conn, "fixture")["cancel_requested"] == 1


def _complete(conn, user, seconds, cost):
    db.save_task_result(conn, TaskResult(run_id=user.run_id, user_id=user.user_id, task_id="T1",
                                       outcome="not_attempted", reason="authored concept test fixture"))
    db.save_evaluation(conn, Evaluation(run_id=user.run_id, user_id=user.user_id, mode="concept",
                      ratings={d: {"not_assessable_reason": "authored fixture"} for d in RatingDimension},
                      rating_reasons="authored fixture"))
    db.save_usage(conn, Usage(run_id=user.run_id, user_id=user.user_id, seconds=seconds, cost_hkd=cost))
    user.status = JobStatus.COMPLETED
    db.save_user(conn, user)


def test_estimate_uses_completed_same_mode_only_and_propagates_unknown(audience):
    with closing(db.connect()) as conn:
        users = save_fixture(conn, config_for(audience, count=3))
        _complete(conn, users[0], 12, 2)
        _complete(conn, users[1], 24, None)
        users[2].status = JobStatus.FAILED
        db.save_user(conn, users[2])
        db.save_usage(conn, Usage(run_id="fixture", user_id=users[2].user_id, seconds=999, cost_hkd=999))
        db.set_run_status(conn, "fixture", JobStatus.COMPLETED)
    estimate = api.estimate_run(config_for(audience, count=10, max_concurrency=5))
    assert estimate["available"] and estimate["cost_hkd"] is None
    assert estimate["minutes"] == pytest.approx(0.6)
    assert "untested at this size" in estimate["basis"]
    assert not api.estimate_run(config_for(audience, mode="interactive", product_url="http://localhost:8101"))["available"]
    with closing(db.connect()) as conn:
        _complete(conn, users[1], 24, 4)
    estimate = api.estimate_run(config_for(audience, count=2, max_concurrency=1))
    assert estimate["cost_hkd"] == 6
    assert "untested at this size" not in estimate["basis"]


def test_accounting_violation_is_loud(audience, monkeypatch, caplog):
    with closing(db.connect()) as conn:
        save_fixture(conn, config_for(audience))
        with monkeypatch.context() as patch:
            patch.setattr(db, "status_counts", lambda *a: {"queued": 0})
            with pytest.raises(AssertionError): worker.assert_accounting(conn, "fixture", 1)
    assert "ACCOUNTING INVARIANT BROKEN" in caplog.text


def test_estimate_excludes_development_fake_runs(audience):
    config = config_for(audience)
    config.product_name = "[FAKE] Development example"
    with closing(db.connect()) as conn:
        users = save_fixture(conn, config)
        _complete(conn, users[0], 15, 1)
        db.set_run_status(conn, "fixture", JobStatus.COMPLETED)
    assert api.estimate_run(config_for(audience))["available"] is False
