"""Run from the repository root: streamlit run app/main.py."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

from contextlib import closing
from datetime import datetime
import json
import os
import re
import tempfile
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests
import streamlit as st

from app import engine_client
from app.aggregate import aggregate, build_findings
from app.exports import export_csv, export_pdf
from contracts import db
from contracts.models import (AudienceSpec, Evaluation, Finding, JobStatus,
                              RatingDimension, RunConfig, RunMode, SyntheticUser,
                              TaskResult, TaskSpec, Usage)

DISCLAIMER = "Synthetic simulation — not real user research"
RATING_LABELS = {"appeal": "Appeal", "usefulness": "Usefulness", "ease_of_use": "Ease of use",
                 "trust": "Trust", "intention_to_use": "Intention to use"}
STATUS_ORDER = ["queued", "running", "completed", "failed", "cancelled"]
FAKE_MODE = os.environ.get("SYNTHETIX_FAKE_ENGINE", "0") == "1"
LOCAL_AI_PAUSED = (
    not FAKE_MODE
    and os.environ.get("SYNTHETIX_LOCAL_INFERENCE_ALLOWED") == "0"
    and urlsplit(os.environ.get("LLM_BASE_URL", "")).hostname in {"localhost", "127.0.0.1", "::1"}
)

st.set_page_config(page_title="Synthetix · Product signals", page_icon="◈", layout="wide",
                   initial_sidebar_state="auto")
st.markdown("""
<style>
.block-container { max-width:1180px; padding-top:5rem; padding-bottom:4rem; }
[data-testid="stSidebar"] { border-right:1px solid rgba(127,127,127,.2); }
h1,h2,h3 { letter-spacing:-.025em; }
h1 { font-weight:720 !important; }
.syn-eyebrow { color:inherit; font-weight:750; letter-spacing:.14em; font-size:.74rem; margin-bottom:.4rem; }
.syn-disclaimer { padding:.7rem .9rem; background:#fff5de; border:1px solid #ead6a8; border-radius:.6rem; color:#715523; font-size:.86rem; margin:0 0 1.3rem; }
.syn-subtle { color:inherit; font-size:.95rem; line-height:1.6; }
[data-testid="stMetric"] { padding:1rem; border:1px solid rgba(127,127,127,.2); border-radius:.8rem; }
[data-testid="stMetricLabel"] { white-space:normal; }
[data-testid="stDataFrame"], [data-testid="stDataEditor"] { max-width:100%; }
.stButton button, .stDownloadButton button { border-radius:.55rem; }
a { overflow-wrap:anywhere; }
@media (max-width:600px) {
 .block-container { padding-left:1rem; padding-right:1rem; padding-top:5rem; }
 h1 { font-size:2rem !important; }
 [data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
 [data-testid="stColumn"] { min-width:min(100%,155px) !important; }
 .syn-disclaimer { font-size:.78rem; }
}
</style>
""", unsafe_allow_html=True)


def _date(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, ZoneInfo("Asia/Hong_Kong")).strftime("%d %b %Y, %H:%M HKT")


def _all_runs() -> list[dict]:
    with closing(db.connect()) as conn:
        runs = db.list_runs(conn)
        return runs if FAKE_MODE else [run for run in runs if not run["config"].product_name.startswith("[FAKE]")]


def _report_metadata_path(run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", run_id):
        raise ValueError("Invalid report run ID")
    return ROOT / "data/report_metadata" / f"{run_id}.json"


def _read_report_metadata(run_id: str) -> dict:
    try:
        metadata = json.loads(_report_metadata_path(run_id).read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            return {}
        result = {}
        method = metadata.get("findings_method")
        if isinstance(method, str) and 0 < len(method) <= 400:
            result["findings_method"] = method
        notes = metadata.get("quality_notes")
        if isinstance(notes, list):
            valid_notes = [note for note in notes[:8]
                           if isinstance(note, str) and 0 < len(note) <= 1000]
            if valid_notes:
                result["quality_notes"] = valid_notes
        return result
    except (OSError, ValueError):
        return {}


def _save_report_metadata(run_id: str, method: str) -> None:
    path = _report_metadata_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = _read_report_metadata(run_id)
    metadata["findings_method"] = method
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{run_id}-", suffix=".tmp", delete=False) as handle:
            temporary_path = Path(handle.name)
            json.dump(metadata, handle, ensure_ascii=False)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _snapshot(run_id: str) -> dict | None:
    with closing(db.connect()) as conn:
        run = db.get_run(conn, run_id)
        if not run:
            return None
        run.update(_read_report_metadata(run_id))
        return {"run": run,
                "users": db.load_records(conn, "users", SyntheticUser, run_id),
                "task_results": db.load_records(conn, "task_results", TaskResult, run_id),
                "evaluations": db.load_records(conn, "evaluations", Evaluation, run_id),
                "findings": db.load_records(conn, "findings", Finding, run_id),
                "usage": db.load_records(conn, "usage", Usage, run_id)}


def _summary(data: dict) -> dict:
    return aggregate(data["run"]["config"], data["users"], data["task_results"], data["evaluations"])


def _banner(run: dict, interim: bool = False) -> None:
    if run["is_saved_example"]:
        st.info(f"Saved example — recorded {_date(run['created_at'])}, not live")
    if run["config"].product_name.startswith("[FAKE]"):
        st.error("DEVELOPMENT FAKE DATA · This run cannot be used as a demo or research evidence.")
    if interim:
        st.warning("Interim — users are still queued or running. These results can change.")
    for note in run.get("quality_notes", []):
        st.warning(note)


def _share(signal: dict, label: str = "rated") -> str:
    n, total = signal["numerator"], signal["denominator"]
    return f"{n / total:.0%} ({n} of {total} {label})" if total else f"Not assessable (0 of 0 {label})"


def _navigate(page: str) -> None:
    st.session_state["pending_navigation"] = page
    st.rerun()


def _default_tasks() -> list[dict]:
    path = ROOT / "demo_product/tasks.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return [
        {"task_id": "T1", "instruction": "Find the monthly price of the Basic plan", "success_check": "text_visible:HK$268 per month", "max_steps": 15},
        {"task_id": "T2", "instruction": "Check whether RefillHK delivers to Kwun Tong", "success_check": "text_visible:Kwun Tong", "max_steps": 15},
        {"task_id": "T3", "instruction": "Start the free trial using the test details provided", "success_check": "url_contains:/welcome.html", "max_steps": 15},
    ]


def _health_check(url: str) -> tuple[bool, str]:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return False, "Enter an http:// or https:// URL without credentials."
        # A container's host alias is not generally resolvable from this host-side UI.
        check_url = url.replace("http://host.docker.internal:", "http://127.0.0.1:", 1)
        response = requests.get(check_url, timeout=5)
        response.raise_for_status()
        return True, f"Product responded with HTTP {response.status_code}."
    except requests.RequestException as exc:
        return False, f"Product could not be reached ({type(exc).__name__}). Check the URL and start the product server."


def _new_test() -> None:
    st.markdown('<div class="syn-eyebrow">SET UP A TEST</div>', unsafe_allow_html=True)
    st.title("A clearer first signal.")
    st.markdown("Explore a product with synthetic profiles, inspect what actually happened, and decide what to validate with people.")
    if LOCAL_AI_PAUSED:
        st.info("Local AI is paused. You can edit a test plan or open Runs to review recorded results. New AI tests are disabled.")
    if "draft_config" in st.session_state:
        _review_plan(st.session_state["draft_config"])
        return
    if "pending_mode" in st.session_state:
        st.session_state["new_mode"] = st.session_state.pop("pending_mode")
    default_host = "host.docker.internal" if os.environ.get("SYNTHETIX_CDP_URL") else "localhost"
    with st.container(border=True):
        st.subheader("1 · Product & purpose")
        left, right = st.columns(2)
        product_name = left.text_input("Product name", "RefillHK", key="new_product_name")
        product_version = right.text_input("Product version", "v1", key="new_product_version")
        mode_value = st.radio("Evaluation mode", ["interactive", "concept"], horizontal=True,
                              format_func=lambda x: "Live product" if x == "interactive" else "Concept material", key="new_mode")
        url, material = None, None
        if mode_value == "interactive":
            st.caption("An isolated browser attempts tasks. Completion requires the success check to pass in code.")
            url = st.text_input("Product URL", f"http://{default_host}:8101", key="new_product_url")
            if st.button("Check product URL", key="check_url"):
                with st.spinner("Checking the product (up to 5 seconds)…"):
                    ok, message = _health_check(url)
                st.session_state["url_check"] = (url, ok, message)
            checked = st.session_state.get("url_check")
            if checked and checked[0] == url:
                (st.success if checked[1] else st.error)(checked[2])
                if not checked[1] and st.button("Switch to concept evaluation"):
                    st.session_state["pending_mode"] = "concept"
                    st.rerun()
        else:
            st.caption("Profiles review supplied material. No product visit or usability task is claimed.")
            material = st.text_area("Concept material", height=180, key="new_concept_material",
                                    placeholder="Paste the concept, product description, pricing and limitations to review.")
        value_proposition = st.text_area("Value proposition", "Monthly household cleaning-product refills in reusable bottles, delivered in Hong Kong.", height=85, key="new_value")
        objective = st.text_input("What do you want to learn?", "Can people find the price, check delivery coverage and start a free trial?", key="new_objective")
    with st.container(border=True):
        st.subheader("2 · Synthetic audience")
        st.caption("Starter profiles are authored assumptions. The mix is illustrative and does not represent Hong Kong's population.")
        audience_text = (ROOT / "app/presets/hk_audience.json").read_text(encoding="utf-8")
        try:
            preview = AudienceSpec.model_validate_json(st.session_state.get("new_audience", audience_text))
            st.write(" · ".join(segment.name for segment in preview.segments))
        except ValueError:
            pass
        with st.expander("Inspect or edit audience assumptions"):
            audience_text = st.text_area("AudienceSpec JSON", audience_text, height=320, key="new_audience")
        count = st.number_input("Number of synthetic users", min_value=1, max_value=10_000, value=1, step=1, key="new_count")
        st.caption("Start small. A permitted maximum of 10,000 is a configuration limit, not a measured capacity claim.")
    with st.container(border=True):
        st.subheader("3 · Tasks & execution")
        st.caption("Task completion is checked in code. Use text_visible:<text> or url_contains:<text>.")
        tasks = st.data_editor(_default_tasks(), num_rows="dynamic", hide_index=True, use_container_width=True,
                               column_config={"task_id": st.column_config.TextColumn("ID", required=True, width="small"),
                                              "instruction": st.column_config.TextColumn("Task instruction", required=True, width="large"),
                                              "success_check": st.column_config.TextColumn("Success check", required=True, width="large"),
                                              "max_steps": st.column_config.NumberColumn("Max steps", min_value=1, max_value=50, step=1, required=True)}, key="new_tasks")
        c1, c2 = st.columns(2)
        concurrency = c1.number_input("Concurrent users", min_value=1, max_value=50, value=5, step=1, key="new_concurrency")
        seed = c2.number_input("Persona seed", min_value=0, value=42, step=1, key="new_seed")
        set_budget = st.checkbox("Set a budget in HKD", key="new_set_budget")
        budget = st.number_input("Budget (HKD)", min_value=0.01, value=10.0, step=1.0, key="new_budget") if set_budget else None
        if set_budget:
            st.caption("A budget requires configured input and output token prices. Unknown local-model cost cannot be treated as zero.")
    if st.button("Review test plan →", type="primary", use_container_width=True):
        try:
            audience = AudienceSpec.model_validate_json(audience_text)
            parsed_tasks = [TaskSpec.model_validate(t) for t in tasks]
            if not product_name.strip() or not product_version.strip() or not value_proposition.strip() or not objective.strip():
                raise ValueError("Product name, version, value proposition and objective are required.")
            if mode_value == "interactive":
                with st.spinner("Checking that the product can be reached…"):
                    ok, message = _health_check(url or "")
                st.session_state["url_check"] = (url, ok, message)
                if not ok:
                    st.error(message)
                    st.rerun()
            config = RunConfig(product_name=product_name.strip(), product_version=product_version.strip(), mode=mode_value,
                               product_url=url if mode_value == "interactive" else None, concept_material=material,
                               value_proposition=value_proposition, objective=objective, audience=audience,
                               user_count=count, tasks=parsed_tasks, seed=seed, max_concurrency=concurrency, budget_hkd=budget)
            st.session_state["draft_config"] = config
            st.session_state["launch_in_progress"] = False
            st.rerun()
        except (ValueError, TypeError) as exc:
            st.error(f"Please fix the test plan: {exc}")


def _review_plan(config: RunConfig) -> None:
    st.subheader("Review your plan")
    st.caption("Check the scope and assumptions before launching. Synthetic results are early signals.")
    st.info("LIVE PRODUCT · Agents attempt tasks in an isolated browser. Outcomes reflect these attempts, not real-user behaviour."
            if config.mode == RunMode.INTERACTIVE else "CONCEPT · Profiles review supplied material. Product interaction and ease of use cannot be assessed.")
    with st.container(border=True):
        st.write(f"**{config.product_name} · {config.product_version}**")
        st.write(config.value_proposition)
        st.write(f"**Objective:** {config.objective}")
        if config.product_url:
            st.code(config.product_url, language=None)
        else:
            with st.expander("Concept material"):
                st.write(config.concept_material)
        st.write(f"**{config.user_count:,} requested users** · concurrency {config.max_concurrency} · seed {config.seed}")
        total_weight = sum(segment.weight for segment in config.audience.segments)
        st.dataframe([{"Segment": segment.name, "Approximate users": round(config.user_count * segment.weight / total_weight, 1),
                       "Evidence": f"{len(segment.sourced_facts)} sourced facts / {len(segment.authored_assumptions)} authored assumptions"}
                      for segment in config.audience.segments], hide_index=True, use_container_width=True)
        st.caption("Approximate allocation shown above. The engine uses largest remainders to allocate exactly the requested count.")
        st.dataframe([{"ID": task.task_id, "Task": task.instruction, "Success check": task.success_check, "Max steps": task.max_steps}
                      for task in config.tasks], hide_index=True, use_container_width=True)
    try:
        estimate = engine_client.estimate_run(config)
        if estimate["available"]:
            st.write(f"**Measured estimate:** {estimate['minutes']:.1f} minutes · " + (f"HK${estimate['cost_hkd']:.3f}" if estimate['cost_hkd'] is not None else "cost unknown"))
            st.caption(estimate["basis"])
            if "untested at this size" in estimate["basis"]:
                st.warning("Untested at this size — the requested count exceeds the largest measured completed run.")
        else:
            st.info("Estimate unavailable — no measured runs yet")
            st.warning("This mode has no measured capacity yet. Start with one user.")
    except (ValueError, RuntimeError) as exc:
        st.warning(f"Estimate unavailable: {exc}")
    st.caption("Launch uses only supplied test details. Unsafe actions are blocked. A completed user can still have failed or blocked tasks; all outcomes remain visible.")
    back, launch = st.columns([1, 2])
    if back.button("← Edit plan", use_container_width=True):
        del st.session_state["draft_config"]
        st.rerun()
    if launch.button("Launch test", type="primary", disabled=LOCAL_AI_PAUSED or st.session_state.get("launch_in_progress", False), use_container_width=True):
        st.session_state["launch_in_progress"] = True
        try:
            run_id = engine_client.start_run(config)
            st.session_state["active_run"] = run_id
            st.session_state["run_detail_view"] = "Progress"
            del st.session_state["draft_config"]
            _navigate("Runs")
        except Exception as exc:
            st.session_state["launch_in_progress"] = False
            st.error(f"The run could not be launched: {exc}")


def _coverage(data: dict, summary: dict) -> None:
    coverage = summary["coverage"]
    counts = coverage["status_counts"]
    cols = st.columns(4)
    for col, label, value in zip(cols, ["Requested", "Completed", "Failed", "Cancelled"],
                                 [coverage["requested"], coverage["completed"], counts["failed"], counts["cancelled"]]):
        col.metric(label, f"{value:,}")
    total = sum(counts.values())
    check = f"{coverage['requested']} requested = " + " + ".join(f"{counts[s]} {s}" for s in STATUS_ORDER)
    if total == coverage["requested"]:
        st.caption(f"✓ Accounting check · {check}")
    else:
        st.error(f"Accounting invariant failed: {check}. Recorded total = {total}.")
    st.caption(f"Run status: {data['run']['status']} · Started {_date(data['run']['created_at'])} · {data['run']['config'].mode.value} mode")


def _inspect_user(data: dict, key: str) -> None:
    users = sorted({u.user_id: u for u in data["users"]}.values(), key=lambda u: u.user_id)
    if not users:
        st.info("No user records yet.")
        return
    selected = st.selectbox("Inspect a synthetic user", [u.user_id for u in users], key=f"{key}_user")
    user = next(u for u in users if u.user_id == selected)
    st.write(f"**{user.segment}** · {user.status.value} · {user.attempts} attempt(s)")
    if user.failure_reason:
        st.error(user.failure_reason)
    with st.expander("Persona and its assumptions"):
        st.json(user.profile)
        st.write("**Sourced facts**")
        st.write(user.sourced_facts or "No sourced facts supplied.")
        st.write("**Authored assumptions**")
        st.write(user.authored_assumptions or "No authored assumptions supplied.")
    results = [r for r in data["task_results"] if r.user_id == selected]
    if not results:
        st.caption("No task results recorded. No visit or task outcome is implied.")
    for result in results:
        with st.expander(f"{result.task_id} · {result.outcome.value} · {len(result.steps)} recorded steps"):
            st.write(result.reason)
            for step in result.steps:
                st.markdown(f"**Step {step.step} · {step.action}**")
                st.caption(step.url)
                if step.target:
                    st.write(f"Target: {step.target}")
                if step.value:
                    st.code(step.value, language=None)
                if step.agent_reason:
                    st.write(step.agent_reason)
                st.text(step.observation)
                if step.screenshot_path:
                    path = (ROOT / step.screenshot_path).resolve()
                    if path.is_relative_to(ROOT / "data/traces") and path.is_file():
                        st.image(str(path), caption=f"{selected} · {result.task_id} · step {step.step}", use_container_width=True)
                    else:
                        st.caption("Screenshot path was recorded; image is unavailable on this machine.")
                st.divider()
    evaluation = next((e for e in data["evaluations"] if e.user_id == selected), None)
    if evaluation:
        st.write("**Synthetic evaluation**")
        st.dataframe([{"Dimension": RATING_LABELS[dimension.value],
                       "Rating": rating.score if rating.score is not None else "not_assessable",
                       "Reason if not assessable": rating.not_assessable_reason or ""}
                      for dimension, rating in evaluation.ratings.items()], hide_index=True, use_container_width=True)
        st.write(evaluation.rating_reasons)
        for label, items in (("Strengths", evaluation.strengths), ("Suggestions", evaluation.suggestions)):
            if items:
                st.write(f"**{label}**")
                for item in items:
                    st.write(f"• {item}")
        for problem in evaluation.problems:
            st.write(f"**{problem.severity} · {problem.task_id or 'overall'}:** {problem.text}")
        if evaluation.pricing_feedback:
            st.write(f"**Pricing feedback:** {evaluation.pricing_feedback}")
    else:
        st.caption("No validated evaluation is saved for this user.")


def _progress_contents(run_id: str) -> None:
    data = _snapshot(run_id)
    if data is None:
        st.error("Run not found.")
        return
    summary = _summary(data)
    _banner(data["run"], summary["coverage"]["interim"])
    _coverage(data, summary)
    if not summary["coverage"]["settled"]:
        st.caption("This view refreshes every 2 seconds. Cancellation allows users already in flight to finish.")
        if data["run"]["cancel_requested"]:
            st.info("Cancellation requested. Waiting for in-flight users to finish.")
        elif st.button("Cancel remaining users", key=f"cancel_{run_id}"):
            engine_client.cancel_run(run_id)
            st.rerun()
    elif not summary["coverage"]["completed"]:
        st.warning("No user completed. Inspect failure reasons below; no aggregate product ratings are available.")
    st.dataframe([{"User ID": u.user_id, "Segment": u.segment, "Status": u.status.value,
                   "Attempts": u.attempts, "Failure reason": u.failure_reason or ""} for u in data["users"]],
                 hide_index=True, use_container_width=True)
    _inspect_user(data, f"progress_{run_id}")


def _ratings(summary: dict) -> None:
    if summary["individual_mode"]:
        st.info("Individual feedback mode — one completed user or one requested user. Shares and aggregate distributions are not shown.")
    rows = []
    for dimension, rating in summary["ratings"].items():
        row = {"Dimension": RATING_LABELS[dimension], "Mean / 5": round(rating["mean"], 2) if rating["mean"] is not None else None,
               "Eligible ratings": rating["eligible"], "Not assessable": rating["not_assessable"], "Missing": rating.get("missing", 0)}
        if not summary["individual_mode"]:
            row.update({f"Score {score}": rating["counts"].get(score, rating["counts"].get(str(score), 0)) for score in range(1, 6)})
        rows.append(row)
    st.dataframe(rows, hide_index=True, use_container_width=True)
    st.caption("Only completed users enter metrics. Missing and not-assessable ratings are excluded from means and eligible denominators. Anchors: 1 very low · 2 low · 3 mixed · 4 high · 5 very high.")


def _signals(summary: dict) -> None:
    if summary["individual_mode"]:
        st.caption("Use the individual's ratings and reasons below. A single synthetic profile is not a market share.")
        return
    left, right = st.columns(2)
    left.metric("Positive synthetic appeal rating", _share(summary["appeal_signal"]))
    right.metric("Positive synthetic intention-to-use rating", _share(summary["adoption_interest_signal"]))
    st.caption("Positive = score 4 or 5. These are synthetic ratings, not conversion, predicted demand or real market research.")
    rows = []
    for name, segment in summary["segments"].items():
        rows.append({"Segment": name, "Completed": segment["completed"],
                     "Positive appeal": _share(segment["appeal_signal"]),
                     "Positive intention to use": _share(segment["adoption_interest_signal"])})
    st.dataframe(rows, hide_index=True, use_container_width=True)
    st.caption("Segment signals are unweighted. Small denominators are visible; differences are exploratory.")


def _report(data: dict) -> None:
    config, run_id = data["run"]["config"], data["run"]["run_id"]
    summary = _summary(data)
    _banner(data["run"], summary["coverage"]["interim"])
    st.subheader("Test coverage")
    _coverage(data, summary)
    st.write(f"**Objective:** {config.objective}")
    if config.mode == RunMode.CONCEPT:
        st.info("Concept evaluation: no product interaction took place. Ease of use is not assessable.")
    usage = data["usage"]
    if usage:
        cost = None if any(u.cost_hkd is None for u in usage) else sum(u.cost_hkd for u in usage)
        st.caption(f"Recorded usage across all attempts: {sum(u.input_tokens for u in usage):,} input + {sum(u.output_tokens for u in usage):,} output tokens · " + ("cost unknown" if cost is None else f"HK${cost:.4f}"))
    st.subheader("Product experience")
    task_rows = []
    for task_id, task in summary["tasks"].items():
        row = {"Task": task_id, "Instruction": task["instruction"], **task["outcome_counts"]}
        if not summary["individual_mode"]:
            row["Completion"] = _share(task["completion"], "with a task result")
        task_rows.append(row)
    if task_rows:
        st.dataframe(task_rows, hide_index=True, use_container_width=True)
    else:
        st.caption("No tasks configured.")
    st.caption("Task metrics include completed users with a recorded result. A failed user is excluded from metrics; their saved traces remain available as diagnostic evidence.")
    st.subheader("Rating dashboard")
    _ratings(summary)
    st.subheader("Market attractiveness")
    _signals(summary)
    st.subheader("Improvement backlog")
    completed_ids = {u.user_id for u in data["users"] if u.status == JobStatus.COMPLETED}
    if completed_ids and st.button("Build / refresh evidence themes", key=f"build_findings_{run_id}", disabled=LOCAL_AI_PAUSED):
        try:
            with st.spinner("Grouping reported problems; counts are computed in code…"):
                findings = build_findings(run_id, config,
                                          [r for r in data["task_results"] if r.user_id in completed_ids],
                                          [e for e in data["evaluations"] if e.user_id in completed_ids])
                with closing(db.connect()) as conn:
                    db.replace_findings(conn, run_id, findings)
                method = getattr(findings, "method", "Theme grouping method unavailable")
                st.session_state[f"finding_method_{run_id}"] = method
                data["findings"] = list(findings)
                try:
                    _save_report_metadata(run_id, method)
                    data["run"]["findings_method"] = method
                except OSError:
                    st.warning("Evidence themes were saved, but their grouping method could not be recorded for later sessions.")
        except Exception as exc:
            st.error(f"Evidence themes could not be refreshed: {exc}")
    method = data["run"].get("findings_method") or st.session_state.get(f"finding_method_{run_id}")
    if method:
        st.caption(f"Theme method: {method}. The model labels themes only; supporting counts and denominators are computed in code.")
    elif data["findings"]:
        st.caption("Theme grouping method was not recorded for this older report.")
    if not data["findings"]:
        st.caption("No findings are saved. Individual problems and traces remain available below.")
    for finding in data["findings"]:
        support = len(set(finding.supporting_user_ids))
        measure = f"{support} supporting user(s)" if summary["individual_mode"] else _share({"numerator": support, "denominator": finding.eligible_denominator}, "eligible users")
        with st.expander(f"{finding.severity.upper()} · {finding.theme} · {measure}"):
            st.write(f"Task: {finding.task_id or 'overall evaluation'}")
            st.write("**Supporting users:** " + ", ".join(finding.supporting_user_ids))
            st.write("**Evidence references**")
            for ref in finding.evidence_refs:
                st.code(ref, language=None)
            st.caption("Select a supporting user in the evidence inspector below to view their recorded steps and screenshots.")
    st.subheader("Next validation")
    if data["findings"]:
        for finding in data["findings"][:5]:
            st.write(f"**Suggestion · Validate with real users:** Ask people in the target audience to attempt {finding.task_id or 'the relevant product flow'} and observe whether “{finding.theme}” occurs.")
    else:
        st.write("**Suggestion · Validate with real users:** Observe a small set of target users attempting the same tasks, then compare their difficulties with these recorded synthetic attempts.")
    with st.expander("Evidence inspector", expanded=summary["individual_mode"] or not completed_ids):
        _inspect_user(data, f"report_{run_id}")
    st.divider()
    if data["run"]["status"] == JobStatus.COMPLETED.value and not data["run"]["is_saved_example"]:
        if st.button("Mark as saved example", key=f"save_example_{run_id}"):
            with closing(db.connect()) as conn:
                db.set_saved_example(conn, run_id)
            st.rerun()
    st.write("**Export this report**")
    try:
        csv_bytes = export_csv(run_id, config, data["users"], data["task_results"], data["evaluations"])
        st.download_button("Download CSV", csv_bytes, file_name=f"{run_id}.csv", mime="text/csv", key=f"csv_{run_id}")
        pdf_run = dict(data["run"])
        if method:
            pdf_run["findings_method"] = method
        pdf_bytes = export_pdf(run_id, pdf_run, data["users"], data["task_results"], data["evaluations"], data["findings"])
        st.download_button("Download PDF", pdf_bytes, file_name=f"{run_id}.pdf", mime="application/pdf", key=f"pdf_{run_id}")
    except Exception as exc:
        st.error(f"Export could not be generated: {exc}")


def _runs_page(runs: list[dict]) -> None:
    st.markdown('<div class="syn-eyebrow">OBSERVE & LEARN</div>', unsafe_allow_html=True)
    st.title("Your test runs")
    if not runs:
        st.info("No tests yet. Set up a one-user test to verify the complete flow.")
        if st.button("Create a test", type="primary"):
            _navigate("New test")
        return
    ids = [run["run_id"] for run in runs]
    if st.session_state.get("active_run") not in ids:
        st.session_state["active_run"] = ids[0]
    labels = {run["run_id"]: f"{'[Saved] ' if run['is_saved_example'] else ''}{run['config'].product_name} · {run['config'].product_version} · {_date(run['created_at'])} · {run['run_id']}" for run in runs}
    run_id = st.selectbox("Select a run", ids, format_func=lambda x: labels[x], key="active_run")
    data = _snapshot(run_id)
    if data is None:
        st.error("Run not found.")
        return
    detail_view = st.radio("Run view", ["Progress", "Report"], horizontal=True, key="run_detail_view")
    if detail_view == "Progress":
        summary = _summary(data)
        if hasattr(st, "fragment"):
            @st.fragment(run_every="2s" if not summary["coverage"]["settled"] else None)
            def progress_fragment():
                _progress_contents(run_id)
            progress_fragment()
        else:
            _progress_contents(run_id)
            st.caption("Automatic refresh requires a newer Streamlit version.")
            if st.button("Refresh status"):
                st.rerun()
    else:
        _report(data)


def _rubric_signature(run: dict) -> str:
    path = ROOT / "data/logs" / f"{run['run_id']}.metadata.json"
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
        return metadata.get("evaluation_prompt_version", "unknown")
    except (FileNotFoundError, ValueError, OSError):
        return "unknown"


def _compare(runs: list[dict]) -> None:
    st.markdown('<div class="syn-eyebrow">COMPARE ITERATIONS</div>', unsafe_allow_html=True)
    st.title("Change in synthetic ratings under the same configuration")
    st.caption("Inspect the configuration differences before interpreting any change.")
    if len(runs) < 2:
        st.info("At least two runs are needed for a comparison.")
        return
    ids = [run["run_id"] for run in runs]
    labels = {run["run_id"]: f"{'[Saved] ' if run['is_saved_example'] else ''}{run['config'].product_name} · {run['config'].product_version} · {run['run_id']}" for run in runs}
    left, right = st.columns(2)
    baseline_id = left.selectbox("Baseline run", ids, index=min(1, len(ids) - 1), format_func=lambda x: labels[x], key="compare_baseline")
    newer_id = right.selectbox("New run", ids, format_func=lambda x: labels[x], key="compare_new")
    if baseline_id == newer_id:
        st.info("Choose two different runs.")
        return
    baseline, newer = _snapshot(baseline_id), _snapshot(newer_id)
    if not baseline or not newer:
        st.error("A selected run is unavailable.")
        return
    a, b = baseline["run"]["config"], newer["run"]["config"]
    differences = []
    if a.audience.spec_version != b.audience.spec_version:
        differences.append(f"Audience spec version: {a.audience.spec_version} → {b.audience.spec_version}")
    if a.audience.model_dump() != b.audience.model_dump():
        differences.append("Audience segment weights, traits, facts or assumptions differ.")
    if [t.model_dump() for t in a.tasks] != [t.model_dump() for t in b.tasks]:
        differences.append("Tasks, success checks or step limits differ.")
    if a.mode != b.mode:
        differences.append(f"Evaluation mode: {a.mode.value} → {b.mode.value}")
    if a.seed != b.seed:
        differences.append(f"Persona seed: {a.seed} → {b.seed}")
    rubric_a, rubric_b = _rubric_signature(baseline["run"]), _rubric_signature(newer["run"])
    if rubric_a != rubric_b:
        differences.append(f"Evaluation rubric version: {rubric_a} → {rubric_b}")
    if "unknown" in (rubric_a, rubric_b):
        differences.append("Evaluation rubric metadata is unavailable for one or both runs; identical rubrics cannot be verified.")
    if differences:
        st.warning("Configuration differences limit direct comparison:\n\n" + "\n".join(f"- {difference}" for difference in differences))
    else:
        st.success("Audience, tasks, persona seed, mode and recorded evaluation rubric match.")
    summaries = [_summary(baseline), _summary(newer)]
    individual = any(s["individual_mode"] for s in summaries)
    if individual:
        st.info("Individual feedback mode applies to at least one run. Comparison shares are suppressed.")
    for col, data, summary, label in zip(st.columns(2), [baseline, newer], summaries, ["Baseline", "New run"]):
        with col:
            st.subheader(f"{label} · {data['run']['config'].product_version}")
            _banner(data["run"], summary["coverage"]["interim"])
            _coverage(data, summary)
            st.dataframe([{"Dimension": RATING_LABELS[d], "Mean / 5": round(r["mean"], 2) if r["mean"] is not None else None,
                           "Eligible n": r["eligible"], "Not assessable": r["not_assessable"]}
                          for d, r in summary["ratings"].items()], hide_index=True, use_container_width=True)
            if not individual:
                st.write("**Positive synthetic appeal rating:** " + _share(summary["appeal_signal"]))
                st.write("**Positive synthetic intention-to-use rating:** " + _share(summary["adoption_interest_signal"]))
            st.dataframe([{"Task": task_id, "Completed": task["outcome_counts"].get("completed", 0),
                           "Eligible n": task["eligible"],
                           **({"Completion": _share(task["completion"], "with a task result")} if not individual else {})}
                          for task_id, task in summary["tasks"].items()], hide_index=True, use_container_width=True)
    st.subheader("Finding comparison")
    if not baseline["findings"] or not newer["findings"]:
        st.info("Build evidence themes in each report to compare findings. An absent saved finding does not establish that a problem was resolved.")
    else:
        a_findings = {(f.task_id, f.theme.casefold().strip()): f for f in baseline["findings"]}
        b_findings = {(f.task_id, f.theme.casefold().strip()): f for f in newer["findings"]}
        rows = []
        for finding_key in sorted(a_findings.keys() | b_findings.keys(), key=lambda x: (x[0] or "", x[1])):
            old, current = a_findings.get(finding_key), b_findings.get(finding_key)
            state = "Persisting" if old and current else "New" if current else "Resolved in these synthetic results"
            f = current or old
            rows.append({"Finding": f.theme, "Task": f.task_id or "overall", "State": state,
                         "Baseline support": f"{len(old.supporting_user_ids)} of {old.eligible_denominator}" if old else "not reported",
                         "New support": f"{len(current.supporting_user_ids)} of {current.eligible_denominator}" if current else "not reported"})
        st.dataframe(rows, hide_index=True, use_container_width=True)
        st.caption("Findings match by task and exact normalised theme label. “Resolved” means absent from the new saved synthetic findings, not proof that real users no longer experience it.")


def main() -> None:
    if "pending_navigation" in st.session_state:
        st.session_state["workspace"] = st.session_state.pop("pending_navigation")
    with st.sidebar:
        st.markdown("## ◈ Synthetix")
        st.caption("Product exploration, with evidence.")
        page = st.radio("Workspace", ["New test", "Runs", "Compare"], key="workspace", label_visibility="collapsed")
        st.divider()
        if FAKE_MODE:
            st.error("FAKE ENGINE · Development only")
        else:
            provider_host = urlsplit(os.environ.get("LLM_BASE_URL", "")).hostname
            if LOCAL_AI_PAUSED:
                st.caption("Local AI paused · recorded results available")
            else:
                st.caption("Real engine · local model" if provider_host in {"localhost", "127.0.0.1", "::1"} else "Real engine · configured model")
                st.caption(f"Model: {os.environ.get('LLM_MODEL', 'not configured')}")
        st.caption("Synthetic profiles are authored simulations. Validate important findings with real people.")
        st.caption("Track 4 · SDG 12 · Hackathon prototype")
    st.markdown(f'<div class="syn-disclaimer">{DISCLAIMER}</div>', unsafe_allow_html=True)
    runs = _all_runs()
    if page == "New test":
        _new_test()
    elif page == "Runs":
        _runs_page(runs)
    else:
        _compare(runs)
    st.divider()
    st.caption(DISCLAIMER)


if __name__ == "__main__":
    main()
