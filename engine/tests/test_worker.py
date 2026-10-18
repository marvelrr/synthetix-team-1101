import asyncio
from contextlib import closing

import pytest

from contracts import db, llm
from contracts.models import Evaluation, JobStatus, SyntheticUser, TaskResult, Usage
from engine import worker
from engine.tests.helpers import config_for, evaluation_response, save_fixture


def records(table, model, run_id="fixture"):
    with closing(db.connect()) as conn:
        return db.load_records(conn, table, model, run_id)


def test_retry_same_id_one_result_and_accumulated_usage(audience, monkeypatch):
    with closing(db.connect()) as conn:
        users = save_fixture(conn, config_for(audience))
    calls = []
    def response(*a, **kw):
        calls.append(1)
        payload, usage = evaluation_response(*a, **kw)
        return ({} if len(calls) <= 2 else payload), usage
    monkeypatch.setattr(llm, "call_json", response)
    counts = asyncio.run(worker.run_worker("fixture"))
    saved = records("users", SyntheticUser)[0]
    assert saved.user_id == users[0].user_id
    assert saved.attempts == 2 and saved.status == JobStatus.COMPLETED
    assert counts["completed"] == 1
    assert len(records("task_results", TaskResult)) == len(records("evaluations", Evaluation)) == 1
    measured = records("usage", Usage)[0]
    assert measured.llm_calls == 3 and measured.input_tokens == 30 and measured.output_tokens == 15
    assert measured.cost_hkd is None


def test_second_failure_is_terminal(audience, monkeypatch):
    with closing(db.connect()) as conn:
        save_fixture(conn, config_for(audience))
    monkeypatch.setattr(llm, "call_json", lambda *a, **kw: ({}, {"input_tokens": 10, "output_tokens": 5}))
    counts = asyncio.run(worker.run_worker("fixture"))
    user = records("users", SyntheticUser)[0]
    assert counts["failed"] == 1 and user.attempts == 2
    assert "evaluation" in user.failure_reason
    assert not records("evaluations", Evaluation)
    assert records("usage", Usage)[0].llm_calls == 4


def test_cancel_mid_run_does_not_schedule_remaining(audience, monkeypatch):
    with closing(db.connect()) as conn:
        save_fixture(conn, config_for(audience, count=10))
    calls = []
    def response(*a, **kw):
        calls.append(1)
        with closing(db.connect()) as own_conn:
            db.request_cancel(own_conn, "fixture")
        return evaluation_response(*a, **kw)
    monkeypatch.setattr(llm, "call_json", response)
    counts = asyncio.run(worker.run_worker("fixture"))
    assert counts == {"queued": 0, "running": 0, "completed": 1, "failed": 0, "cancelled": 9}
    assert len(calls) == 1
    assert all(u.failure_reason == "run cancelled" and u.attempts == 0 for u in records("users", SyntheticUser) if u.status == JobStatus.CANCELLED)
    with closing(db.connect()) as conn:
        assert db.get_run(conn, "fixture")["status"] == "cancelled"


def test_restart_keeps_attempts_id_and_usage(audience, monkeypatch):
    with closing(db.connect()) as conn:
        user = save_fixture(conn, config_for(audience))[0]
        user.status, user.attempts = JobStatus.RUNNING, 1
        db.save_user(conn, user)
        db.save_usage(conn, Usage(run_id="fixture", user_id=user.user_id, llm_calls=2,
                                  input_tokens=9, output_tokens=5, seconds=7))
    monkeypatch.setattr(llm, "call_json", evaluation_response)
    asyncio.run(worker.run_worker("fixture"))
    saved = records("users", SyntheticUser)[0]
    measured = records("usage", Usage)[0]
    assert saved.user_id == user.user_id and saved.attempts == 2 and saved.status == JobStatus.COMPLETED
    assert measured.llm_calls == 3 and measured.input_tokens == 19 and measured.seconds >= 7


def test_restart_at_attempt_limit_fails(audience):
    with closing(db.connect()) as conn:
        user = save_fixture(conn, config_for(audience))[0]
        user.status, user.attempts = JobStatus.RUNNING, 2
        db.save_user(conn, user)
    counts = asyncio.run(worker.run_worker("fixture"))
    assert counts["failed"] == 1
    assert records("users", SyntheticUser)[0].attempts == 2


def test_budget_stops_scheduling(audience, monkeypatch):
    monkeypatch.setenv("LLM_PRICE_IN_HKD_PER_1M", "1000000")
    monkeypatch.setenv("LLM_PRICE_OUT_HKD_PER_1M", "1000000")
    with closing(db.connect()) as conn:
        save_fixture(conn, config_for(audience, count=5, budget_hkd=10))
    monkeypatch.setattr(llm, "call_json", evaluation_response)
    counts = asyncio.run(worker.run_worker("fixture"))
    assert counts["completed"] == 1 and counts["cancelled"] == 4
    assert all(u.failure_reason == "budget reached" for u in records("users", SyntheticUser) if u.status == JobStatus.CANCELLED)
    assert records("usage", Usage)[0].cost_hkd == 15


def test_budget_unknown_cost_fails_closed(audience, monkeypatch):
    monkeypatch.setenv("LLM_PRICE_IN_HKD_PER_1M", "1")
    monkeypatch.setenv("LLM_PRICE_OUT_HKD_PER_1M", "1")
    with closing(db.connect()) as conn:
        save_fixture(conn, config_for(audience, count=3, budget_hkd=10))
    def broken(*a, **kw):
        raise TimeoutError("do not persist this provider payload")
    monkeypatch.setattr(llm, "call_json", broken)
    counts = asyncio.run(worker.run_worker("fixture"))
    assert counts["failed"] == 3
    assert all(u.failure_reason == "budget accounting failed: measured cost is unknown" for u in records("users", SyntheticUser))
    assert records("usage", Usage)[0].cost_hkd is None


