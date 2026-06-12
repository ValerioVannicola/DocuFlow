from __future__ import annotations

import time
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from docflow.constants import DEFAULT_DPI
from docflow.workflow.state import PipelineState


@runtime_checkable
class PipelineStep(Protocol):
    name: str

    async def execute(self, state: PipelineState) -> PipelineState: ...


class Ingest:
    name = "ingest"

    def __init__(self, path: str | None = None):
        self.path = path

    async def execute(self, state: PipelineState) -> PipelineState:
        from docflow.ingestion.local import ingest_file

        path = self.path or state.metadata.get("input_path", "")
        if not path:
            state.errors.append("No input path provided for ingestion")
            state.status = "failed"
            return state

        start = time.monotonic()
        state.document = await ingest_file(path)
        state.trace.document_id = state.document.id
        duration = (time.monotonic() - start) * 1000
        state.trace.add_event("ingest", step_name=self.name, duration_ms=duration)
        return state


class Parse:
    name = "parse"

    def __init__(self, parser: Any = None):
        self.parser = parser

    async def execute(self, state: PipelineState) -> PipelineState:
        if state.document is None:
            state.errors.append("No document to parse")
            state.status = "failed"
            return state

        parser = self.parser
        if parser is None or parser == "pymupdf":
            from docflow.parsing.pymupdf import PyMuPDFParser
            parser = PyMuPDFParser()
        elif parser == "tesseract":
            from docflow.parsing.tesseract_parser import TesseractParser
            parser = TesseractParser()
        elif parser == "docling":
            from docflow.parsing.docling_parser import DoclingParser
            parser = DoclingParser()
        elif parser == "smart":
            from docflow.parsing.smart_parser import SmartParser
            parser = SmartParser()
        elif parser == "azure-di":
            from docflow.parsing.azure_di import AzureDocumentIntelligenceParser
            parser = AzureDocumentIntelligenceParser()
        elif parser == "textract":
            from docflow.parsing.textract import TextractParser
            parser = TextractParser()
        elif parser == "google-docai":
            from docflow.parsing.google_docai import GoogleDocumentAIParser
            parser = GoogleDocumentAIParser()

        start = time.monotonic()
        state.document = await parser.parse(state.document)
        duration = (time.monotonic() - start) * 1000
        state.trace.add_event("parse", step_name=self.name, duration_ms=duration)
        return state


class Anonymize:
    name = "anonymize"

    def __init__(self, policy: Any = None):
        self.policy = policy

    async def execute(self, state: PipelineState) -> PipelineState:
        if self.policy is None:
            return state

        if state.document is None:
            state.errors.append("No document to anonymize")
            state.status = "failed"
            return state

        from docflow.privacy.anonymizer import Anonymizer

        anonymizer = Anonymizer(self.policy)
        start = time.monotonic()
        try:
            anon_result = await anonymizer.anonymize_document(state.document)
            state.metadata["anonymization_result"] = anon_result
            state.metadata["original_raw_text"] = state.document.raw_text
            state.document.raw_text = anon_result.anonymized_text
            if anon_result.page_results:
                for page, anon_page in zip(state.document.pages, anon_result.page_results, strict=False):
                    page.text = anon_page.text
        except Exception as exc:
            if self.policy.fail_closed:

                state.errors.append(f"Anonymization failed (fail_closed): {exc}")
                state.status = "failed"
            else:
                state.trace.add_event(
                    "anonymization_warning", step_name=self.name, error=str(exc)
                )
        duration = (time.monotonic() - start) * 1000
        state.trace.add_event("anonymize", step_name=self.name, duration_ms=duration)
        return state


class Extract:
    name = "extract"

    def __init__(
        self,
        schema: type[BaseModel] | None = None,
        llm: Any = None,
        mode: str = "single",
        n_instances: int = 5,
        temperatures: list[float] | None = None,
        context: str | None = None,
        scoring: str = "qualitative",
    ):
        self._schema = schema
        self.llm = llm
        self.mode = mode
        self.n_instances = n_instances
        self.temperatures = temperatures
        self.context = context
        self.scoring = scoring

    async def execute(self, state: PipelineState) -> PipelineState:
        if state.document is None:
            state.errors.append("No document to extract from")
            state.status = "failed"
            return state

        schema = self._schema or state.metadata.get("schema")
        if schema is None:
            state.errors.append("No schema provided for extraction")
            state.status = "failed"
            return state

        from docflow.extraction.engine import ExtractionEngine

        engine = ExtractionEngine(llm=self.llm, context=self.context)
        start = time.monotonic()
        state.extraction_result = await engine.extract(
            state.document, schema, trace=state.trace,
            mode=self.mode, n_instances=self.n_instances,
            temperatures=self.temperatures, scoring=self.scoring,
        )
        duration = (time.monotonic() - start) * 1000
        state.trace.add_event("extract", step_name=self.name, duration_ms=duration)
        return state


