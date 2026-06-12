from __future__ import annotations

import asyncio
import base64
import io
import json
import uuid

from pydantic import BaseModel

from docflow.constants import DEFAULT_DPI
from docflow.documents.models import Document
from docflow.errors import SchemaExtractionError
from docflow.extraction.evidence import attach_evidence
from docflow.extraction.llm.base import LLMAdapter
from docflow.extraction.models import ExtractedField, ExtractionResult, FieldTrust
from docflow.extraction.prompts import (
    JSON_REPAIR_PROMPT,
    build_extraction_prompt,
    build_vision_extraction_prompt,
)
from docflow.extraction.scoring import (
    compute_document_ocr_confidence,
    compute_field_consensus,
    compute_field_ocr_confidence,
)
from docflow.observability.traces import Trace

JSON_MODE = {"type": "json_object"}


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


async def _parse_json_with_retry(
    llm: LLMAdapter,
    content: str,
    messages: list[dict],
) -> dict:
    cleaned = _strip_markdown_fences(content)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    retry_messages = [
        *messages,
        {"role": "assistant", "content": content},
        {"role": "user", "content": JSON_REPAIR_PROMPT},
    ]
    try:
        retry_response = await llm.complete(
            retry_messages, temperature=0.0, response_format=JSON_MODE,
        )
        return json.loads(_strip_markdown_fences(retry_response.content))
    except (json.JSONDecodeError, Exception) as exc:
        raise SchemaExtractionError(
            f"Failed to parse LLM response as JSON after retry: {exc}"
        ) from exc


def _generate_temperatures(n: int, mean: float = 0.3, spread: float = 0.15) -> list[float]:
    if n == 1:
        return [mean]
    step = (spread * 2) / (n - 1)
    return [round(max(0.0, min(1.0, mean - spread + i * step)), 3) for i in range(n)]


DECIDER_SYSTEM_PROMPT = """You are a data extraction judge. You will receive multiple candidate \
extractions of the same document, each produced independently by a different LLM instance.

Your job is to compare all candidates field by field and produce the single best extraction.

Rules:
1. For each field, pick the value that appears most consistently across candidates.
2. If candidates disagree, prefer the value that has stronger evidence (exact quote from source).
3. If a field has the same value in all candidates, keep it — that is high confidence.
4. For confidence, set it based on agreement: 1.0 if all agree, 0.7 if majority agrees, \
0.4 if split.
5. Return the same JSON format: {"data": {...}, "evidence": {...}}
6. Evidence confidence should reflect the cross-candidate agreement, not just one instance."""


def _build_decider_prompt(
    schema: type[BaseModel],
    candidates: list[dict],
    document_text: str,
) -> list[dict]:
    field_desc_lines = []
    json_schema = schema.model_json_schema()
    for name, prop in json_schema.get("properties", {}).items():
        field_desc_lines.append(f"- {name}: {prop.get('type', 'string')}")

    parts = ["## Schema Fields\n" + "\n".join(field_desc_lines) + "\n"]
    parts.append(f"## Document Text (for reference)\n{document_text[:3000]}\n")

    for i, candidate in enumerate(candidates):
        parts.append(f"## Candidate {i + 1}\n```json\n{json.dumps(candidate, indent=2)}\n```\n")

    parts.append(
        f"Compare all {len(candidates)} candidates. Produce the single best extraction. "
        "Return JSON with 'data' and 'evidence' keys."
    )

    return [
        {"role": "system", "content": DECIDER_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(parts)},
    ]


def _normalize_value(value: object) -> str:
    s = str(value).strip().lower()
    for ch in "$€£¥,":
        s = s.replace(ch, "")
    return s


def _value_found_in_source(value: object, document: Document) -> bool:
    if value is None:
        return False
    normalized = _normalize_value(value)
    if not normalized:
        return False
    doc_text = _normalize_value(document.raw_text)
    return normalized in doc_text


def _compute_agreement(
    field_name: str, candidates: list[dict],
) -> tuple[str, float]:
    values = []
    for c in candidates:
        data = c.get("data", c)
        if field_name in data:
            values.append(_normalize_value(data[field_name]))
    if not values:
        return "0/0", 0.0
    most_common = max(set(values), key=values.count)
    agree_count = values.count(most_common)
    ratio = agree_count / len(values)
    return f"{agree_count}/{len(values)}", round(ratio, 4)


