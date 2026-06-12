from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from docuflow.extraction.llm.base import LLMResponse
from docuflow.extraction.models import ExtractionResult, TokenUsage
from docuflow.router import DEFAULT_ROUTER_MODEL, WorkflowRouter


class Invoice(BaseModel):
    supplier_name: str
    total: float


class Claim(BaseModel):
    policy_number: str
    damage_amount: float


def _fake_pipeline(result: ExtractionResult | None = None, error: str | None = None):
    pipeline = AsyncMock()
    if error:
        pipeline.run = AsyncMock(side_effect=RuntimeError(error))
    else:
        pipeline.run = AsyncMock(return_value=result or ExtractionResult(
            document_id="d1", schema_name="Invoice", confidence=0.9,
        ))
    return pipeline


def _classifier_llm(decisions: list[dict]):
    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=[
        LLMResponse(
            content=json.dumps(d),
            model="gemini-2.5-flash",
            usage={"prompt_tokens": 400, "completion_tokens": 30, "total_tokens": 430},
        )
        for d in decisions
    ])
    return llm


def _router(llm, **kwargs) -> WorkflowRouter:
    router = WorkflowRouter(llm=llm, **kwargs)
    router.register("invoice", pipeline=_fake_pipeline(), schema=Invoice,
                    description="supplier invoices")
    router.register("claim", pipeline=_fake_pipeline(), schema=Claim,
                    description="insurance claim forms")
    return router


def _patch_peek():
    return patch.object(
        WorkflowRouter, "_peek",
        new=AsyncMock(return_value=("Invoice INV-001 from Acme Corp Total 1234.56", None)),
    )


class TestRegistration:
    def test_default_model_is_gemini_flash(self):
        assert WorkflowRouter().model == DEFAULT_ROUTER_MODEL == "gemini/gemini-2.5-flash"

    def test_duplicate_name_raises(self):
        router = _router(AsyncMock())
        with pytest.raises(ValueError, match="already registered"):
            router.register("invoice", pipeline=_fake_pipeline(), schema=Invoice)

    def test_register_requires_pipeline_or_workflow(self):
        router = WorkflowRouter()
        with pytest.raises(ValueError, match="needs either"):
            router.register("x")

    def test_description_defaults_to_schema_fields(self):
        router = WorkflowRouter()
        router.register("invoice", pipeline=_fake_pipeline(), schema=Invoice)
        assert "supplier_name" in router._workflows["invoice"].description

    def test_from_config_dict(self):
        cfg = {
            "model": "openai/gpt-4o-mini",
            "workflows": [
                {
                    "name": "invoice",
                    "description": "supplier invoices",
                    "workflow": {
                        "name": "inv",
                        "schema": {"total": {"type": "float"}},
                    },
                },
            ],
        }
        router = WorkflowRouter.from_config(cfg)
        assert router.model == "openai/gpt-4o-mini"
        assert "invoice" in router._workflows


class TestClassification:
    async def test_classifies_to_registered_workflow(self):
        llm = _classifier_llm([
            {"workflow": "invoice", "confidence": 0.95, "reason": "has invoice number"},
        ])
        router = _router(llm)
        with _patch_peek():
            decision = await router.classify("/docs/a.pdf")
        assert decision.workflow == "invoice"
        assert decision.confidence == 0.95

    async def test_none_answer_unclassified(self):
        llm = _classifier_llm([
            {"workflow": "none", "confidence": 0.9, "reason": "looks like a menu"},
        ])
        router = _router(llm)
        with _patch_peek():
            decision = await router.classify("/docs/a.pdf")
        assert decision.workflow is None
        assert "menu" in decision.reason

    async def test_low_confidence_unclassified(self):
        llm = _classifier_llm([
            {"workflow": "invoice", "confidence": 0.3, "reason": "maybe"},
        ])
        router = _router(llm)
        with _patch_peek():
            decision = await router.classify("/docs/a.pdf")
        assert decision.workflow is None
        assert "below" in decision.reason

    async def test_unknown_workflow_name_unclassified(self):
        llm = _classifier_llm([
            {"workflow": "receipt", "confidence": 0.9, "reason": "a receipt"},
        ])
        router = _router(llm)
        with _patch_peek():
            decision = await router.classify("/docs/a.pdf")
        assert decision.workflow is None

    async def test_classifier_error_degrades_to_unclassified(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("rate limited"))
        router = _router(llm)
        with _patch_peek():
            decision = await router.classify("/docs/a.pdf")
        assert decision.workflow is None
        assert "rate limited" in decision.reason


class TestRouting:
    async def test_routes_and_groups_results(self):
        llm = _classifier_llm([
            {"workflow": "invoice", "confidence": 0.9, "reason": "r1"},
            {"workflow": "claim", "confidence": 0.85, "reason": "r2"},
            {"workflow": "none", "confidence": 0.9, "reason": "unknown type"},
        ])
        router = _router(llm)
        with _patch_peek():
            report = await router.route(["/a.pdf", "/b.pdf", "/c.pdf"])

        assert report.total == 3
        assert len(report.by_workflow["invoice"]) == 1
        assert len(report.by_workflow["claim"]) == 1
        assert len(report.unclassified) == 1
        assert report.unclassified[0].classification_reason == "unknown type"

    async def test_pipeline_failure_recorded_not_raised(self):
        llm = _classifier_llm([
            {"workflow": "invoice", "confidence": 0.9, "reason": "r"},
        ])
        router = WorkflowRouter(llm=llm)
        router.register(
            "invoice", pipeline=_fake_pipeline(error="boom"), schema=Invoice,
        )
        with _patch_peek():
            report = await router.route(["/a.pdf"])

        assert report.failed[0].error == "boom"
        assert not report.failed[0].success

    async def test_usage_includes_classification_and_extraction(self):
        result = ExtractionResult(
            document_id="d1", schema_name="Invoice", confidence=0.9,
            usage=TokenUsage(prompt_tokens=1000, completion_tokens=200,
                             total_tokens=1200, n_llm_calls=1),
        )
        llm = _classifier_llm([
            {"workflow": "invoice", "confidence": 0.9, "reason": "r"},
        ])
        router = WorkflowRouter(llm=llm)
        router.register("invoice", pipeline=_fake_pipeline(result=result),
                        schema=Invoice)
        with _patch_peek():
            report = await router.route(["/a.pdf"])

        # 430 classification + 1200 extraction
        assert report.usage.total_tokens == 1630
        assert report.usage.n_llm_calls == 2

    async def test_no_workflows_raises(self):
        router = WorkflowRouter(llm=AsyncMock())
        with pytest.raises(ValueError, match="No workflows registered"):
            await router.route(["/a.pdf"])

    async def test_to_csv(self):
        llm = _classifier_llm([
            {"workflow": "invoice", "confidence": 0.9, "reason": "r"},
        ])
        router = _router(llm)
        with _patch_peek():
            report = await router.route(["/a.pdf"])
        csv_text = report.to_csv()
        assert "file_name" in csv_text
        assert "invoice" in csv_text


class TestTopLevelExport:
    def test_importable_from_package_root(self):
        from docuflow import WorkflowRouter as Exported

        assert Exported is WorkflowRouter
