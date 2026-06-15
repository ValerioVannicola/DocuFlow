from __future__ import annotations

import time
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from docuflow.constants import DEFAULT_DPI
from docuflow.workflow.state import PipelineState


@runtime_checkable
class PipelineStep(Protocol):
    name: str

    async def execute(self, state: PipelineState) -> PipelineState: ...


class Ingest:
    name = "ingest"

    def __init__(self, path: str | None = None):
        self.path = path

    async def execute(self, state: PipelineState) -> PipelineState:
        from docuflow.ingestion.local import ingest_file

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
        if parser is None or parser == "pdfplumber":
            from docuflow.parsing.pdfplumber_parser import PdfplumberParser
            parser = PdfplumberParser()
        elif parser == "tesseract":
            from docuflow.parsing.tesseract_parser import TesseractParser
            parser = TesseractParser()
        elif parser == "docling":
            from docuflow.parsing.docling_parser import DoclingParser
            parser = DoclingParser()
        elif parser == "smart":
            from docuflow.parsing.smart_parser import SmartParser
            parser = SmartParser()
        elif parser == "azure-di":
            from docuflow.parsing.azure_di import AzureDocumentIntelligenceParser
            parser = AzureDocumentIntelligenceParser()
        elif parser == "textract":
            from docuflow.parsing.textract import TextractParser
            parser = TextractParser()
        elif parser == "google-docai":
            from docuflow.parsing.google_docai import GoogleDocumentAIParser
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

        from docuflow.privacy.anonymizer import Anonymizer

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
        schema_shards: int | None = None,
        normalize_output: bool = False,
    ):
        self._schema = schema
        self.llm = llm
        self.mode = mode
        self.n_instances = n_instances
        self.temperatures = temperatures
        self.context = context
        self.schema_shards = schema_shards
        self.normalize_output = normalize_output

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

        from docuflow.extraction.engine import ExtractionEngine

        engine = ExtractionEngine(
            llm=self.llm,
            context=self.context,
            normalize_output=self.normalize_output,
        )
        start = time.monotonic()
        state.extraction_result = await engine.extract(
            state.document, schema, trace=state.trace,
            mode=self.mode, n_instances=self.n_instances,
            temperatures=self.temperatures,
            shards=self.schema_shards,
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
        normalize_output: bool = False,
    ):
        self._schema = schema
        self.llm = llm
        self.mode = mode
        self.n_instances = n_instances
        self.temperatures = temperatures
        self.dpi = dpi
        self.context = context
        self.normalize_output = normalize_output

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

        from docuflow.extraction.engine import VisionExtractionEngine

        engine = VisionExtractionEngine(
            llm=self.llm,
            dpi=self.dpi,
            context=self.context,
            normalize_output=self.normalize_output,
        )
        start = time.monotonic()
        state.extraction_result = await engine.extract(
            state.document, schema, trace=state.trace,
            mode=self.mode, n_instances=self.n_instances,
            temperatures=self.temperatures,
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
        normalize_output: bool = False,
    ):
        self._schema = schema
        self.llm = llm
        self.n_instances = n_instances
        self.temperatures = temperatures
        self.dpi = dpi
        self.context = context
        self.normalize_output = normalize_output

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

        from docuflow.extraction.engine import HybridExtractionEngine

        engine = HybridExtractionEngine(
            llm=self.llm,
            dpi=self.dpi,
            context=self.context,
            normalize_output=self.normalize_output,
        )
        start = time.monotonic()
        state.extraction_result = await engine.extract(
            state.document, schema, trace=state.trace,
            n_instances=self.n_instances,
            temperatures=self.temperatures,
        )
        duration = (time.monotonic() - start) * 1000
        state.trace.add_event("extract_hybrid", step_name=self.name, duration_ms=duration)
        return state