def test_contexts_are_fresh_closed_and_concurrency_bounded(audience, monkeypatch):
    contexts, active = [], 0
    class Context:
        closed = False
        async def close(self):
            nonlocal active
            self.closed = True
            active -= 1
    class Browser:
        async def new_context(self, **kwargs):
            nonlocal active
            active += 1
            assert active <= 2
            context = Context()
            contexts.append(context)
            return context
        async def close(self): pass
    class Chromium:
        async def launch(self, **kwargs): return Browser()
    class Playwright:
        chromium = Chromium()
        async def start(self): return self
        async def stop(self): pass
    monkeypatch.setattr(worker, "async_playwright", Playwright)
    async def task(context, user, task, config, run_id):
        await asyncio.sleep(0.005)
        return TaskResult(run_id=run_id, user_id=user.user_id, task_id=task.task_id,
                          outcome="completed", reason="explicit worker test double"), {}
    monkeypatch.setattr(worker.agent, "run_task", task)
    monkeypatch.setattr(llm, "call_json", evaluation_response)
    with closing(db.connect()) as conn:
        save_fixture(conn, config_for(audience, count=5, mode="interactive", product_url="http://localhost:8101", max_concurrency=2))
    counts = asyncio.run(worker.run_worker("fixture"))
    assert counts["completed"] == len(contexts) == 5
    assert len({id(c) for c in contexts}) == 5 and all(c.closed for c in contexts)
    assert all(u.llm_calls == 1 for u in records("usage", Usage))


def test_browser_startup_failure_is_honest_and_accounted(audience, monkeypatch):
    class Chromium:
        async def launch(self, **kw): raise RuntimeError("fixture startup failure")
    class Playwright:
        chromium = Chromium()
        async def start(self): return self
        async def stop(self): pass
    monkeypatch.setattr(worker, "async_playwright", Playwright)
    with closing(db.connect()) as conn:
        save_fixture(conn, config_for(audience, count=3, mode="interactive", product_url="http://localhost:8101"))
    counts = asyncio.run(worker.run_worker("fixture"))
    assert counts["failed"] == 3
    assert all(u.attempts == 2 and "browser startup" in u.failure_reason for u in records("users", SyntheticUser))
    assert not records("task_results", TaskResult) and not records("evaluations", Evaluation)
    assert all(u.llm_calls == 0 for u in records("usage", Usage))


def test_precancel_does_not_open_browser(audience, monkeypatch):
    def unexpected(): raise AssertionError("must not start browser after cancellation")
    monkeypatch.setattr(worker, "async_playwright", unexpected)
    with closing(db.connect()) as conn:
        save_fixture(conn, config_for(audience, count=3, mode="interactive", product_url="http://localhost:8101"))
        db.request_cancel(conn, "fixture")
    counts = asyncio.run(worker.run_worker("fixture"))
    assert counts["cancelled"] == 3


def test_call_start_is_persisted_and_budget_waits_for_known_cost(audience, monkeypatch):
    monkeypatch.setenv("LLM_PRICE_IN_HKD_PER_1M", "1000000")
    monkeypatch.setenv("LLM_PRICE_OUT_HKD_PER_1M", "1000000")
    with closing(db.connect()) as conn:
        save_fixture(conn, config_for(audience, count=2, budget_hkd=100, max_concurrency=2))
    def response(*args, **kwargs):
        with closing(db.connect()) as own_conn:
            measured = db.load_records(own_conn, "usage", Usage, "fixture")
            assert any(u.llm_calls == 1 and u.cost_hkd is None for u in measured)
            assert worker._budget_state(own_conn, db.get_run(own_conn, "fixture")) == "budget accounting pending"
        return evaluation_response(*args, **kwargs)
    monkeypatch.setattr(llm, "call_json", response)
    counts = asyncio.run(worker.run_worker("fixture"))
    assert counts["completed"] == 2
    assert all(u.llm_calls == 1 and u.cost_hkd == 15 for u in records("usage", Usage))


def test_restart_with_pending_call_preserves_unknown_cost(audience, monkeypatch):
    monkeypatch.setenv("LLM_PRICE_IN_HKD_PER_1M", "1")
    monkeypatch.setenv("LLM_PRICE_OUT_HKD_PER_1M", "1")
    with closing(db.connect()) as conn:
        user = save_fixture(conn, config_for(audience))[0]
        user.status, user.attempts = JobStatus.RUNNING, 1
        db.save_user(conn, user)
        # Persisted state when a process dies inside a provider call.
        db.save_usage(conn, Usage(run_id="fixture", user_id=user.user_id, llm_calls=1, seconds=2, cost_hkd=None))
    monkeypatch.setattr(llm, "call_json", evaluation_response)
    asyncio.run(worker.run_worker("fixture"))
    measured = records("usage", Usage)[0]
    assert measured.llm_calls == 2 and measured.input_tokens == 10 and measured.seconds >= 2
    assert measured.cost_hkd is None


def test_known_budget_hit_takes_precedence_over_pending_cost(audience):
    with closing(db.connect()) as conn:
        users = save_fixture(conn, config_for(audience, count=2, budget_hkd=10))
        for user in users:
            user.status = JobStatus.RUNNING
            db.save_user(conn, user)
        db.save_usage(conn, Usage(run_id="fixture", user_id=users[0].user_id, llm_calls=1, cost_hkd=20))
        db.save_usage(conn, Usage(run_id="fixture", user_id=users[1].user_id, llm_calls=1, cost_hkd=None))
        assert worker._budget_state(conn, db.get_run(conn, "fixture")) == "budget reached"