def _build_result(
    document: Document,
    schema: type[BaseModel],
    parsed: dict,
    model_name: str,
    trace: Trace | None,
    candidates: list[dict] | None = None,
    scoring: str = "qualitative",
    n_instances: int = 1,
) -> ExtractionResult:
    raw_data = parsed.get("data", parsed)
    evidence_map = parsed.get("evidence", {})

    try:
        validated = schema.model_validate(raw_data)
        data_dict = validated.model_dump()
    except Exception as exc:
        raise SchemaExtractionError(
            f"LLM output does not match schema: {exc}"
        ) from exc

    # Confidence scores must never break extraction: any failure degrades
    # to None and a trace event.
    try:
        doc_ocr = compute_document_ocr_confidence(document)
    except Exception as exc:
        doc_ocr = None
        if trace:
            trace.add_event(
                "ocr_confidence_error", step_name="extraction", error=str(exc),
            )

    fields: dict[str, ExtractedField] = {}
    for field_name, value in data_dict.items():
        evidence_hints = evidence_map.get(field_name, {})
        evidences = attach_evidence(document, field_name, value, evidence_hints)

        field_ocr = None
        if doc_ocr is not None:
            try:
                field_ocr = compute_field_ocr_confidence(
                    document,
                    value,
                    hint_text=evidence_hints.get("text", "") if evidence_hints else "",
                    hint_page=evidence_hints.get("page") if evidence_hints else None,
                )
            except Exception as exc:
                if trace:
                    trace.add_event(
                        "ocr_confidence_error", step_name="extraction",
                        field=field_name, error=str(exc),
                    )

        field_consensus = None
        if candidates is not None and len(candidates) > 1:
            try:
                field_consensus = compute_field_consensus(
                    value, field_name, candidates, n_instances,
                )
            except Exception as exc:
                if trace:
                    trace.add_event(
                        "consensus_error", step_name="extraction",
                        field=field_name, error=str(exc),
                    )

        found_in_source = _value_found_in_source(value, document)
        is_valid = True
        has_consensus = candidates is not None and len(candidates) > 1

        if has_consensus:
            agreement, agreement_ratio = _compute_agreement(field_name, candidates)
        else:
            agreement = ""
            agreement_ratio = 0.0

        is_unanimous = agreement_ratio == 1.0 if has_consensus else False
        auto_accept = is_unanimous and found_in_source and is_valid if has_consensus else found_in_source and is_valid

        if scoring == "quantitative":
            source_bonus = 0.5 if found_in_source else 0.0
            valid_bonus = 0.1 if is_valid else 0.0
            if has_consensus:
                score = round(agreement_ratio * 0.4 + source_bonus + valid_bonus, 4)
            else:
                score = round(source_bonus + valid_bonus, 4)
            confidence = score
        else:
            score = 1.0 if auto_accept else 0.0
            confidence = 1.0 if auto_accept else 0.5 if found_in_source else 0.2

        explanation_parts: list[str] = []
        if has_consensus:
            explanation_parts.append(f"Agreement: {agreement} ({agreement_ratio:.0%})")
        else:
            explanation_parts.append("Single agent (no consensus)")
        explanation_parts.append(f"Found in source: {found_in_source}")
        if scoring == "quantitative":
            explanation_parts.append(f"Score: {score:.0%}")
        elif auto_accept:
            explanation_parts.append("Auto-accept: yes")
        else:
            if has_consensus and not is_unanimous:
                explanation_parts.append("Needs review: disagreement across runs")
            elif not found_in_source:
                explanation_parts.append("Needs review: value not found in source")

        trust = FieldTrust(
            agreement=agreement,
            agreement_ratio=agreement_ratio,
            found_in_source=found_in_source,
            valid=is_valid,
            auto_accept=auto_accept,
            score=score,
            explanation="; ".join(explanation_parts),
        )

        fields[field_name] = ExtractedField(
            value=value,
            confidence=confidence,
            trust=trust,
            ocr=field_ocr,
            consensus=field_consensus,
            evidence=evidences,
            validation_status="pending",
        )

    overall_conf = (
        sum(f.confidence for f in fields.values()) / len(fields) if fields else 0.0
    )

    return ExtractionResult(
        document_id=document.id,
        schema_name=schema.__name__,
        data=data_dict,
        fields=fields,
        confidence=overall_conf,
        ocr=doc_ocr,
        needs_review=False,
        trace_id=trace.trace_id if trace else str(uuid.uuid4()),
        model_name=model_name,
    )



async def _single_llm_call(
    llm: LLMAdapter,
    messages: list[dict],
    temperature: float,
) -> dict | None:
    try:
        response = await llm.complete(
            messages, temperature=temperature, response_format=JSON_MODE,
        )
        parsed = json.loads(_strip_markdown_fences(response.content))
        return {"parsed": parsed, "model": response.model, "usage": response.usage}
    except Exception:
        return None


