import asyncio
import json
import os
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from contracts import llm
from contracts.models import TaskSpec
from engine.agent import origin, run_task, success_check, test_data as supplied_test_data
from engine.personas import generate_users
from engine.tests.helpers import config_for


def action(name, element=None, value=None):
    return {"reason": "explicit mocked test action", "action": name, "element": element, "value": value}


def scripted(monkeypatch, actions):
    queue = iter(actions)
    def call(*args, **kwargs):
        item = next(queue)
        if isinstance(item, Exception): raise item
        return item, {"input_tokens": 3, "output_tokens": 2}
    monkeypatch.setattr(llm, "call_json", call)


def browser_run(exercise):
    async def run():
        async with async_playwright() as p:
            cdp = os.environ.get("SYNTHETIX_TEST_CDP_URL")
            if cdp:
                browser = await p.chromium.connect_over_cdp(cdp)
            else:
                try:
                    browser = await p.chromium.launch(headless=True)
                except Exception as exc:
                    detail = str(exc)
                    if "bootstrap_check_in" in detail and "Permission denied" in detail:
                        pytest.skip("macOS execution sandbox denies Chromium Mach service registration; run from a normal terminal")
                    raise
            try:
                context = await browser.new_context(service_workers="block", accept_downloads=False)
                try: return await exercise(context)
                finally: await context.close()
            finally: await browser.close()
    return asyncio.run(run())


@pytest.mark.parametrize("check,expected", [("url_contains:/welcome", True), ("url_contains:/missing", False),
                                           ("text_visible:Welcome", True), ("text_visible:Missing", False)])
def test_code_success_checks(check, expected):
    class Page:
        url = "http://localhost/welcome"
        async def inner_text(self, selector, **kwargs): return "Welcome to the product"
    assert asyncio.run(success_check(Page(), check)) is expected


def test_origins_are_exact():
    assert origin("https://example.com/a") == origin("https://example.com:443/b")
    assert origin("http://localhost:8101") != origin("http://localhost:8102")
    with pytest.raises(ValueError): origin("javascript:alert(1)")


@pytest.mark.parametrize("check", ["url_contains:/signup.html", "text_visible:Start free trial"])
def test_browser_success_checks(audience, stub_url, monkeypatch, check):
    scripted(monkeypatch, [action("click", 1)])
    config = config_for(audience, mode="interactive", product_url=stub_url)
    user = generate_users("r", audience, 1, 42)[0]
    task = TaskSpec(task_id="T1", instruction="Open the free trial form", success_check=check)
    async def exercise(context):
        result, usage = await run_task(context, user, task, config, "r")
        assert result.outcome.value == "completed" and usage["llm_calls"] == 1
    browser_run(exercise)


def test_done_does_not_fabricate_completion(audience, stub_url, monkeypatch):
    scripted(monkeypatch, [action("done")])
    config = config_for(audience, mode="interactive", product_url=stub_url)
    user = generate_users("r", audience, 1, 42)[0]
    async def exercise(context):
        result, _ = await run_task(context, user, config.tasks[0], config, "r")
        assert result.outcome.value == "failed"
        assert result.reason == "agent believed task was complete but success check not met"
    browser_run(exercise)


def test_safety_stop_without_click(audience, stub_url, monkeypatch):
    scripted(monkeypatch, [action("click", 2)])
    config = config_for(audience, mode="interactive", product_url=stub_url)
    user = generate_users("r", audience, 1, 42)[0]
    async def exercise(context):
        result, _ = await run_task(context, user, config.tasks[0], config, "r")
        assert result.outcome.value == "blocked" and result.reason == "safety stop: Buy now"
        assert "not executed" in result.steps[0].agent_reason
    browser_run(exercise)


def test_off_origin_link_is_not_followed(audience, stub_url, monkeypatch):
    scripted(monkeypatch, [action("click", 3)])
    config = config_for(audience, mode="interactive", product_url=stub_url)
    user = generate_users("r", audience, 1, 42)[0]
    async def exercise(context):
        result, _ = await run_task(context, user, config.tasks[0], config, "r")
        assert result.outcome.value == "blocked" and "off-origin" in result.reason
        assert result.steps[0].url == stub_url + "/"
    browser_run(exercise)