class ExtractVision:
    name = "extract_vision"

    def __init__(
        self,
        schema: type[BaseModel] | None = None,
        llm: Any = None,
        mode: str = "single",
        n_instances: int = 5,
        temperatures: list[float] | None = None,
        dpi: int = DEFAULT_DPI,
        context: str | None = None,
        scoring: str = "qualitative",
    ):
        self._schema = schema
        self.llm = llm
        self.mode = mode
        self.n_instances = n_instances
        self.temperatures = temperatures
        self.dpi = dpi
        self.context = context
        self.scoring = scoring

    async def execute(self, state: PipelineState) -> PipelineState:
        if state.document is None:
            state.errors.append("No document to extract from")
            state.status = "failed"
            return state

        if state.document.status == "parsed":
            state.errors.append(
                "ExtractVision cannot be used after a Parse step. "
                "Vision extraction reads the PDF directly as images — "
                "remove the Parse step from the pipeline."
            )
            state.status = "failed"
            return state

        schema = self._schema or state.metadata.get("schema")
        if schema is None:
            state.errors.append("No schema provided for extraction")
            state.status = "failed"
            return state

        from docflow.extraction.engine import VisionExtractionEngine

        engine = VisionExtractionEngine(llm=self.llm, dpi=self.dpi, context=self.context)
        start = time.monotonic()
        state.extraction_result = await engine.extract(
            state.document, schema, trace=state.trace,
            mode=self.mode, n_instances=self.n_instances,
            temperatures=self.temperatures, scoring=self.scoring,
        )
        duration = (time.monotonic() - start) * 1000
        state.trace.add_event("extract_vision", step_name=self.name, duration_ms=duration)
        return state


class ExtractHybrid:
    name = "extract_hybrid"

    def __init__(
        self,
        schema: type[BaseModel] | None = None,
        llm: Any = None,
        n_instances: int = 5,
        temperatures: list[float] | None = None,
        dpi: int = DEFAULT_DPI,
        context: str | None = None,
        scoring: str = "qualitative",
    ):
        self._schema = schema
        self.llm = llm
        self.n_instances = n_instances
        self.temperatures = temperatures
        self.dpi = dpi
        self.context = context
        self.scoring = scoring

    async def execute(self, state: PipelineState) -> PipelineState:
        if state.document is None:
            state.errors.append("No document to extract from")
            state.status = "failed"
            return state

        if state.document.status == "parsed":
            state.errors.append(
                "ExtractHybrid cannot be used after a Parse step. "
                "Hybrid extraction handles OCR internally — "
                "remove the Parse step from the pipeline."
            )
            state.status = "failed"
            return state

        schema = self._schema or state.metadata.get("schema")
        if schema is None:
            state.errors.append("No schema provided for extraction")
            state.status = "failed"
            return state

        from docflow.extraction.engine import HybridExtractionEngine

        engine = HybridExtractionEngine(llm=self.llm, dpi=self.dpi, context=self.context)
        start = time.monotonic()
        state.extraction_result = await engine.extract(
            state.document, schema, trace=state.trace,
            n_instances=self.n_instances,
            temperatures=self.temperatures, scoring=self.scoring,
        )
        duration = (time.monotonic() - start) * 1000
        state.trace.add_event("extract_hybrid", step_name=self.name, duration_ms=duration)
        return state


class Review:
    name = "review"

    def __init__(self, rules: list | None = None):
        self.rules = rules or []

    async def execute(self, state: PipelineState) -> PipelineState:
        if state.extraction_result is None:
            state.errors.append("No extraction result to review")
            state.status = "failed"
            return state

        from docflow.extraction.models import ReviewVerdict

        document_text = state.document.raw_text if state.document else ""

        start = time.monotonic()
        reasons: list[str] = []
        for rule in self.rules:
            if hasattr(rule, "acheck"):
                result = await rule.acheck(
                    state.extraction_result, document_text=document_text,
                )
                if isinstance(result, ReviewVerdict):
                    state.extraction_result.review_verdicts.append(result)
                    if result.verdict != "Approved":
                        reasons.append(f"{result.reviewer}: {result.reasoning}")
                elif result:
                    reasons.append(result)
            else:
                reason = rule.check(state.extraction_result)
                if reason:
                    reasons.append(reason)

        if reasons:
            state.extraction_result.needs_review = True
            state.extraction_result.review_reasons = reasons

        duration = (time.monotonic() - start) * 1000
        state.trace.add_event(
            "review", step_name=self.name, duration_ms=duration,
            needs_review=bool(reasons), n_reasons=len(reasons),
        )
        return state


class Validate:
    name = "validate"

    def __init__(self, validators: list | None = None):
        self.validators = validators or []

    async def execute(self, state: PipelineState) -> PipelineState:
        if state.extraction_result is None:
            state.errors.append("No extraction result to validate")
            state.status = "failed"
            return state

        from docflow.validation.engine import validate

        start = time.monotonic()
        state.extraction_result = validate(state.extraction_result, self.validators)
        duration = (time.monotonic() - start) * 1000
        state.trace.add_event("validate", step_name=self.name, duration_ms=duration)
        return state


class Store:
    name = "store"

    def __init__(self, storage: Any = None):
        self.storage = storage

    async def execute(self, state: PipelineState) -> PipelineState:
        if self.storage is None:
            return state

        start = time.monotonic()
        if state.document:
            await self.storage.save_document(state.document)
        if state.extraction_result:
            await self.storage.save_result(state.extraction_result)
        await self.storage.save_trace(state.trace)
        duration = (time.monotonic() - start) * 1000
        state.trace.add_event("store", step_name=self.name, duration_ms=duration)
        return state