async def _run_multi(
    llm: LLMAdapter,
    document: Document,
    schema: type[BaseModel],
    messages: list[dict],
    trace: Trace | None,
    start: float,
    n_instances: int,
    temperatures: list[float] | None,
    scoring: str = "qualitative",
) -> ExtractionResult:
    import time

    temps = temperatures or _generate_temperatures(n_instances)
    if len(temps) != n_instances:
        temps = _generate_temperatures(n_instances)

    tasks = [_single_llm_call(llm, messages, t) for t in temps]
    raw_results = await asyncio.gather(*tasks)

    candidates: list[dict] = []
    for r in raw_results:
        if r is not None:
            candidates.append(r["parsed"])

    if not candidates:
        raise SchemaExtractionError(
            f"All {n_instances} extraction instances failed"
        )

    candidate_duration_ms = (time.monotonic() - start) * 1000
    if trace:
        trace.add_event(
            "multi_extract_candidates",
            step_name="extraction",
            duration_ms=candidate_duration_ms,
            n_instances=n_instances,
            n_succeeded=len(candidates),
            temperatures=temps,
        )

    if len(candidates) == 1:
        first_model = ""
        for r in raw_results:
            if r is not None:
                first_model = r["model"]
                break
        return _build_result(document, schema, candidates[0], first_model, trace, scoring=scoring)

    decider_messages = _build_decider_prompt(schema, candidates, document.raw_text)

    try:
        decider_response = await llm.complete(
            decider_messages, temperature=0.0, response_format=JSON_MODE,
        )
    except Exception as exc:
        raise SchemaExtractionError(f"Decider LLM call failed: {exc}") from exc

    total_duration_ms = (time.monotonic() - start) * 1000
    if trace:
        trace.add_event(
            "multi_extract_decider",
            step_name="extraction",
            duration_ms=total_duration_ms - candidate_duration_ms,
            model=decider_response.model,
        )

    decider_parsed = await _parse_json_with_retry(
        llm, decider_response.content, decider_messages,
    )
    return _build_result(
        document, schema, decider_parsed, decider_response.model, trace,
        candidates=candidates, scoring=scoring, n_instances=n_instances,
    )


class ExtractionEngine:
    """Text-based extraction. Requires parsed document with text."""

    def __init__(self, llm: LLMAdapter, context: str | None = None):
        self.llm = llm
        self.context = context

    async def extract(
        self,
        document: Document,
        schema: type[BaseModel],
        trace: Trace | None = None,
        mode: str = "single",
        n_instances: int = 5,
        temperatures: list[float] | None = None,
        scoring: str = "qualitative",
    ) -> ExtractionResult:
        import time

        start = time.monotonic()
        page_texts = [p.text for p in document.pages] if document.pages else None
        messages = build_extraction_prompt(
            schema, document.raw_text, page_texts, context=self.context,
        )

        if mode == "multi":
            return await _run_multi(
                self.llm, document, schema, messages, trace, start,
                n_instances=n_instances, temperatures=temperatures,
                scoring=scoring,
            )

        try:
            response = await self.llm.complete(
                messages, temperature=0.0, response_format=JSON_MODE,
            )
        except Exception as exc:
            raise SchemaExtractionError(f"LLM extraction failed: {exc}") from exc

        duration_ms = (time.monotonic() - start) * 1000
        if trace:
            trace.add_event(
                "llm_call", step_name="extraction",
                duration_ms=duration_ms, model=response.model, usage=response.usage,
            )

        parsed = await _parse_json_with_retry(self.llm, response.content, messages)
        return _build_result(document, schema, parsed, response.model, trace, scoring=scoring)