def test_only_test_data_can_be_typed(audience, stub_url, monkeypatch):
    scripted(monkeypatch, [action("click", 1), action("type", 1, "invented personal data")])
    config = config_for(audience, mode="interactive", product_url=stub_url)
    user = generate_users("r", audience, 1, 42)[0]
    async def exercise(context):
        result, _ = await run_task(context, user, config.tasks[0], config, "r")
        assert result.outcome.value == "blocked" and "test data" in result.reason
        assert result.steps[-1].value is None
    browser_run(exercise)


def test_trial_with_actual_test_data_and_screenshots(audience, stub_url, monkeypatch):
    config = config_for(audience, mode="interactive", product_url=stub_url)
    user = generate_users("r", audience, 1, 42)[0]
    data = supplied_test_data(user)
    monkeypatch.setenv("SAVE_SCREENSHOTS", "1")
    scripted(monkeypatch, [action("click", 1), action("type", 1, data["name"]), action("type", 2, data["email"]),
                           action("type", 3, data["phone"]), action("click", 4)])
    task = TaskSpec(task_id="T3", instruction="Start the free trial", success_check="url_contains:/welcome.html")
    async def exercise(context):
        result, usage = await run_task(context, user, task, config, "r")
        assert result.outcome.value == "completed" and len(result.steps) == usage["llm_calls"] == 5
        for step in result.steps:
            assert Path(step.screenshot_path).is_file()
            assert step.screenshot_path == f"data/traces/r/{user.user_id}/T3-{step.step}.png"
            evidence = json.loads(step.observation)
            assert evidence["untrusted_page_data"] is True
            assert len(evidence["visible_text_excerpt"]) <= 1200
            assert len(evidence["after_action"]["visible_text_excerpt"]) <= 1200
    browser_run(exercise)


def test_llm_failure_retries_once(audience, stub_url, monkeypatch):
    scripted(monkeypatch, [TimeoutError(), action("done")])
    config = config_for(audience, mode="interactive", product_url=stub_url)
    user = generate_users("r", audience, 1, 42)[0]
    task = TaskSpec(task_id="T1", instruction="Read the price", success_check="text_visible:HK$268 per month")
    async def exercise(context):
        result, usage = await run_task(context, user, task, config, "r")
        assert result.outcome.value == "completed" and usage["llm_calls"] == 2
        assert usage["cost_hkd"] is None
    browser_run(exercise)


def test_step_limit(audience, stub_url, monkeypatch):
    scripted(monkeypatch, [action("scroll")])
    config = config_for(audience, mode="interactive", product_url=stub_url)
    user = generate_users("r", audience, 1, 42)[0]
    task = TaskSpec(task_id="T1", instruction="Find an unavailable feature", success_check="text_visible:Missing", max_steps=1)
    async def exercise(context):
        result, _ = await run_task(context, user, task, config, "r")
        assert result.outcome.value == "failed" and result.reason == "step limit reached"
    browser_run(exercise)


def test_back_cannot_leave_the_initial_product_page(audience, stub_url, monkeypatch):
    scripted(monkeypatch, [action("back")])
    config = config_for(audience, mode="interactive", product_url=stub_url)
    user = generate_users("r", audience, 1, 42)[0]
    async def exercise(context):
        result, _ = await run_task(context, user, config.tasks[0], config, "r")
        assert result.outcome.value == "blocked"
        assert result.reason == "back unavailable: no earlier product page in this task"
        assert result.steps[0].url == stub_url + "/"
        assert result.steps[0].agent_reason.startswith("not executed")
    browser_run(exercise)


def test_back_returns_to_product_page_and_passes_success_check(audience, stub_url, monkeypatch):
    scripted(monkeypatch, [action("click", 1), action("back")])
    config = config_for(audience, mode="interactive", product_url=stub_url)
    user = generate_users("r", audience, 1, 42)[0]
    task = TaskSpec(task_id="T1", instruction="Open the signup form, then return to the home page",
                    success_check="text_visible:HK$268 per month")
    async def exercise(context):
        result, usage = await run_task(context, user, task, config, "r")
        assert result.outcome.value == "completed" and result.reason == "success check passed"
        assert [step.action for step in result.steps] == ["click", "back"]
        assert result.steps[1].url.endswith("/signup.html")
        assert len(result.steps) == usage["llm_calls"] == 2
    browser_run(exercise)
