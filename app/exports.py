"""Downloadable report exports built from persisted records, never invented results."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import os
from pathlib import Path

from fpdf import FPDF

from app.aggregate import aggregate
from contracts.models import JobStatus, RatingDimension, TaskOutcome

DISCLAIMER = "Synthetic simulation — not real user research"


def _text(value) -> str:
    return "".join(c for c in str(value) if c in "\n\t" or ord(c) >= 32)


def _share(signal: dict, noun="rated") -> str:
    n, denominator = signal["numerator"], signal["denominator"]
    return (f"{n / denominator:.0%} ({n} of {denominator} {noun})" if denominator
            else f"Not assessable (0 of 0 {noun})")


def _date(timestamp) -> str:
    if timestamp is None:
        return "date unavailable"
    return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).strftime("%Y-%m-%d UTC")


class _ReportPDF(FPDF):
    def __init__(self, run_id, labels):
        super().__init__()
        self.run_id = run_id
        self.labels = labels
        candidates = [os.environ.get("SYNTHETIX_PDF_FONT", ""),
                      "/Library/Fonts/Arial Unicode.ttf",
                      "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                      "C:/Windows/Fonts/arial.ttf"]
        font = next((p for p in candidates if p and Path(p).is_file()), None)
        self.unicode_font = bool(font)
        self.report_font = "Report" if font else "Helvetica"
        if font:
            self.add_font("Report", fname=font)
        self.set_margins(15, 25, 15)
        self.set_auto_page_break(True, margin=23)
        self.set_title(f"Synthetix - {run_id}")
        self.set_author("Synthetix")

    def safe(self, text):
        text = _text(text)
        if self.unicode_font:
            return text
        return text.replace("—", "-").replace("–", "-").encode("latin-1", "replace").decode("latin-1")

    def header(self):
        self.set_y(8)
        self.set_font(self.report_font, size=9)
        self.set_text_color(119, 61, 12)
        self.multi_cell(0, 5, self.safe(DISCLAIMER), new_x="LMARGIN", new_y="NEXT")
        if self.labels:
            self.set_font(self.report_font, size=8)
            self.multi_cell(0, 4, self.safe(" | ".join(self.labels)), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(223, 228, 235)
        self.line(15, 21, 195, 21)
        self.set_y(26)

    def footer(self):
        self.set_y(-18)
        self.set_font(self.report_font, size=7)
        self.set_text_color(87, 99, 116)
        self.multi_cell(0, 4, self.safe(
            f"Synthetix — synthetic simulation, not real user research — {self.run_id}"),
            new_x="LMARGIN", new_y="NEXT", align="C")
        self.cell(0, 4, f"{self.page_no()}", align="C")

    def paragraph(self, text, size=10):
        self.set_font(self.report_font, size=size)
        self.set_text_color(37, 49, 66)
        self.multi_cell(0, 5.6, self.safe(text), new_x="LMARGIN", new_y="NEXT")
        self.ln(1.5)

    def section(self, title):
        if self.get_y() > self.h - 50:
            self.add_page()
        self.ln(3)
        self.set_font(self.report_font, size=15)
        self.set_text_color(26, 65, 93)
        self.multi_cell(0, 8, self.safe(title), new_x="LMARGIN", new_y="NEXT")
        self.ln(1)


def export_pdf(run_id, run, users, task_results, evaluations, findings) -> bytes:
    """All report sections; every page carries the simulation notice and run footer."""
    config = run["config"]
    report = aggregate(config, users, task_results, evaluations)
    coverage = report["coverage"]
    labels = []
    if coverage["interim"]:
        labels.append("Interim")
    if run.get("is_saved_example"):
        labels.append(f"Saved example — recorded {_date(run.get('created_at'))}, not live")
    if config.product_name.startswith("[FAKE]"):
        labels.append("DEVELOPMENT FAKE DATA — never use in the demo")
    pdf = _ReportPDF(run_id, labels)
    pdf.add_page()
    pdf.paragraph("SYNTHETIX / PRODUCT TEST REPORT", 11)
    pdf.paragraph(f"{config.product_name} · {config.product_version}", 23)
    pdf.paragraph(f"Run {run_id} | Mode: {config.mode.value}")
    pdf.paragraph(f"Value proposition: {config.value_proposition}")
    pdf.paragraph(f"Objective: {config.objective}")
    pdf.paragraph("Synthetic results are early signals. Validate important findings with real users.")
    if config.mode.value == "concept":
        pdf.paragraph("Concept evaluation reviews supplied material. No product was operated; ease of use is not assessable.")
    else:
        pdf.paragraph("Interactive evaluation records attempted browser tasks. A task completes only when its coded success check passes.")
    for note in run.get("quality_notes", []):
        pdf.paragraph(f"Report quality note: {note}")
    user_map = {u.user_id: u for u in users if u.run_id == run_id}
    completed = {uid: u for uid, u in user_map.items() if u.status == JobStatus.COMPLETED}
    evals = {e.user_id: e for e in evaluations if e.user_id in completed and e.run_id == run_id}
    results = {(r.user_id, r.task_id): r for r in task_results
               if r.user_id in completed and r.run_id == run_id}
    individual = report["individual_mode"]
    pdf.section("Test coverage")
    counts = coverage["status_counts"]
    pdf.paragraph(f"Requested: {coverage['requested']}. Completed: {counts['completed']}. "
                  f"Failed: {counts['failed']}. Cancelled: {counts['cancelled']}. "
                  f"Queued: {counts['queued']}. Running: {counts['running']}.")
    pdf.paragraph("Accounting check: " + ("passed" if coverage["accounting_valid"] else "FAILED - user records do not match the request"))
    pdf.paragraph(f"Audience: {config.audience.description} (spec {config.audience.spec_version}).")
    if individual:
        pdf.paragraph("Individual feedback only: one requested or completed synthetic user; no population shares are shown.")
    pdf.section("Product experience")
    if not config.tasks:
        pdf.paragraph("No product tasks were configured.")
    for task in config.tasks:
        data = report["tasks"][task.task_id]
        pdf.paragraph(f"{task.task_id}: {task.instruction}", 11)
        pdf.paragraph(f"Success check: {task.success_check}", 9)
        if not individual:
            pdf.paragraph(f"Task completion: {_share(data['completion'], 'with a task result')}. "
                          + "; ".join(f"{outcome}: {count}" for outcome, count in data["outcome_counts"].items()))
        for (uid, tid), result in sorted(results.items()):
            if tid != task.task_id:
                continue
            if individual or result.outcome != TaskOutcome.COMPLETED:
                pdf.paragraph(f"Evidence {uid}:{tid} — {result.outcome.value}: {result.reason}", 9)
                key_steps = result.steps if len(result.steps) <= 4 else result.steps[:2] + result.steps[-2:]
                for step in key_steps:
                    pdf.paragraph(f"Step {step.step}: {step.action}; target: {step.target or 'none'}; "
                                  f"URL: {step.url}. {step.agent_reason or ''}", 8)
    pdf.section("Rating dashboard")
    if individual:
        for uid, evaluation in sorted(evals.items()):
            pdf.paragraph(f"Individual: {uid}", 11)
            for dimension in RatingDimension:
                rating = evaluation.ratings[dimension]
                value = f"{rating.score} of 5" if rating.score is not None else f"Not assessable: {rating.not_assessable_reason}"
                pdf.paragraph(f"{dimension.value.replace('_', ' ').title()}: {value}")
            pdf.paragraph(f"Rating reasons: {evaluation.rating_reasons}")
            if evaluation.strengths:
                pdf.paragraph("Strengths: " + "; ".join(evaluation.strengths))
            if evaluation.problems:
                pdf.paragraph("Problems: " + "; ".join(f"[{p.severity}] {p.text}" for p in evaluation.problems))
            if evaluation.suggestions:
                pdf.paragraph("Suggestions: " + "; ".join(evaluation.suggestions))
            if evaluation.pricing_feedback:
                pdf.paragraph("Pricing feedback (observed price): " + evaluation.pricing_feedback)
        if not evals:
            pdf.paragraph("No completed user's evaluation is available.")
    else:
        for dimension, data in report["ratings"].items():
            mean = f"{data['mean']:.2f} of 5" if data["mean"] is not None else "Not assessable"
            pdf.paragraph(f"{dimension.replace('_', ' ').title()}: mean {mean}; "
                          f"eligible {data['eligible']}; not assessable {data['not_assessable']}; missing {data['missing']}.")
            pdf.paragraph("Distribution (counts): " + "; ".join(f"{score}: {count}" for score, count in data["counts"].items()), 9)
    pdf.section("Market attractiveness")
    if individual:
        pdf.paragraph("Read the individual's appeal and intention-to-use ratings above. One simulated response does not establish a market pattern.")
    else:
        pdf.paragraph("Positive synthetic appeal rating (4 or 5): " + _share(report["appeal_signal"]))
        pdf.paragraph("Positive synthetic adoption-interest rating (4 or 5): " + _share(report["adoption_interest_signal"]))
        for name, segment in report["segments"].items():
            pdf.paragraph(f"{name} — {segment['completed']} completed; appeal {_share(segment['appeal_signal'])}; "
                          f"adoption interest {_share(segment['adoption_interest_signal'])}.", 9)
    pdf.paragraph("Segment results are unweighted synthetic signals; they do not measure conversion or predict demand.")
    pdf.section("Improvement backlog")
    method = getattr(findings, "method", None) or run.get("findings_method")
    if method:
        pdf.paragraph(method, 9)
    if not findings:
        pdf.paragraph("No grouped findings have been generated. Individual feedback and task evidence remain available.")
    for finding in findings:
        pdf.paragraph(f"[{finding.severity.upper()}] {finding.theme}", 11)
        supporters = len(set(finding.supporting_user_ids))
        if individual:
            pdf.paragraph(f"Supporting user IDs: {', '.join(finding.supporting_user_ids)}", 9)
        else:
            pdf.paragraph("Supporting share: " + _share({"numerator": supporters, "denominator": finding.eligible_denominator}, "eligible users"), 9)
        pdf.paragraph(f"Task: {finding.task_id or 'General feedback'}. Evidence: " + "; ".join(finding.evidence_refs), 9)
    pdf.section("Next validation")
    if findings:
        for finding in findings[:5]:
            pdf.paragraph(f"Suggestion — Validate with real users: observe people from the intended audience "
                          f"attempt {finding.task_id or 'a relevant product task'} and investigate '{finding.theme}'.")
    else:
        pdf.paragraph("Suggestion — Validate with real users: observe core tasks and ask participants to explain their decisions.")
    return bytes(pdf.output())


def export_csv(run_id, config, users, task_results, evaluations) -> bytes:
    """One raw row per unique user x configured task; no absent result is fabricated."""
    user_map = {u.user_id: u for u in users if u.run_id == run_id}
    results = {(r.user_id, r.task_id): r for r in task_results if r.run_id == run_id}
    evals = {e.user_id: e for e in evaluations if e.run_id == run_id}
    dimensions = [d.value for d in RatingDimension]
    fields = ["run_id", "user_id", "segment", "user_status", "task_id", "outcome", "reason",
              *dimensions, "problems"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for uid, user in sorted(user_map.items()):
        evaluation = evals.get(uid)
        for task in config.tasks:
            result = results.get((uid, task.task_id))
            row = {"run_id": run_id, "user_id": uid, "segment": user.segment,
                   "user_status": user.status.value, "task_id": task.task_id,
                   "outcome": result.outcome.value if result else "not_recorded",
                   "reason": result.reason if result else (user.failure_reason or "No task result recorded"),
                   "problems": "; ".join(f"[{p.severity}] {p.text}" for p in evaluation.problems) if evaluation else ""}
            for dimension in RatingDimension:
                rating = evaluation.ratings.get(dimension) if evaluation else None
                row[dimension.value] = (rating.score if rating.score is not None else "not_assessable") if rating else ""
            writer.writerow(row)
    return ("\ufeff" + stream.getvalue()).encode("utf-8")
