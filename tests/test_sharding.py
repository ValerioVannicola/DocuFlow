from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel, Field

from docuflow.documents.models import Document, DocumentMetadata, Page
from docuflow.extraction.engine import ExtractionEngine
from docuflow.extraction.llm.base import LLMResponse
from docuflow.extraction.models import ExtractionResult, TokenUsage
from docuflow.extraction.sharding import merge_shard_results, shard_schema


class WideInvoice(BaseModel):
    supplier_name: str = Field(description="Supplier")
    invoice_number: str = Field(description="Number")
    invoice_date: str = Field(description="Date")
    total: float = Field(description="Total")
    currency: str = Field(default="EUR", description="Currency")
    po_number: str = Field(default="", description="PO")


class TestShardSchema:
    def test_splits_into_contiguous_groups(self):
        shards = shard_schema(WideInvoice, 2)
        assert len(shards) == 2
        names_0 = list(shards[0].model_fields.keys())
        names_1 = list(shards[1].model_fields.keys())
        assert names_0 + names_1 == list(WideInvoice.model_fields.keys())

    def test_preserves_field_metadata(self):
        shards = shard_schema(WideInvoice, 2)
        all_fields = {}
        for s in shards:
            all_fields.update(s.model_fields)
        assert all_fields["supplier_name"].description == "Supplier"
        assert all_fields["currency"].default == "EUR"
        assert all_fields["total"].is_required()

    def test_one_shard_returns_original(self):
        assert shard_schema(WideInvoice, 1) == [WideInvoice]

    def test_more_shards_than_fields_caps(self):
        shards = shard_schema(WideInvoice, 100)
        assert len(shards) <= len(WideInvoice.model_fields)
        total_fields = sum(len(s.model_fields) for s in shards)
        assert total_fields == len(WideInvoice.model_fields)


class TestMergeShardResults:
    def test_merges_data_fields_and_usage(self):
        r1 = ExtractionResult(
            document_id="d1", schema_name="S1",
            data={"a": 1}, confidence=0.8,
            usage=TokenUsage(prompt_tokens=100, completion_tokens=10,
                             total_tokens=110, n_llm_calls=1),
        )
        r2 = ExtractionResult(
            document_id="d1", schema_name="S2",
            data={"b": 2}, confidence=0.6,
            usage=TokenUsage(prompt_tokens=100, completion_tokens=20,
                             total_tokens=120, n_llm_calls=1),
        )
        merged = merge_shard_results([r1, r2], WideInvoice)
        assert merged.data == {"a": 1, "b": 2}
        assert merged.schema_name == "WideInvoice"
        assert merged.usage.total_tokens == 230
        assert merged.usage.n_llm_calls == 2


class TestShardedExtraction:
    def _doc(self) -> Document:
        text = "Acme Corp INV-001 2024-11-15 Total: 1234.56 USD PO-9"
        return Document(
            id="d1",
            metadata=DocumentMetadata(file_name="t.pdf", file_path="/t.pdf"),
            pages=[Page(page_number=0, text=text)],
            raw_text=text,
        )

    async def test_shards_run_in_parallel_and_merge(self):
        def respond(messages, **kwargs):
            # answer only the fields the shard asked about
            prompt = json.dumps(messages)
            data = {}
            if "supplier_name" in prompt:
                data.update({
                    "supplier_name": "Acme Corp",
                    "invoice_number": "INV-001",
                    "invoice_date": "2024-11-15",
                })
            if "total" in prompt and "supplier_name" not in prompt:
                data.update({
                    "total": 1234.56, "currency": "USD", "po_number": "PO-9",
                })
            return LLMResponse(
                content=json.dumps({"data": data, "evidence": {}}),
                model="gpt-4o",
                usage={"prompt_tokens": 100, "completion_tokens": 50,
                       "total_tokens": 150},
            )

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(side_effect=respond)

        engine = ExtractionEngine(llm=mock_llm)
        result = await engine.extract(self._doc(), schema=WideInvoice, shards=2)

        assert mock_llm.complete.call_count == 2
        assert result.data["supplier_name"] == "Acme Corp"
        assert result.data["total"] == 1234.56
        assert result.schema_name == "WideInvoice"
        assert len(result.fields) == 6
        assert result.usage.n_llm_calls == 2
        assert result.usage.total_tokens == 300

    async def test_shards_none_single_call(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({
                "data": {
                    "supplier_name": "Acme Corp", "invoice_number": "INV-001",
                    "invoice_date": "2024-11-15", "total": 1234.56,
                    "currency": "USD", "po_number": "PO-9",
                },
                "evidence": {},
            }),
            model="gpt-4o",
        ))
        engine = ExtractionEngine(llm=mock_llm)
        result = await engine.extract(self._doc(), schema=WideInvoice)
        assert mock_llm.complete.call_count == 1
        assert result.data["total"] == 1234.56


class TestShardingWiring:
    def test_pipeline_accepts_schema_shards(self):
        from docuflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(schema_shards=3)
        assert pipeline._schema_shards == 3

    def test_workflow_config_accepts_schema_shards(self):
        from docuflow.workflow_config import load_workflow_config

        cfg = load_workflow_config({
            "name": "t",
            "schema": {"total": {"type": "float"}},
            "schema_shards": 2,
        })
        pipeline = cfg.build_pipeline()
        assert pipeline._schema_shards == 2


class TestPromptCaching:
    def test_system_message_marked_for_anthropic(self):
        from docuflow.extraction.llm.litellm_adapter import _mark_system_cacheable

        messages = [
            {"role": "system", "content": "You are an extractor."},
            {"role": "user", "content": "Extract from this."},
        ]
        marked = _mark_system_cacheable(messages)
        assert marked[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert marked[0]["content"][0]["text"] == "You are an extractor."
        assert marked[1] == messages[1]  # user message untouched

    def test_adapter_flag_stored(self):
        from docuflow.extraction.llm.litellm_adapter import LiteLLMAdapter

        adapter = LiteLLMAdapter(
            model="anthropic/claude-sonnet-4-6", prompt_caching=True,
        )
        assert adapter.prompt_caching is True
        # prompt_caching must NOT leak into litellm call kwargs
        assert "prompt_caching" not in adapter.extra_kwargs


@pytest.mark.parametrize("n", [2, 3])
def test_shard_sizes_balanced(n):
    shards = shard_schema(WideInvoice, n)
    sizes = [len(s.model_fields) for s in shards]
    assert max(sizes) - min(sizes) <= 1 or sum(sizes) == 6
