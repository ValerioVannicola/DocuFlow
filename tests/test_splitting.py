"""Tests for document splitting."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from docuflow.splitting.models import DocumentSection

# ---------------------------------------------------------------------------
# Helper — minimal PDF with N pages of text
# ---------------------------------------------------------------------------

def _make_pdf(pages: list[str]) -> bytes:
    """Create a minimal PDF using reportlab with one text page per entry."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for text in pages:
        c.setFont("Helvetica", 12)
        c.drawString(72, 720, text[:100])
        c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


def _write_tmp(tmp_path: Path, pages: list[str]) -> Path:
    p = tmp_path / "doc.pdf"
    p.write_bytes(_make_pdf(pages))
    return p


# ---------------------------------------------------------------------------
# Schema fixtures
# ---------------------------------------------------------------------------

class ContractSections(BaseModel):
    contract_body: str = Field(description="Main contract terms and conditions")
    exhibits: str = Field(description="Attached exhibits and appendices")
    signature_page: str = Field(description="Pages containing signatures")


# ---------------------------------------------------------------------------
# _parse_schema
# ---------------------------------------------------------------------------

def test_parse_schema_from_model():
    from docuflow.splitting.api import _parse_schema

    sections = _parse_schema(ContractSections)
    names = {s.name for s in sections}
    assert names == {"contract_body", "exhibits", "signature_page"}
    assert any(s.description == "Main contract terms and conditions" for s in sections)


def test_parse_schema_from_list():
    from docuflow.splitting.api import _parse_schema

    raw = [
        DocumentSection(name="intro", description="Introduction"),
        DocumentSection(name="body", description="Body text"),
    ]
    sections = _parse_schema(raw)
    assert [s.name for s in sections] == ["intro", "body"]


# ---------------------------------------------------------------------------
# _build_messages
# ---------------------------------------------------------------------------

def test_build_messages_contains_section_names():
    from docuflow.splitting.api import _build_messages

    page_texts = [(0, "Page zero content"), (1, "Page one content")]
    sections = [
        DocumentSection(name="intro", description="Introductory section"),
        DocumentSection(name="body", description="Main body"),
    ]
    msgs = _build_messages(page_texts, sections, "", True, False)
    user_text = msgs[-1]["content"]
    assert "intro" in user_text
    assert "Introductory section" in user_text
    assert "Page zero content" in user_text


def test_build_messages_deep_includes_evidence_note():
    from docuflow.splitting.api import _build_messages

    msgs = _build_messages(
        [(0, "text")],
        [DocumentSection(name="s", description="d")],
        "", True, deep=True,
    )
    assert "evidence" in msgs[-1]["content"]
    assert "confidence" in msgs[-1]["content"]


def test_build_messages_no_overlap_note():
    from docuflow.splitting.api import _build_messages

    msgs = _build_messages(
        [(0, "text")],
        [DocumentSection(name="s", description="d")],
        "", allow_overlap=False, deep=False,
    )
    assert "exactly one section" in msgs[-1]["content"]


@pytest.mark.asyncio
async def test_call_llm_forwards_kwargs_to_custom_adapter():
    from docuflow.splitting.api import _call_llm, _SimpleSplitResponse

    class Response:
        def __init__(self) -> None:
            self.content = '{"sections": {}}'
            self.usage = {"total_tokens": 1}

    class FakeLLM:
        def __init__(self) -> None:
            self.kwargs = {}

        async def complete(self, messages, **kwargs):
            self.kwargs = kwargs
            return Response()

    llm = FakeLLM()
    raw, usage = await _call_llm(
        [],
        response_format=_SimpleSplitResponse,
        model="unused",
        llm=llm,
        llm_kwargs={"temperature": 0.2, "metadata": {"source": "test"}},
    )

    assert raw == '{"sections": {}}'
    assert usage == {"total_tokens": 1}
    assert llm.kwargs["response_format"] is _SimpleSplitResponse
    assert llm.kwargs["temperature"] == 0.2
    assert llm.kwargs["metadata"] == {"source": "test"}


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

def test_parse_response_simple():
    from docuflow.splitting.api import _parse_response

    raw = json.dumps({"sections": {"contract_body": {"pages": [0, 1]}, "exhibits": {"pages": [2]}}})
    sections = [
        DocumentSection(name="contract_body", description=""),
        DocumentSection(name="exhibits", description=""),
    ]
    result = _parse_response(raw, sections, deep=False)
    assert result["contract_body"].pages == [0, 1]
    assert result["exhibits"].pages == [2]


def test_parse_response_deep():
    from docuflow.splitting.api import _parse_response

    raw = json.dumps({
        "sections": {
            "contract_body": {"pages": [0, 1], "confidence": "high", "evidence": "Terms on pages 0-1"},
        }
    })
    sections = [DocumentSection(name="contract_body", description="")]
    result = _parse_response(raw, sections, deep=True)
    assert result["contract_body"].confidence == "high"
    assert "Terms" in result["contract_body"].evidence


def test_parse_response_missing_section_gets_empty():
    from docuflow.splitting.api import _parse_response

    raw = json.dumps({"sections": {}})
    sections = [DocumentSection(name="missing", description="")]
    result = _parse_response(raw, sections, deep=False)
    assert result["missing"].pages == []


def test_parse_response_bad_json_returns_empty():
    from docuflow.splitting.api import _parse_response

    sections = [DocumentSection(name="s", description="")]
    result = _parse_response("not json", sections, deep=False)
    assert result["s"].pages == []


