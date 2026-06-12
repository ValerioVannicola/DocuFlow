from __future__ import annotations

from docuflow.extraction.models import ExtractionResult
from docuflow.strategies.base import Strategy


class TestStrategyProtocol:
    def test_protocol_compliance(self):
        class FakeStrategy:
            async def execute(self, document, schema, **kwargs):
                return ExtractionResult(document_id="x", schema_name="Y")

        assert isinstance(FakeStrategy(), Strategy)