class VisionExtractionEngine:
    """Vision-based extraction. Renders PDF pages to images and sends them to a vision LLM.

    Automatically runs Tesseract OCR on the rendered images to populate
    document blocks with bounding boxes and confidence scores. This enriches
    evidence grounding without requiring a separate Parse step.
    """

    def __init__(self, llm: LLMAdapter, dpi: int = DEFAULT_DPI, context: str | None = None):
        self.llm = llm
        self.dpi = dpi
        self.context = context

    async def _render_pages(self, file_path: str) -> list:
        from docflow.rendering.renderer import render_all_pages

        return await render_all_pages(file_path, dpi=self.dpi)

    @staticmethod
    def _encode_images(images: list) -> list[str]:
        encoded: list[str] = []
        for img in images:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            encoded.append(base64.b64encode(buf.getvalue()).decode("ascii"))
        return encoded

    @staticmethod
    async def _enrich_document_with_ocr(
        document: Document, images: list, dpi: int = DEFAULT_DPI,
    ) -> None:
        from docflow.documents.models import Page
        from docflow.ocr.base import blocks_to_points
        from docflow.ocr.tesseract import TesseractOCR

        ocr = TesseractOCR(preprocess_steps=[])
        scale = 72.0 / dpi
        pages: list[Page] = []
        for i, image in enumerate(images):
            ocr_result = await ocr.ocr(image)
            pages.append(
                Page(
                    page_number=i,
                    width=float(image.width) * scale,
                    height=float(image.height) * scale,
                    blocks=blocks_to_points(ocr_result.blocks, dpi),
                    text=ocr_result.text,
                )
            )
        document.pages = pages
        document.raw_text = "\n\n".join(p.text for p in pages)
        document.metadata.page_count = len(pages)

    async def extract(
        self,
        document: Document,
        schema: type[BaseModel],
        trace: Trace | None = None,
        mode: str = "single",
        n_instances: int = 5,
        temperatures: list[float] | None = None,
        scoring: str = "qualitative",
    ) -> ExtractionResult:
        import time

        start = time.monotonic()

        images = await self._render_pages(document.metadata.file_path)
        images_b64 = self._encode_images(images)

        render_ms = (time.monotonic() - start) * 1000
        if trace:
            trace.add_event(
                "vision_render",
                step_name="extraction",
                duration_ms=render_ms,
                n_pages=len(images_b64),
                dpi=self.dpi,
            )

        ocr_start = time.monotonic()
        await self._enrich_document_with_ocr(document, images, dpi=self.dpi)
        ocr_ms = (time.monotonic() - ocr_start) * 1000
        if trace:
            trace.add_event(
                "vision_ocr_enrichment",
                step_name="extraction",
                duration_ms=ocr_ms,
                n_pages=len(images),
            )

        messages = build_vision_extraction_prompt(schema, images_b64, context=self.context)

        if mode == "multi":
            return await _run_multi(
                self.llm, document, schema, messages, trace, start,
                n_instances=n_instances, temperatures=temperatures,
                scoring=scoring,
            )

        try:
            response = await self.llm.complete(
                messages, temperature=0.0, response_format=JSON_MODE,
            )
        except Exception as exc:
            raise SchemaExtractionError(f"Vision LLM extraction failed: {exc}") from exc

        duration_ms = (time.monotonic() - start) * 1000
        if trace:
            trace.add_event(
                "vision_llm_call", step_name="extraction",
                duration_ms=duration_ms, model=response.model, usage=response.usage,
            )

        parsed = await _parse_json_with_retry(self.llm, response.content, messages)

        return _build_result(document, schema, parsed, response.model, trace, scoring=scoring)


HYBRID_DECIDER_SYSTEM_PROMPT = """You are a data extraction judge with vision capabilities. \
You will receive page images of the original document and multiple candidate extractions \
produced by independent approaches: some read the document as images (vision), others read \
OCR text (text).

Your job is to look at the document images, compare all candidates field by field, and \
produce the single best extraction.

Rules:
1. USE THE IMAGES to verify candidate values — look at the actual document.
2. For each field, check which candidate value matches what you see in the images.
3. If candidates agree, keep the value — that is high confidence.
4. If candidates disagree, trust what you see in the images over any single candidate.
5. For confidence, set 1.0 if all agree and you confirm in the image, 0.7 if majority \
agrees, 0.4 if you had to pick based on your own reading.
6. Return the same JSON format: {"data": {...}, "evidence": {...}}"""


def _build_hybrid_decider_prompt(
    schema: type[BaseModel],
    candidates: list[dict],
    candidate_labels: list[str],
    images_base64: list[str],
) -> list[dict]:
    field_desc_lines = []
    json_schema = schema.model_json_schema()
    for name, prop in json_schema.get("properties", {}).items():
        field_desc_lines.append(f"- {name}: {prop.get('type', 'string')}")

    text_parts = ["## Schema Fields\n" + "\n".join(field_desc_lines) + "\n\n"]

    for i, (candidate, label) in enumerate(
        zip(candidates, candidate_labels, strict=False)
    ):
        text_parts.append(
            f"## Candidate {i + 1} ({label})\n"
            f"```json\n{json.dumps(candidate, indent=2)}\n```\n"
        )

    text_parts.append(
        f"Compare all {len(candidates)} candidates against the document images below. "
        "Produce the single best extraction. "
        "Return JSON with 'data' and 'evidence' keys."
    )

    content_parts: list[dict] = [{"type": "text", "text": "\n".join(text_parts)}]
    for _i, img_b64 in enumerate(images_base64):
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
        })

    return [
        {"role": "system", "content": HYBRID_DECIDER_SYSTEM_PROMPT},
        {"role": "user", "content": content_parts},
    ]