class ExtractAuto:
    """Text extraction with automatic vision escalation.

    Expects a parsed document (use the smart parser). Evaluates OCR quality:
    if the text is trustworthy, runs normal text extraction; if OCR produced
    garbage or nothing (per the EscalationPolicy), re-reads the original file
    with the vision (or hybrid) engine instead.

    Escalation is disabled when `allow_escalation=False` — DocumentPipeline
    sets this when a privacy policy is configured, because vision sends raw
    page images to the LLM, bypassing anonymization.
    """

    name = "extract_auto"

    def __init__(
        self,
        schema: type[BaseModel] | None = None,
        llm: Any = None,
        mode: str = "single",
        n_instances: int = 5,
        temperatures: list[float] | None = None,
        dpi: int = DEFAULT_DPI,
        context: str | None = None,
        policy: Any = None,
        allow_escalation: bool = True,
        normalize_output: bool = False,
    ):
        self._schema = schema
        self.llm = llm
        self.mode = mode
        self.n_instances = n_instances
        self.temperatures = temperatures
        self.dpi = dpi
        self.context = context
        self.policy = policy
        self.allow_escalation = allow_escalation
        self.normalize_output = normalize_output

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

        from docuflow.extraction.escalation import evaluate_escalation

        escalate, reason = evaluate_escalation(state.document, self.policy)

        if escalate and not self.allow_escalation:
            state.trace.add_event(
                "vision_escalation_suppressed", step_name=self.name,
                reason=reason, cause="privacy policy configured",
            )
            escalate = False

        start = time.monotonic()
        if escalate:
            state.trace.add_event(
                "vision_escalation", step_name=self.name, reason=reason,
            )
            escalate_to = getattr(self.policy, "escalate_to", "vision")
            if escalate_to == "hybrid":
                from docuflow.extraction.engine import HybridExtractionEngine

                engine = HybridExtractionEngine(
                    llm=self.llm,
                    dpi=self.dpi,
                    context=self.context,
                    normalize_output=self.normalize_output,
                )
                result = await engine.extract(
                    state.document, schema, trace=state.trace,
                    n_instances=self.n_instances,
                    temperatures=self.temperatures,
                )
            else:
                from docuflow.extraction.engine import VisionExtractionEngine

                engine = VisionExtractionEngine(
                    llm=self.llm,
                    dpi=self.dpi,
                    context=self.context,
                    normalize_output=self.normalize_output,
                )
                result = await engine.extract(
                    state.document, schema, trace=state.trace,
                    mode=self.mode, n_instances=self.n_instances,
                    temperatures=self.temperatures,
                )
            result.escalated = True
            result.escalation_reason = reason
            state.extraction_result = result
        else:
            from docuflow.extraction.engine import ExtractionEngine

            engine = ExtractionEngine(
                llm=self.llm,
                context=self.context,
                normalize_output=self.normalize_output,
            )
            state.extraction_result = await engine.extract(
                state.document, schema, trace=state.trace,
                mode=self.mode, n_instances=self.n_instances,
                temperatures=self.temperatures,
            )

        duration = (time.monotonic() - start) * 1000
        state.trace.add_event(
            "extract_auto", step_name=self.name, duration_ms=duration,
            escalated=escalate,
        )
        return state


class VerifyFields:
    """Zoom-and-verify: re-read weak fields from a high-DPI crop of their
    page region with the vision LLM. Runs after extraction, before review.

    Requires a vision-capable model (the same adapter used for extraction).
    """

    name = "verify_fields"

    def __init__(
        self,
        schema: type[BaseModel] | None = None,
        llm: Any = None,
        policy: Any = None,
    ):
        self._schema = schema
        self.llm = llm
        self.policy = policy

    async def execute(self, state: PipelineState) -> PipelineState:
        if state.extraction_result is None:
            state.errors.append("No extraction result to verify")
            state.status = "failed"
            return state
        if state.document is None:
            return state

        schema = self._schema or state.metadata.get("schema")
        if schema is None:
            return state

        from docuflow.extraction.verify import verify_result

        start = time.monotonic()
        n_verified = await verify_result(
            state.document, state.extraction_result, schema,
            self.llm, policy=self.policy, trace=state.trace,
        )
        duration = (time.monotonic() - start) * 1000
        state.trace.add_event(
            "verify_fields", step_name=self.name,
            duration_ms=duration, n_verified=n_verified,
        )
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

        from docuflow.extraction.models import ReviewVerdict

        document_text = state.document.raw_text if state.document else ""

        import asyncio

        start = time.monotonic()

        # LLM reviewers are independent — run them concurrently. Sync rules
        # are cheap and run inline; reasons keep the original rule order.
        async_rules = [r for r in self.rules if hasattr(r, "acheck")]
        async_results = await asyncio.gather(*(
            rule.acheck(state.extraction_result, document_text=document_text)
            for rule in async_rules
        ))
        async_iter = iter(async_results)

        reasons: list[str] = []
        for rule in self.rules:
            if hasattr(rule, "acheck"):
                result = next(async_iter)
                if isinstance(result, ReviewVerdict):
                    state.extraction_result.review_verdicts.append(result)
                    if result.usage:
                        from docuflow.extraction.models import TokenUsage

                        current = state.extraction_result.usage or TokenUsage()
                        state.extraction_result.usage = current.merged(result.usage)
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

        from docuflow.validation.engine import validate

        start = time.monotonic()
        state.extraction_result = validate(state.extraction_result, self.validators)
        duration = (time.monotonic() - start) * 1000
        state.trace.add_event("validate", step_name=self.name, duration_ms=duration)
        return state


