from __future__ import annotations

from unittest.mock import AsyncMock

from docuflow.privacy.policy import PrivacyPolicy
from docuflow.workflow.state import PipelineState
from docuflow.workflow.steps import Anonymize, PipelineStep


class MockProvider:
    async def adetect_text(self, text, entities=None, language="en", score_threshold=0.35):
        return []

    async def aanonymize_text(self, text, findings, mode, token_map=None):
        return text, []

    async def arestore_text(self, text, mappings):
        return text


class TestAnonymizeStep:
    async def test_anonymize_step_no_policy(self):
        step = Anonymize(policy=None)
        state = PipelineState()
        result = await step.execute(state)
        assert result.status != "failed"

    async def test_anonymize_step_no_document(self):
        policy = PrivacyPolicy(provider=MockProvider())
        step = Anonymize(policy=policy)
        state = PipelineState()
        result = await step.execute(state)
        assert result.status == "failed"

    async def test_anonymize_step_success(self):
        from docuflow.documents.models import Document, DocumentMetadata, Page

        policy = PrivacyPolicy(provider=MockProvider())
        step = Anonymize(policy=policy)
        state = PipelineState()
        state.document = Document(
            id="doc-1",
            metadata=DocumentMetadata(
                file_name="test.pdf", file_path="C:/test/test.pdf", mime_type="application/pdf"
            ),
            pages=[Page(page_number=0, text="Some text here")],
            raw_text="Some text here",
        )
        result = await step.execute(state)
        assert result.status != "failed"
        assert "anonymization_result" in result.metadata

    async def test_anonymize_step_fail_closed(self):
        failing_provider = AsyncMock()
        failing_provider.adetect_text = AsyncMock(side_effect=RuntimeError("provider error"))
        policy = PrivacyPolicy(provider=failing_provider, fail_closed=True)
        step = Anonymize(policy=policy)

        from docuflow.documents.models import Document, DocumentMetadata, Page

        state = PipelineState()
        state.document = Document(
            id="doc-1",
            metadata=DocumentMetadata(
                file_name="test.pdf", file_path="C:/test/test.pdf", mime_type="application/pdf"
            ),
            pages=[Page(page_number=0, text="John Doe")],
            raw_text="John Doe",
        )
        result = await step.execute(state)
        assert result.status == "failed"
        assert any("Anonymization failed" in e for e in result.errors)

    async def test_anonymize_step_fail_open(self):
        failing_provider = AsyncMock()
        failing_provider.adetect_text = AsyncMock(side_effect=RuntimeError("provider error"))
        policy = PrivacyPolicy(provider=failing_provider, fail_closed=False)
        step = Anonymize(policy=policy)

        from docuflow.documents.models import Document, DocumentMetadata, Page

        state = PipelineState()
        state.document = Document(
            id="doc-1",
            metadata=DocumentMetadata(
                file_name="test.pdf", file_path="C:/test/test.pdf", mime_type="application/pdf"
            ),
            pages=[Page(page_number=0, text="John Doe")],
            raw_text="John Doe",
        )
        result = await step.execute(state)
        assert result.status != "failed"

    def test_protocol_compliance(self):
        assert isinstance(Anonymize(), PipelineStep)


class TestDocumentPipelinePrivacy:
    def test_pipeline_without_privacy_unchanged(self):
        from docuflow.processor import DocumentPipeline

        pipeline = DocumentPipeline()
        assert pipeline._privacy is None

    def test_pipeline_with_privacy(self):
        from docuflow.processor import DocumentPipeline

        policy = PrivacyPolicy(provider=MockProvider())
        pipeline = DocumentPipeline(privacy=policy)
        assert pipeline._privacy is policy
