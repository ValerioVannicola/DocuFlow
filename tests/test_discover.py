from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from docuflow.discover import (
    DiscoveredField,
    DiscoveryResult,
    _build_pydantic_model,
    _build_yaml_template,
    discover_schema,
)
from docuflow.extraction.llm.base import LLMResponse


def _make_llm_response() -> LLMResponse:
    data = {
        "document_type": "invoice",
        "description": "A supplier invoice with line items",
        "fields": [
            {"name": "supplier_name", "type": "str", "required": True, "description": "Vendor name"},
            {"name": "invoice_number", "type": "str", "required": True, "description": "Invoice ref"},
            {"name": "invoice_date", "type": "date", "required": True, "description": "Issue date"},
            {"name": "total", "type": "float", "required": True, "description": "Total amount"},
            {"name": "currency", "type": "str", "required": False, "description": "Currency code"},
            {"name": "vat_amount", "type": "float", "required": False, "description": "VAT amount"},
        ],
    }
    return LLMResponse(content=json.dumps(data), model="gpt-4o")


class TestBuildPydanticModel:
    def test_basic_model(self):
        result = DiscoveryResult(
            document_type="invoice",
            fields=[
                DiscoveredField(name="supplier_name", type="str", required=True),
                DiscoveredField(name="total", type="float", required=True),
                DiscoveredField(name="currency", type="str", required=False),
            ],
        )
        model = _build_pydantic_model(result)

        assert issubclass(model, BaseModel)
        assert model.__name__ == "Invoice"

        instance = model(supplier_name="Acme", total=100.0)
        assert instance.supplier_name == "Acme"
        assert instance.total == 100.0
        assert instance.currency is None

    def test_required_field_enforced(self):
        result = DiscoveryResult(
            document_type="test",
            fields=[DiscoveredField(name="name", type="str", required=True)],
        )
        model = _build_pydantic_model(result)

        import pydantic

        with pytest.raises(pydantic.ValidationError):
            model()

    def test_all_types(self):
        result = DiscoveryResult(
            document_type="test",
            fields=[
                DiscoveredField(name="s", type="str", required=True),
                DiscoveredField(name="f", type="float", required=True),
                DiscoveredField(name="i", type="int", required=True),
                DiscoveredField(name="b", type="bool", required=True),
                DiscoveredField(name="tags", type="list[str]", required=False),
            ],
        )
        model = _build_pydantic_model(result)
        instance = model(s="a", f=1.0, i=1, b=True)
        assert instance.s == "a"
        assert instance.tags is None


class TestBuildYamlTemplate:
    def test_basic_yaml(self):
        result = DiscoveryResult(
            document_type="invoice",
            description="A supplier invoice",
            fields=[
                DiscoveredField(name="supplier_name", type="str", required=True, description="Vendor"),
                DiscoveredField(name="total", type="float", required=True, description="Amount"),
            ],
        )
        yaml = _build_yaml_template(result)

        assert "name: invoice" in yaml
        assert "supplier_name:" in yaml
        assert "type: str" in yaml
        assert "type: float" in yaml
        assert "required: true" in yaml


class TestDiscoverSchema:
    async def test_discover_from_document(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake content for test")

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response())

        mock_parser = AsyncMock()
        mock_parser.parse = AsyncMock(side_effect=lambda doc: _set_parsed(doc))

        with patch("docuflow.parsing.pdfplumber_parser.PdfplumberParser", return_value=mock_parser):
            result = await discover_schema(str(pdf_path), llm=mock_llm)

        assert isinstance(result, DiscoveryResult)
        assert result.document_type == "invoice"
        assert len(result.fields) == 6
        assert result.fields[0].name == "supplier_name"

        assert result.schema_class is not None
        assert issubclass(result.schema_class, BaseModel)

        instance = result.schema_class(
            supplier_name="Acme", invoice_number="INV-001",
            invoice_date="2024-01-15", total=1000.0,
        )
        assert instance.supplier_name == "Acme"

    async def test_discover_produces_yaml(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response())

        mock_parser = AsyncMock()
        mock_parser.parse = AsyncMock(side_effect=lambda doc: _set_parsed(doc))

        with patch("docuflow.parsing.pdfplumber_parser.PdfplumberParser", return_value=mock_parser):
            result = await discover_schema(str(pdf_path), llm=mock_llm)

        assert result.yaml_template != ""
        assert "name: invoice" in result.yaml_template
        assert "supplier_name:" in result.yaml_template

    async def test_discover_then_extract(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response())

        mock_parser = AsyncMock()
        mock_parser.parse = AsyncMock(side_effect=lambda doc: _set_parsed(doc))

        with patch("docuflow.parsing.pdfplumber_parser.PdfplumberParser", return_value=mock_parser):
            discovery = await discover_schema(str(pdf_path), llm=mock_llm)

        schema = discovery.schema_class
        assert schema.__name__ == "Invoice"
        assert "supplier_name" in schema.model_fields
        assert "total" in schema.model_fields

    async def test_prompt_includes_document_text(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response())

        mock_parser = AsyncMock()
        mock_parser.parse = AsyncMock(side_effect=lambda doc: _set_parsed(doc))

        with patch("docuflow.parsing.pdfplumber_parser.PdfplumberParser", return_value=mock_parser):
            await discover_schema(str(pdf_path), llm=mock_llm)

        call_messages = mock_llm.complete.call_args[0][0]
        assert "Analyze this document" in call_messages[1]["content"]
        assert "Invoice from Acme" in call_messages[1]["content"]


def _set_parsed(doc):
    doc.raw_text = "Invoice from Acme Corp\nInvoice #: INV-001\nTotal: 1234.56"
    doc.status = "parsed"
    return doc
