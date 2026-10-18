from __future__ import annotations

import csv
import io
import re

from app.aggregate import build_findings
from app.exports import _ReportPDF, export_csv, export_pdf
from contracts.models import JobStatus


def test_csv_one_row_per_unique_user_task_and_no_missing_fabrication(records):
    run_id, config, users, results, evaluations = records
    content = export_csv(run_id, config, users * 2, results * 2, evaluations * 2)
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    assert len(rows) == 12
    assert len({(r["user_id"], r["task_id"]) for r in rows}) == 12
    na_row = next(r for r in rows if r["user_id"] == users[2].user_id)
    assert na_row["appeal"] == "not_assessable"
    failed_row = next(r for r in rows if r["user_id"] == users[3].user_id)
    assert failed_row["outcome"] == "not_recorded" and failed_row["user_status"] == "failed"
    assert next(r for r in rows if r["user_id"] == users[0].user_id)["problems"] == "[blocker] Price hidden"


def test_pdf_serializes_report_and_multipage_evidence(records):
    run_id, config, users, results, evaluations = records
    findings = build_findings(run_id, config, results, evaluations[:3])
    run = {"config": config, "created_at": 1_792_186_200, "is_saved_example": True}
    content = export_pdf(run_id, run, users, results, evaluations, findings)
    assert content.startswith(b"%PDF-") and content.rstrip().endswith(b"%%EOF")
    assert len(re.findall(rb"/Type /Page\b", content)) >= 2
    assert b"/FontFile2" in content  # Unicode notice is preserved through font embedding


def test_individual_pdf_has_no_percentage_shares(records, monkeypatch):
    # Rendering succeeds with one complete user and arbitrary long user evidence.
    run_id, config, users, results, evaluations = records
    config = config.model_copy(update={"user_count": 1})
    evaluations[0].rating_reasons = "A detailed reason. " * 120
    rendered = []
    original = _ReportPDF.paragraph
    def capture(self, text, size=10):
        rendered.append(text)
        return original(self, text, size)
    monkeypatch.setattr(_ReportPDF, "paragraph", capture)
    content = export_pdf(run_id, {"config": config, "quality_notes": ["Recorded model feedback needs review."]},
                         users[:1], results, evaluations[:1], [])
    assert content.startswith(b"%PDF-")
    assert not any("%" in text for text in rendered)
    assert any("Individual feedback only" in text for text in rendered)
    assert "Report quality note: Recorded model feedback needs review." in rendered


def test_pdf_last_duplicate_status_excludes_noncompleted_evaluation(records, monkeypatch):
    run_id, config, users, results, evaluations = records
    replacement = users[0].model_copy(update={"status": JobStatus.FAILED})
    evaluations[0].rating_reasons = "SHOULD_NOT_APPEAR"
    config = config.model_copy(update={"user_count": 1})
    rendered = []
    original = _ReportPDF.paragraph
    def capture(self, text, size=10):
        rendered.append(text)
        return original(self, text, size)
    monkeypatch.setattr(_ReportPDF, "paragraph", capture)
    export_pdf(run_id, {"config": config}, [users[0], replacement], results, evaluations, [])
    assert not any("SHOULD_NOT_APPEAR" in text for text in rendered)
