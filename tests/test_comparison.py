from __future__ import annotations

import json
from unittest.mock import AsyncMock

from docuflow.comparison import (
    ComparisonCell,
    ComparisonResult,
    _compute_difference,
    compare_documents,
)
from docuflow.documents.evidence import Evidence
from docuflow.extraction.models import ExtractedField, ExtractionResult


def _make_result(
    doc_id: str, supplier: str, total: float, conf: float = 0.8,
) -> ExtractionResult:
    return ExtractionResult(
        document_id=doc_id,
        schema_name="Invoice",
        data={"supplier_name": supplier, "total": total},
        fields={
            "supplier_name": ExtractedField(
                value=supplier, confidence=conf,
                evidence=[Evidence(
                    document_id=doc_id, page_number=0, text=supplier,
                )],
            ),
            "total": ExtractedField(
                value=total, confidence=conf,
                evidence=[Evidence(
                    document_id=doc_id, page_number=0, text=str(total),
                )],
            ),
        },
        confidence=conf,
    )


class TestComputeDifference:
    def test_all_agree(self):
        cells = [
            ComparisonCell(document_id="d1", file_name="a.pdf", value=100.0),
            ComparisonCell(document_id="d2", file_name="b.pdf", value=100.0),
            ComparisonCell(document_id="d3", file_name="c.pdf", value=100.0),
        ]
        diff = _compute_difference("total", cells)
        assert diff.all_agree is True
        assert len(diff.unique_values) == 1
        assert "All 3 documents agree" in diff.summary

    def test_disagreement(self):
        cells = [
            ComparisonCell(document_id="d1", file_name="a.pdf", value=100.0),
            ComparisonCell(document_id="d2", file_name="b.pdf", value=100.0),
            ComparisonCell(document_id="d3", file_name="c.pdf", value=200.0),
        ]
        diff = _compute_difference("total", cells)
        assert diff.all_agree is False
        assert len(diff.unique_values) == 2
        assert "2/3" in diff.summary

    def test_all_different(self):
        cells = [
            ComparisonCell(document_id="d1", file_name="a.pdf", value="A"),
            ComparisonCell(document_id="d2", file_name="b.pdf", value="B"),
            ComparisonCell(document_id="d3", file_name="c.pdf", value="C"),
        ]
        diff = _compute_difference("name", cells)
        assert diff.all_agree is False
        assert len(diff.unique_values) == 3

    def test_single_document(self):
        cells = [
            ComparisonCell(document_id="d1", file_name="a.pdf", value=100.0),
        ]
        diff = _compute_difference("total", cells)
        assert diff.all_agree is True
        assert "All 1 documents agree" in diff.summary


class TestCompareDocuments:
    async def test_compare_identical_documents(self):
        mock_pipeline = AsyncMock()
        mock_pipeline.run = AsyncMock(side_effect=[
            _make_result("d1", "Acme", 1000.0),
            _make_result("d2", "Acme", 1000.0),
        ])

        result = await compare_documents(
            files=["a.pdf", "b.pdf"],
            schema=type("Invoice", (), {"__name__": "Invoice"}),
            pipeline=mock_pipeline,
        )

        assert isinstance(result, ComparisonResult)
        assert result.schema_name == "Invoice"
        assert len(result.documents) == 2
        assert "supplier_name" in result.fields
        assert "total" in result.fields
        assert result.differences["supplier_name"].all_agree is True
        assert result.differences["total"].all_agree is True
        assert len(result.results) == 2

    async def test_compare_different_documents(self):
        mock_pipeline = AsyncMock()
        mock_pipeline.run = AsyncMock(side_effect=[
            _make_result("d1", "Acme", 1000.0),
            _make_result("d2", "Acme", 1000.0),
            _make_result("d3", "Beta Corp", 2000.0),
        ])

        result = await compare_documents(
            files=["a.pdf", "b.pdf", "c.pdf"],
            schema=type("Invoice", (), {"__name__": "Invoice"}),
            pipeline=mock_pipeline,
        )

        assert result.differences["supplier_name"].all_agree is False
        assert result.differences["total"].all_agree is False
        assert len(result.differences["supplier_name"].unique_values) == 2

    async def test_evidence_preserved_in_cells(self):
        mock_pipeline = AsyncMock()
        mock_pipeline.run = AsyncMock(return_value=_make_result("d1", "Acme", 500.0))

        result = await compare_documents(
            files=["doc.pdf"],
            schema=type("Invoice", (), {"__name__": "Invoice"}),
            pipeline=mock_pipeline,
        )

        cell = result.fields["supplier_name"][0]
        assert cell.value == "Acme"
        assert len(cell.evidence) == 1
        assert cell.evidence[0].text == "Acme"
        assert cell.evidence[0].page_number == 0

    async def test_handles_extraction_failure(self):
        mock_pipeline = AsyncMock()
        mock_pipeline.run = AsyncMock(side_effect=[
            _make_result("d1", "Acme", 1000.0),
            RuntimeError("extraction failed"),
            _make_result("d3", "Acme", 1000.0),
        ])

        result = await compare_documents(
            files=["a.pdf", "b.pdf", "c.pdf"],
            schema=type("Invoice", (), {"__name__": "Invoice"}),
            pipeline=mock_pipeline,
        )

        assert len(result.documents) == 2
        assert len(result.results) == 2

    async def test_missing_field_in_some_documents(self):
        r1 = ExtractionResult(
            document_id="d1", schema_name="Invoice",
            data={"name": "Acme", "total": 100},
            fields={
                "name": ExtractedField(value="Acme", confidence=0.9),
                "total": ExtractedField(value=100, confidence=0.8),
            },
        )
        r2 = ExtractionResult(
            document_id="d2", schema_name="Invoice",
            data={"name": "Beta"},
            fields={
                "name": ExtractedField(value="Beta", confidence=0.9),
            },
        )
        mock_pipeline = AsyncMock()
        mock_pipeline.run = AsyncMock(side_effect=[r1, r2])

        result = await compare_documents(
            files=["a.pdf", "b.pdf"],
            schema=type("Invoice", (), {"__name__": "Invoice"}),
            pipeline=mock_pipeline,
        )

        assert len(result.fields["total"]) == 2
        assert result.fields["total"][0].value == 100
        assert result.fields["total"][1].value is None

    async def test_serializes_to_json(self):
        mock_pipeline = AsyncMock()
        mock_pipeline.run = AsyncMock(side_effect=[
            _make_result("d1", "Acme", 1000.0),
            _make_result("d2", "Beta", 2000.0),
        ])

        result = await compare_documents(
            files=["a.pdf", "b.pdf"],
            schema=type("Invoice", (), {"__name__": "Invoice"}),
            pipeline=mock_pipeline,
        )

        output = json.loads(result.model_dump_json())
        assert "fields" in output
        assert "differences" in output
        assert "documents" in output
        assert output["differences"]["supplier_name"]["all_agree"] is False

    async def test_file_name_extraction(self):
        mock_pipeline = AsyncMock()
        mock_pipeline.run = AsyncMock(return_value=_make_result("d1", "Acme", 100))

        result = await compare_documents(
            files=["C:/docs/invoices/invoice_2024.pdf"],
            schema=type("Invoice", (), {"__name__": "Invoice"}),
            pipeline=mock_pipeline,
        )

        assert result.documents[0] == "invoice_2024.pdf"
