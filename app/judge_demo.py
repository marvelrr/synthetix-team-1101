"""Cloud judging entry point: streamlit run app/judge_demo.py.

Recorded proof is public. Optional paid live reviews require server-side secrets.
Visitor material/results stay in that Streamlit session and never enter SQLite.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()
os.environ["SYNTHETIX_LOCAL_INFERENCE_ALLOWED"] = "0"

import streamlit as st

from app.aggregate import aggregate
from app.judge_support import (MAX_AUDIENCE_CHARS, MAX_TEXT_CHARS,
                               SESSION_COOLDOWN_SECONDS, LiveLimiter,
                               access_allowed, concern_topics, config_for_review,
                               configure_remote, parse_bundle, rating_comparisons,
                               remote_settings_valid, run_reviews)
from contracts.models import JobStatus, RatingDimension

RECORDED_PATH = ROOT / "docs" / "site" / "assets" / "refillhk-five-persona.json"


def server_settings() -> dict:
    keys = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
            "LLM_PRICE_IN_HKD_PER_1M", "LLM_PRICE_OUT_HKD_PER_1M",
            "SYNTHETIX_JUDGE_LIVE_ENABLED", "SYNTHETIX_JUDGE_ACCESS_CODE",
            "SYNTHETIX_JUDGE_DAILY_PROFILES")
    settings = {}
    for key in keys:
        try:
            value = st.secrets.get(key, os.environ.get(key, ""))
        except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
            value = os.environ.get(key, "")
        settings[key] = str(value)
    return settings


@st.cache_resource
def limiter(profile_allowance: int) -> LiveLimiter:
    return LiveLimiter(profile_allowance)


def safe_text(value) -> None:
    # st.text never treats model/user text as HTML, Markdown links, or instructions.
    st.text(str(value))


def display_report(bundle: dict) -> None:
    config, users, tasks, evaluations = parse_bundle(bundle)
    metrics = aggregate(config, users, tasks, evaluations)
    completed_ids = {user.user_id for user in users if user.status == JobStatus.COMPLETED}
    evaluations = [evaluation for evaluation in evaluations if evaluation.user_id in completed_ids]
    provenance = bundle.get("provenance", {})
    if provenance.get("kind") != "live-session":
        st.info("Recorded example — generated " + str(provenance.get("recorded_at", "at the date in its provenance")) + ". Open the live tab to submit new copy.")
    coverage = metrics["coverage"]
    if coverage["interim"]:
        st.warning("Interim results — the run has not settled.")
    st.subheader("Your report")
    cols = st.columns(4)
    for col, label, value in zip(cols, ("Requested", "Completed", "Failed", "Cancelled"),
                                 (coverage["requested"], coverage["completed"], coverage["failed"], coverage["cancelled"])):
        col.metric(label, value)
    st.caption("Concept review of supplied copy • no browser task attempts • authored synthetic profiles")
    st.caption("Model: " + str(provenance.get("model", "see provenance")))

    with st.expander("See the exact product copy reviewed"):
        safe_text(config.concept_material)
        st.caption("Intended audience")
        safe_text(config.audience.description)

    st.markdown("### Compare the perspectives")
    st.dataframe(rating_comparisons(evaluations), hide_index=True, width="stretch")
    if len(evaluations) > 1:
        cols = st.columns(2)
        for col, key, title in ((cols[0], "appeal_signal", "Positive synthetic appeal rating"),
                                (cols[1], "adoption_interest_signal", "Positive synthetic intention rating")):
            signal = metrics[key]
            n, d = signal["numerator"], signal["denominator"]
            col.metric(title, f"{n} of {d} rated")
            if d:
                col.caption(f"{100*n/d:.0f}% ({n} of {d} eligible ratings were 4 or 5)")
    st.caption("Ratings use 1–5 anchors: very low, low, mixed, high, very high. Missing and not-assessable ratings are excluded. Ease of use is unassessed because no product task was attempted.")

    st.markdown("### Concerns, with supporting evidence")
    st.caption("Code groups the actual problem text using a fixed keyword index. A problem may appear under several topics. Counts identify distinct completed profiles, not real customers.")
    topics = concern_topics(evaluations)
    if not topics:
        st.write("No problems were recorded by the completed profiles.")
    for topic in topics:
        n, d = len(topic["supporting_user_ids"]), topic["denominator"]
        with st.expander(f"{topic['topic']} — {n} of {d} completed profiles", expanded=n > 1):
            for evidence in topic["evidence"]:
                st.caption(f"{evidence['user_id']} • {evidence['severity']}")
                safe_text(evidence["text"])

    st.markdown("### Inspect every independent review")
    by_id = {evaluation.user_id: evaluation for evaluation in evaluations}
    for user in users:
        with st.expander(f"{user.segment} · {user.status.value}"):
            safe_text(user.user_id)
            st.write("**Authored profile**")
            st.json(user.profile, expanded=True)
            for assumption in user.authored_assumptions:
                st.caption("Authored assumption: " + assumption)
            evaluation = by_id.get(user.user_id)
            if evaluation is None:
                st.warning(user.failure_reason or "No valid evaluation was saved for this profile.")
                continue
            rows = []
            for dimension in RatingDimension:
                rating = evaluation.ratings[dimension]
                rows.append({"Dimension": dimension.value.replace("_", " ").title(),
                             "Rating": str(rating.score) + "/5" if rating.score is not None else "Not assessable",
                             "Reason if not assessable": rating.not_assessable_reason or ""})
            st.dataframe(rows, hide_index=True, width="stretch")
            safe_text(evaluation.rating_reasons)
            for heading, lines in (("Strengths", evaluation.strengths),
                                   ("Suggestions to investigate", evaluation.suggestions)):
                st.write("**" + heading + "**")
                for line in lines:
                    safe_text("• " + line)
            st.write("**Problems**")
            for problem in evaluation.problems:
                safe_text(f"{problem.severity}: {problem.text}")
            if evaluation.pricing_feedback:
                st.write("**Pricing feedback**")
                safe_text(evaluation.pricing_feedback)

    usage = bundle.get("usage", {})
    if isinstance(usage, list):
        costs = [item.get("cost_hkd") for item in usage]
        usage = {"llm_calls": sum(item.get("llm_calls", 0) for item in usage),
                 "input_tokens": sum(item.get("input_tokens", 0) for item in usage),
                 "output_tokens": sum(item.get("output_tokens", 0) for item in usage),
                 "cost_hkd": None if any(cost is None for cost in costs) else sum(costs)}
    with st.expander("Usage and provenance"):
        cost = usage.get("cost_hkd")
        st.write("Cost: unknown" if cost is None else f"Measured token cost: HK${cost:.4f}")
        st.write({key: usage.get(key) for key in ("llm_calls", "input_tokens", "output_tokens")})
        st.json(provenance)
        st.caption("These are synthetic viewpoints for early feedback. Their agreement does not establish real market demand or representativeness.")
    st.download_button("Download this report (JSON)", json.dumps(bundle, ensure_ascii=False, indent=2),
                       file_name="synthetix-concept-report.json", mime="application/json",
                       key="download-" + users[0].run_id)


def main() -> None:
    st.set_page_config(page_title="Synthetix — try the prototype", page_icon="◈", layout="centered")
    st.title("Synthetix")
    st.markdown("### Several AI perspectives. One clearer product message.")
    st.write("Review marketing or product copy through contrasting customer priorities, then inspect the evidence behind every observation.")
    st.caption("Synthetic simulation • AI-authored viewpoints • review suggestions with real customers")
    try:
        bundle = json.loads(RECORDED_PATH.read_text(encoding="utf-8"))
        config, _, _, _ = parse_bundle(bundle)
    except Exception:
        st.error("The recorded demonstration is unavailable. Please use the repository's saved reports.")
        st.link_button("Open repository", "https://github.com/marvelrr/synthetix-team-1101")
        return
    recorded_tab, live_tab = st.tabs(["Explore the RefillHK demonstration", "Review your own copy"])
    with recorded_tab:
        st.write("RefillHK is an invented Hong Kong refill business used as a repeatable demonstration input. The profiles and their feedback below were actually generated; no visits or customer responses are implied.")
        display_report(bundle)
    with live_tab:
        settings = server_settings()
        try:
            enabled = (settings.get("SYNTHETIX_JUDGE_LIVE_ENABLED") == "1"
                       and remote_settings_valid(settings)
                       and bool(settings.get("SYNTHETIX_JUDGE_ACCESS_CODE")))
        except (TypeError, ValueError):
            enabled = False
        if not enabled:
            st.info("New AI reviews are not enabled on this deployment. The recorded five-profile demonstration remains fully inspectable in the first tab.")
            return
        st.write("Paste non-sensitive marketing copy. Five authored priorities are available: see the recorded profiles before running. Each selected profile receives the same copy independently.")
        st.caption("Your submitted text is sent to the configured AI provider. It is held in this browser session's server memory and is not added to a shared database. Provider processing policies still apply.")
        st.session_state.setdefault("judge_copy", "")
        st.session_state.setdefault("judge_audience", config.audience.description)
        if st.button("Load the RefillHK example into the form"):
            st.session_state["judge_copy"] = config.concept_material or ""
            st.session_state["judge_audience"] = config.audience.description
        with st.form("new-review"):
            material = st.text_area("Product or marketing copy", key="judge_copy",
                                    max_chars=MAX_TEXT_CHARS, height=220)
            audience = st.text_area("Intended audience", key="judge_audience",
                                    max_chars=MAX_AUDIENCE_CHARS, height=90)
            count = st.selectbox("Number of independent profiles", [3, 5], index=1)
            code = st.text_input("Judging access code", type="password", autocomplete="off")
            consent = st.checkbox("I have permission to submit this non-sensitive text to the AI provider.")
            submit = st.form_submit_button("Generate independent reviews", type="primary")
        if submit:
            if not consent:
                st.error("Confirm permission before submitting text.")
            elif not access_allowed(settings["SYNTHETIX_JUDGE_ACCESS_CODE"], code):
                st.error("The judging access code was not accepted.")
            elif time.monotonic() - st.session_state.get("judge_last_started", -1e9) < SESSION_COOLDOWN_SECONDS:
                st.warning("Please wait 90 seconds between review starts in this session.")
            else:
                try:
                    run_config = config_for_review(config, material, audience, count)
                    allowance = int(settings.get("SYNTHETIX_JUDGE_DAILY_PROFILES") or 5)
                    guard = limiter(max(1, min(allowance, 15)))
                except (ValueError, TypeError):
                    st.error("Use 20–8,000 characters of copy and 3–600 characters for the audience.")
                    return
                if not guard.acquire(count):
                    st.warning("The demo is busy or its daily AI allowance has been reached. Please explore the recorded report.")
                else:
                    st.session_state["judge_last_started"] = time.monotonic()
                    st.session_state.pop("judge_result", None)
                    progress = st.progress(0, text="Starting independent reviews…")
                    try:
                        configure_remote(settings)
                        def update(done, total, status):
                            progress.progress(done / total, text=f"{done} of {total} profiles settled · latest {status}")
                        st.session_state["judge_result"] = run_reviews(run_config, update)
                    except Exception:
                        st.error("The live review could not finish. No valid result has been substituted. Please use the recorded demonstration.")
                    finally:
                        guard.release()
        if "judge_result" in st.session_state:
            display_report(st.session_state["judge_result"])
            if st.button("Clear my session result"):
                del st.session_state["judge_result"]
                st.rerun()


if __name__ == "__main__":
    main()