class FillForm:
    """Fill a PDF form with trusted data from a Pydantic model instance or mapping."""

    name = "fill_form"

    def __init__(
        self,
        data: Any = None,
        output_path: str | None = None,
        review: bool = False,
        strategy: str = "auto",
        match_by: str = "auto",
        field_map: dict[str, Any] | None = None,
        formats: dict[str, Any] | None = None,
        flatten: bool = False,
        detect_blank_spaces: bool = False,
        blank_detection_mode: str = "heuristic",
        llm: Any = None,
        model: str = "gemini/gemini-2.5-flash",
        llm_kwargs: dict[str, Any] | None = None,
        vision_dpi: int = DEFAULT_DPI,
        min_detection_confidence: float = 0.5,
        skip_none: bool = True,
        unmatched: str = "warn",
        overflow: str = "shrink",
    ):
        self.data = data
        self.output_path = output_path
        self.review = review
        self.strategy = strategy
        self.match_by = match_by
        self.field_map = field_map
        self.formats = formats
        self.flatten = flatten
        self.detect_blank_spaces = detect_blank_spaces
        self.blank_detection_mode = blank_detection_mode
        self.llm = llm
        self.model = model
        self.llm_kwargs = llm_kwargs
        self.vision_dpi = vision_dpi
        self.min_detection_confidence = min_detection_confidence
        self.skip_none = skip_none
        self.unmatched = unmatched
        self.overflow = overflow

    async def execute(self, state: PipelineState) -> PipelineState:
        if state.document is None:
            state.errors.append("No document to fill")
            state.status = "failed"
            return state

        data = self.data or state.metadata.get("fill_data") or state.metadata.get("data")
        if data is None:
            state.errors.append("No data provided for PDF form filling")
            state.status = "failed"
            return state

        from docuflow.filling.api import fill_pdf_form_async

        start = time.monotonic()
        state.filling_result = await fill_pdf_form_async(
            state.document.metadata.file_path,
            data,
            output_path=self.output_path or state.metadata.get("output_path"),
            document_id=state.document.id,
            review=self.review,
            strategy=self.strategy,
            match_by=self.match_by,
            field_map=self.field_map,
            formats=self.formats,
            flatten=self.flatten,
            detect_blank_spaces=self.detect_blank_spaces,
            blank_detection_mode=self.blank_detection_mode,
            llm=self.llm,
            model=self.model,
            llm_kwargs=self.llm_kwargs,
            vision_dpi=self.vision_dpi,
            min_detection_confidence=self.min_detection_confidence,
            skip_none=self.skip_none,
            unmatched=self.unmatched,
            overflow=self.overflow,
        )
        state.filling_result.document_id = state.document.id
        duration = (time.monotonic() - start) * 1000
        state.trace.add_event(
            "fill_form",
            step_name=self.name,
            duration_ms=duration,
            success=state.filling_result.success,
        )

        if not state.filling_result.success:
            state.errors.extend(state.filling_result.errors)
            state.status = "failed"
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
        if state.filling_result and hasattr(self.storage, "save_filling_result"):
            await self.storage.save_filling_result(state.filling_result)
        await self.storage.save_trace(state.trace)
        duration = (time.monotonic() - start) * 1000
        state.trace.add_event("store", step_name=self.name, duration_ms=duration)
        return state
