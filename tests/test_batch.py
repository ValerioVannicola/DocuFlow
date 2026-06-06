from __future__ import annotations

import csv
import io
import json
from unittest.mock import AsyncMock

from docflow.batch import BatchReport, process_batch
from docflow.extraction.models import ExtractedField, ExtractionResult


def _make_result(
    doc_id: str, supplier: str, total: float, conf: float = 0.8,
    needs_review: bool = False, review_reasons: list | None = None,
) -> ExtractionResult:
    return ExtractionResult(
        document_id=doc_id,
        schema_name="Invoice",
        data={"supplier_name": supplier, "total": total},
        fields={
            "supplier_name": ExtractedField(value=supplier, confidence=conf),
            "total": ExtractedField(value=total, confidence=conf),
        },
        confidence=conf,
        needs_review=needs_review,
        review_reasons=review_reasons or [],
    )


class TestProcessBatch:
    async def test_all_succeed(self):
        mock_pipeline = AsyncMock()
        mock_pipeline.run = AsyncMock(side_effect=[
            _make_result("d1", "Acme", 100.0),
            _make_result("d2", "Beta", 200.0),
            _make_result("d3", "Gamma", 300.0),
        ])

        report = await process_batch(
            files=["a.pdf", "b.pdf", "c.pdf"],
            schema=type("Invoice", (), {"__name__": "Invoice"}),
            pipeline=mock_pipeline,
        )

        assert report.total == 3
        assert report.succeeded == 3
        assert report.failed == 0
        assert report.average_confidence > 0
        assert len(report.documents) == 3
        assert len(report.results) == 3

    async def test_partial_failure(self):
        mock_pipeline = AsyncMock()
        mock_pipeline.run = AsyncMock(side_effect=[
            _make_result("d1", "Acme", 100.0),
            RuntimeError("extraction failed"),
            _make_result("d3", "Gamma", 300.0),
        ])

        report = await process_batch(
            files=["a.pdf", "b.pdf", "c.pdf"],
            schema=type("Invoice", (), {"__name__": "Invoice"}),
            pipeline=mock_pipeline,
        )

        assert report.total == 3
        assert report.succeeded == 2
        assert report.failed == 1
        assert len(report.results) == 2

        failed = [d for d in report.documents if not d.success]
        assert len(failed) == 1
        assert "extraction failed" in failed[0].error

    async def test_review_tracking(self):
        mock_pipeline = AsyncMock()
        mock_pipeline.run = AsyncMock(side_effect=[
            _make_result("d1", "Acme", 100.0, needs_review=True,
                         review_reasons=["Low confidence"]),
            _make_result("d2", "Beta", 200.0, needs_review=True,
                         review_reasons=["Low confidence", "Missing field"]),
            _make_result("d3", "Gamma", 300.0),
        ])

        report = await process_batch(
            files=["a.pdf", "b.pdf", "c.pdf"],
            schema=type("Invoice", (), {"__name__": "Invoice"}),
            pipeline=mock_pipeline,
        )

        assert report.needs_review == 2
        assert report.approved == 1
        assert "Low confidence" in report.top_review_reasons
        assert report.top_review_reasons["Low confidence"] == 2

    async def test_field_names_collected(self):
        mock_pipeline = AsyncMock()
        mock_pipeline.run = AsyncMock(return_value=_make_result("d1", "Acme", 100.0))

        report = await process_batch(
            files=["a.pdf"],
            schema=type("Invoice", (), {"__name__": "Invoice"}),
            pipeline=mock_pipeline,
        )

        assert "supplier_name" in report.field_names
        assert "total" in report.field_names

    async def test_file_name_extraction(self):
        mock_pipeline = AsyncMock()
        mock_pipeline.run = AsyncMock(return_value=_make_result("d1", "Acme", 100.0))

        report = await process_batch(
            files=["C:/docs/invoices/invoice_2024.pdf"],
            schema=type("Invoice", (), {"__name__": "Invoice"}),
            pipeline=mock_pipeline,
        )

        assert report.documents[0].file_name == "invoice_2024.pdf"

    async def test_all_fail(self):
        mock_pipeline = AsyncMock()
        mock_pipeline.run = AsyncMock(side_effect=RuntimeError("broken"))

        report = await process_batch(
            files=["a.pdf", "b.pdf"],
            schema=type("Invoice", (), {"__name__": "Invoice"}),
            pipeline=mock_pipeline,
        )

        assert report.total == 2
        assert report.succeeded == 0
        assert report.failed == 2
        assert report.average_confidence == 0.0


class TestBatchReportCSV:
    async def test_to_csv(self):
        mock_pipeline = AsyncMock()
        mock_pipeline.run = AsyncMock(side_effect=[
            _make_result("d1", "Acme", 100.0, conf=0.9),
            _make_result("d2", "Beta", 200.0, conf=0.7),
        ])

        report = await process_batch(
            files=["a.pdf", "b.pdf"],
            schema=type("Invoice", (), {"__name__": "Invoice"}),
            pipeline=mock_pipeline,
        )

        csv_output = report.to_csv()
        reader = csv.DictReader(io.StringIO(csv_output))
        rows = list(reader)

        assert len(rows) == 2
        assert rows[0]["supplier_name"] == "Acme"
        assert rows[0]["total"] == "100.0"
        assert rows[1]["supplier_name"] == "Beta"
        assert "confidence" in rows[0]
        assert "needs_review" in rows[0]

    async def test_csv_with_failure(self):
        mock_pipeline = AsyncMock()
        mock_pipeline.run = AsyncMock(side_effect=[
            _make_result("d1", "Acme", 100.0),
            RuntimeError("fail"),
        ])

        report = await process_batch(
            files=["a.pdf", "b.pdf"],
            schema=type("Invoice", (), {"__name__": "Invoice"}),
            pipeline=mock_pipeline,
        )

        csv_output = report.to_csv()
        reader = csv.DictReader(io.StringIO(csv_output))
        rows = list(reader)
        assert len(rows) == 2
        assert rows[1]["success"] == "False"

    async def test_empty_batch(self):
        report = BatchReport()
        assert report.to_csv() == ""


class TestBatchReportJSON:
    async def test_serializes(self):
        mock_pipeline = AsyncMock()
        mock_pipeline.run = AsyncMock(return_value=_make_result("d1", "Acme", 100.0))

        report = await process_batch(
            files=["a.pdf"],
            schema=type("Invoice", (), {"__name__": "Invoice"}),
            pipeline=mock_pipeline,
        )

        output = json.loads(report.model_dump_json())
        assert output["total"] == 1
        assert output["succeeded"] == 1
        assert len(output["documents"]) == 1
        assert output["documents"][0]["data"]["supplier_name"] == "Acme"