class HybridExtractionEngine:
    """Hybrid extraction: runs vision and text agents in parallel, then a vision decider.

    Renders pages to images and runs Tesseract OCR once (shared). Then:
    - N vision LLM calls (page images at varied temperatures)
    - N text LLM calls (OCR markdown at varied temperatures)
    - 1 vision decider call that sees page images + all candidates
    """

    def __init__(self, llm: LLMAdapter, dpi: int = DEFAULT_DPI, context: str | None = None):
        self.llm = llm
        self.dpi = dpi
        self.context = context

    async def extract(
        self,
        document: Document,
        schema: type[BaseModel],
        trace: Trace | None = None,
        n_instances: int = 5,
        temperatures: list[float] | None = None,
        scoring: str = "qualitative",
    ) -> ExtractionResult:
        import time

        start = time.monotonic()

        from docflow.rendering.renderer import render_all_pages

        images = await render_all_pages(document.metadata.file_path, dpi=self.dpi)

        images_b64: list[str] = []
        for img in images:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            images_b64.append(base64.b64encode(buf.getvalue()).decode("ascii"))

        render_ms = (time.monotonic() - start) * 1000
        if trace:
            trace.add_event(
                "hybrid_render", step_name="extraction",
                duration_ms=render_ms, n_pages=len(images), dpi=self.dpi,
            )

        ocr_start = time.monotonic()
        await VisionExtractionEngine._enrich_document_with_ocr(document, images, dpi=self.dpi)
        ocr_ms = (time.monotonic() - ocr_start) * 1000
        if trace:
            trace.add_event(
                "hybrid_ocr_enrichment", step_name="extraction",
                duration_ms=ocr_ms, n_pages=len(images),
            )

        vision_messages = build_vision_extraction_prompt(
            schema, images_b64, context=self.context,
        )
        page_texts = [p.text for p in document.pages] if document.pages else None
        text_messages = build_extraction_prompt(
            schema, document.raw_text, page_texts, context=self.context,
        )

        temps = temperatures or _generate_temperatures(n_instances)
        if len(temps) != n_instances:
            temps = _generate_temperatures(n_instances)

        vision_tasks = [_single_llm_call(self.llm, vision_messages, t) for t in temps]
        text_tasks = [_single_llm_call(self.llm, text_messages, t) for t in temps]
        all_results = await asyncio.gather(*vision_tasks, *text_tasks)

        candidates: list[dict] = []
        candidate_labels: list[str] = []
        for i, r in enumerate(all_results):
            if r is not None:
                candidates.append(r["parsed"])
                candidate_labels.append("vision" if i < n_instances else "text")

        candidates_ms = (time.monotonic() - start) * 1000
        if trace:
            trace.add_event(
                "hybrid_candidates", step_name="extraction",
                duration_ms=candidates_ms,
                n_vision=n_instances, n_text=n_instances,
                n_succeeded=len(candidates), temperatures=temps,
            )

        if not candidates:
            raise SchemaExtractionError(
                f"All {n_instances * 2} hybrid extraction instances failed"
            )

        if len(candidates) == 1:
            first_model = ""
            for r in all_results:
                if r is not None:
                    first_model = r["model"]
                    break
            return _build_result(document, schema, candidates[0], first_model, trace, scoring=scoring)

        decider_messages = _build_hybrid_decider_prompt(
            schema, candidates, candidate_labels, images_b64,
        )

        try:
            decider_response = await self.llm.complete(
                decider_messages, temperature=0.0, response_format=JSON_MODE,
            )
        except Exception as exc:
            raise SchemaExtractionError(
                f"Hybrid decider LLM call failed: {exc}"
            ) from exc

        total_ms = (time.monotonic() - start) * 1000
        if trace:
            trace.add_event(
                "hybrid_decider", step_name="extraction",
                duration_ms=total_ms - candidates_ms, model=decider_response.model,
            )

        decider_parsed = await _parse_json_with_retry(
            self.llm, decider_response.content, decider_messages,
        )

        return _build_result(
            document, schema, decider_parsed, decider_response.model, trace,
            candidates=candidates, scoring=scoring, n_instances=n_instances * 2,
        )