# ---------------------------------------------------------------------------
# Full split_document_async — monkeypatched LLM
# ---------------------------------------------------------------------------

def _make_llm_response(page_map: dict[str, list[int]], deep: bool = False) -> str:
    if deep:
        return json.dumps({
            "sections": {
                name: {"pages": pages, "confidence": "high", "evidence": f"{name} pages"}
                for name, pages in page_map.items()
            }
        })
    return json.dumps({"sections": {name: {"pages": pages} for name, pages in page_map.items()}})


@pytest.mark.asyncio
async def test_split_document_simple(tmp_path, monkeypatch):
    p = _write_tmp(tmp_path, ["Contract terms", "More terms", "Exhibit A", "Signatures"])
    expected_map = {"contract_body": [0, 1], "exhibits": [2], "signature_page": [3]}

    async def _fake_call(messages, *, response_format, model, llm, llm_kwargs):
        return _make_llm_response(expected_map, deep=False), {"total_tokens": 100}

    monkeypatch.setattr("docuflow.splitting.api._call_llm", _fake_call)

    from docuflow.splitting.api import split_document_async

    result = await split_document_async(str(p), ContractSections)
    assert result.success
    assert result.total_pages == 4
    assert result.page_map["contract_body"] == [0, 1]
    assert result.page_map["exhibits"] == [2]
    assert result.page_map["signature_page"] == [3]
    assert result.usage["total_tokens"] == 100


@pytest.mark.asyncio
async def test_split_document_deep(tmp_path, monkeypatch):
    p = _write_tmp(tmp_path, ["Contract terms", "Exhibit A"])
    expected_map = {"contract_body": [0], "exhibits": [1]}

    async def _fake_call(messages, *, response_format, model, llm, llm_kwargs):
        return _make_llm_response(expected_map, deep=True), {}

    monkeypatch.setattr("docuflow.splitting.api._call_llm", _fake_call)

    from docuflow.splitting.api import split_document_async

    result = await split_document_async(str(p), ContractSections, deep=True)
    assert result.sections["contract_body"].confidence == "high"
    assert result.sections["exhibits"].evidence == "exhibits pages"


@pytest.mark.asyncio
async def test_split_document_list_schema(tmp_path, monkeypatch):
    p = _write_tmp(tmp_path, ["Intro", "Body"])
    sections = [
        DocumentSection(name="intro", description="Introduction"),
        DocumentSection(name="body", description="Body text"),
    ]

    async def _fake_call(messages, *, response_format, model, llm, llm_kwargs):
        return json.dumps({"sections": {"intro": {"pages": [0]}, "body": {"pages": [1]}}}), {}

    monkeypatch.setattr("docuflow.splitting.api._call_llm", _fake_call)

    from docuflow.splitting.api import split_document_async

    result = await split_document_async(str(p), sections)
    assert result.page_map["intro"] == [0]
    assert result.page_map["body"] == [1]


@pytest.mark.asyncio
async def test_split_document_out_of_range_pages_warned(tmp_path, monkeypatch):
    p = _write_tmp(tmp_path, ["Only page"])

    async def _fake_call(messages, *, response_format, model, llm, llm_kwargs):
        # LLM returns page 99 which doesn't exist
        return json.dumps({"sections": {"contract_body": {"pages": [0, 99]}, "exhibits": {"pages": []}, "signature_page": {"pages": []}}}), {}

    monkeypatch.setattr("docuflow.splitting.api._call_llm", _fake_call)

    from docuflow.splitting.api import split_document_async

    result = await split_document_async(str(p), ContractSections)
    assert 99 not in result.sections["contract_body"].pages
    assert any("99" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_split_document_page_subset(tmp_path, monkeypatch):
    p = _write_tmp(tmp_path, ["Page 0", "Page 1", "Page 2", "Page 3"])

    async def _fake_call(messages, *, response_format, model, llm, llm_kwargs):
        # Verify the message only contains pages 1 and 2
        user_text = messages[-1]["content"]
        assert "Page 0" not in user_text
        assert "Page 1" in user_text
        assert "Page 2" in user_text
        return json.dumps({"sections": {"contract_body": {"pages": [1]}, "exhibits": {"pages": [2]}, "signature_page": {"pages": []}}}), {}

    monkeypatch.setattr("docuflow.splitting.api._call_llm", _fake_call)

    from docuflow.splitting.api import split_document_async

    result = await split_document_async(str(p), ContractSections, pages=[1, 2])
    assert result.total_pages == 2


@pytest.mark.asyncio
async def test_split_document_no_sections_errors(tmp_path, monkeypatch):
    p = _write_tmp(tmp_path, ["text"])

    from docuflow.splitting.api import split_document_async

    class EmptySchema(BaseModel):
        pass

    result = await split_document_async(str(p), EmptySchema)
    assert not result.success
    assert result.errors


@pytest.mark.asyncio
async def test_split_document_page_map_property(tmp_path, monkeypatch):
    p = _write_tmp(tmp_path, ["A", "B", "C"])

    async def _fake_call(messages, *, response_format, model, llm, llm_kwargs):
        return json.dumps({"sections": {
            "contract_body": {"pages": [2, 0]},
            "exhibits": {"pages": [1]},
            "signature_page": {"pages": []},
        }}), {}

    monkeypatch.setattr("docuflow.splitting.api._call_llm", _fake_call)

    from docuflow.splitting.api import split_document_async

    result = await split_document_async(str(p), ContractSections)
    # page_map returns sorted pages
    assert result.page_map["contract_body"] == [0, 2]
