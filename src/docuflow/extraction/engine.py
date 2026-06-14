from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import uuid
from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel

from docuflow.constants import DEFAULT_DPI
from docuflow.documents.models import Document
from docuflow.errors import SchemaExtractionError
from docuflow.extraction.evidence import attach_evidence
from docuflow.extraction.llm.base import LLMAdapter
from docuflow.extraction.models import (
    ExtractedField,
    ExtractionResult,
    FieldTrust,
    TokenUsage,
)
from docuflow.extraction.prompts import (
    JSON_REPAIR_PROMPT,
    build_extraction_prompt,
    build_vision_extraction_prompt,
)
from docuflow.extraction.scoring import (
    compute_document_ocr_confidence,
    compute_field_consensus,
    compute_field_ocr_confidence,
)
from docuflow.observability.traces import Trace

JSON_MODE = {"type": "json_object"}
_MISSING = object()


class _UsageTracker:
    """Wraps an LLMAdapter and records the usage of every call, so a single
    aggregate can be attached to the ExtractionResult."""

    def __init__(self, llm: LLMAdapter):
        self._llm = llm
        self.usages: list[dict] = []

    async def complete(
        self,
        messages: list[dict],
        response_format: object = None,
        temperature: float = 0.0,
    ):
        response = await self._llm.complete(
            messages, response_format=response_format, temperature=temperature,
        )
        if response.usage:
            self.usages.append(response.usage)
        return response

    def total(self) -> TokenUsage | None:
        return TokenUsage.from_usages(self.usages)


def _usage_of(llm: object) -> TokenUsage | None:
    return llm.total() if isinstance(llm, _UsageTracker) else None


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


def _strip_optional(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _coerce_number_string(value: object, target_type: type) -> object:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value

    negative = text.startswith("(") and text.endswith(")")
    cleaned = text.strip("()")
    cleaned = cleaned.replace(",", "")
    for ch in "$€£¥%":
        cleaned = cleaned.replace(ch, "")
    cleaned = cleaned.strip()

    match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
    if not match:
        return value
    number_text = match.group(0)
    if negative and not number_text.startswith("-"):
        number_text = f"-{number_text}"

    try:
        if target_type is int:
            return int(float(number_text))
        return float(number_text)
    except ValueError:
        return value


def _coerce_bool_string(value: object) -> object:
    if not isinstance(value, str):
        return value
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "y", "1"}:
        return True
    if normalized in {"false", "no", "n", "0"}:
        return False
    return value


def _coerce_value_for_annotation(value: object, annotation: Any) -> object:
    annotation = _strip_optional(annotation)
    origin = get_origin(annotation)

    if value is None:
        return None

    if annotation in (float, int):
        return _coerce_number_string(value, annotation)

    if annotation is bool:
        return _coerce_bool_string(value)

    if origin is list:
        item_args = get_args(annotation)
        item_annotation = item_args[0] if item_args else Any
        if isinstance(value, list):
            return [
                _coerce_value_for_annotation(item, item_annotation)
                for item in value
            ]
        if isinstance(value, str) and _strip_optional(item_annotation) is str:
            return [value]
        return value

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if isinstance(value, dict):
            return _coerce_data_for_schema(annotation, value)
        return value

    return value


def _coerce_data_for_schema(
    schema: type[BaseModel],
    raw_data: dict[str, object],
) -> dict[str, object]:
    coerced = dict(raw_data)
    for field_name, field_info in schema.model_fields.items():
        if field_name not in coerced:
            continue
        coerced[field_name] = _coerce_value_for_annotation(
            coerced[field_name], field_info.annotation,
        )
    return coerced


def _validate_schema_data(
    schema: type[BaseModel],
    raw_data: object,
) -> tuple[dict[str, object], BaseModel]:
    if not isinstance(raw_data, dict):
        raise TypeError("LLM output data must be a JSON object")
    coerced = _coerce_data_for_schema(schema, raw_data)
    validated = schema.model_validate(coerced)
    return coerced, validated


def _empty_value_for_field(field_info: object) -> object:
    annotation = _strip_optional(getattr(field_info, "annotation", Any))
    origin = get_origin(annotation)
    if origin is list:
        return []
    return _MISSING


def _safe_schema_data_after_failed_repair(
    schema: type[BaseModel],
    raw_data: object,
) -> dict[str, object] | None:
    """Last-resort normalization for fields that are structurally unusable.

    LLMs sometimes collapse a table/list field into one long string. If the
    schema allows an empty list, prefer a schema-valid empty list over failing
    the whole extraction. Required scalars are never fabricated here.
    """
    if not isinstance(raw_data, dict):
        return None
    safe = _coerce_data_for_schema(schema, raw_data)
    changed = False
    for name, field_info in schema.model_fields.items():
        if name in safe:
            value = safe[name]
            annotation = _strip_optional(field_info.annotation)
            if get_origin(annotation) is list and not isinstance(value, list):
                safe[name] = []
                changed = True
        elif not field_info.is_required():
            empty = _empty_value_for_field(field_info)
            if empty is not _MISSING:
                safe[name] = empty
                changed = True
    return safe if changed else None


def _schema_validation_repair_prompt(
    schema: type[BaseModel],
    parsed: dict,
    validation_error: Exception,
) -> str:
    return (
        "Your previous JSON was valid JSON but did not match the required schema.\n"
        "Return ONLY a corrected JSON object with the same top-level shape:\n"
        '{"data": {...}, "evidence": {...}}\n\n'
        "Rules:\n"
        "- Preserve values that are already correct.\n"
        "- Fix only type/shape issues reported by validation.\n"
        "- Numbers must be JSON numbers without currency symbols, commas, or percent signs.\n"
        "- Arrays must be JSON arrays, never strings. If a table/list is present, split it into objects matching the item schema.\n"
        "- Objects must be JSON objects.\n"
        "- If a value cannot be corrected from the document/evidence, use null for optional fields or [] for list fields.\n"
        "- Keep original formatted snippets in evidence text.\n\n"
        f"## JSON Schema\n```json\n{json.dumps(schema.model_json_schema(), indent=2)}\n```\n\n"
        f"## Validation Error\n{validation_error}\n\n"
        f"## Previous JSON\n```json\n{json.dumps(parsed, indent=2, default=str)}\n```\n"
    )


async def _validate_or_repair_parsed(
    llm: LLMAdapter,
    schema: type[BaseModel],
    parsed: dict,
    messages: list[dict],
    trace: Trace | None,
) -> dict:
    raw_data = parsed.get("data", parsed)
    validation_error: Exception
    try:
        _coerced, validated = _validate_schema_data(schema, raw_data)
        return {**parsed, "data": validated.model_dump()}
    except Exception as first_exc:
        validation_error = first_exc
        if trace:
            trace.add_event(
                "schema_validation_repair",
                step_name="extraction",
                error=str(validation_error),
            )

    repair_messages = [
        *messages,
        {"role": "assistant", "content": json.dumps(parsed, default=str)},
        {
            "role": "user",
            "content": _schema_validation_repair_prompt(schema, parsed, validation_error),
        },
    ]
    try:
        repair_response = await llm.complete(
            repair_messages, temperature=0.0, response_format=JSON_MODE,
        )
        repaired = await _parse_json_with_retry(
            llm, repair_response.content, repair_messages,
        )
        raw_repaired = repaired.get("data", repaired)
        _coerced, validated = _validate_schema_data(schema, raw_repaired)
        if trace:
            trace.add_event(
                "schema_validation_repaired",
                step_name="extraction",
                model=repair_response.model,
            )
        return {**repaired, "data": validated.model_dump()}
    except Exception as repair_exc:
        safe_data = _safe_schema_data_after_failed_repair(schema, raw_data)
        if safe_data is not None:
            try:
                validated = schema.model_validate(safe_data)
                if trace:
                    trace.add_event(
                        "schema_validation_repair_fallback",
                        step_name="extraction",
                        error=str(repair_exc),
                    )
                return {**parsed, "data": validated.model_dump()}
            except Exception as fallback_exc:
                if trace:
                    trace.add_event(
                        "schema_validation_repair_fallback_failed",
                        step_name="extraction",
                        error=str(fallback_exc),
                    )
        raise SchemaExtractionError(
            f"LLM output does not match schema: {validation_error}"
        ) from repair_exc


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


def _value_found_in_source(value: object, doc_text_normalized: str) -> bool:
    if value is None:
        return False
    normalized = _normalize_value(value)
    if not normalized:
        return False
    return normalized in doc_text_normalized


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
    n_instances: int = 1,
    usage: TokenUsage | None = None,
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

    # Shared across all fields: the locator word stream and the normalized
    # document text are document-level artifacts — building them per field
    # is O(fields x document size) for nothing.
    try:
        from docuflow.documents.locate import build_stream

        stream = build_stream(document)
    except Exception:
        stream = None
    doc_text_normalized = _normalize_value(document.raw_text)

    fields: dict[str, ExtractedField] = {}
    for field_name, value in data_dict.items():
        evidence_hints = evidence_map.get(field_name, {})
        evidences = attach_evidence(
            document, field_name, value, evidence_hints, stream=stream,
        )

        field_ocr = None
        if doc_ocr is not None:
            try:
                field_ocr = compute_field_ocr_confidence(
                    document,
                    value,
                    hint_text=evidence_hints.get("text", "") if evidence_hints else "",
                    hint_page=evidence_hints.get("page") if evidence_hints else None,
                    stream=stream,
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

        found_in_source = _value_found_in_source(value, doc_text_normalized)
        is_valid = True
        has_consensus = candidates is not None and len(candidates) > 1

        if has_consensus:
            agreement, agreement_ratio = _compute_agreement(field_name, candidates)
        else:
            agreement = ""
            agreement_ratio = 0.0

        is_unanimous = agreement_ratio == 1.0 if has_consensus else False
        trust_gate = is_unanimous and found_in_source and is_valid if has_consensus else found_in_source and is_valid

        explanation_parts: list[str] = []
        if has_consensus:
            explanation_parts.append(f"Agreement: {agreement} ({agreement_ratio:.0%})")
        else:
            explanation_parts.append("Single agent (no consensus)")
        explanation_parts.append(f"Found in source: {found_in_source}")
        if trust_gate:
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
            trust_gate=trust_gate,
            explanation="; ".join(explanation_parts),
        )

        fields[field_name] = ExtractedField(
            value=value,
            trust=trust,
            ocr=field_ocr,
            consensus=field_consensus,
            evidence=evidences,
            validation_status="pending",
        )

    overall_conf = (
        sum(1.0 if (f.trust.trust_gate if f.trust else False) else 0.0 for f in fields.values()) / len(fields)
        if fields else 0.0
    )

    return ExtractionResult(
        document_id=document.id,
        schema_name=schema.__name__,
        data=data_dict,
        fields=fields,
        confidence=overall_conf,
        ocr=doc_ocr,
        usage=usage,
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


def _candidates_unanimous(candidates: list[dict]) -> bool:
    """True when every candidate extracted the same normalized value for
    every field. With unanimity the decider call adds nothing — any
    candidate IS the answer — so it can be skipped (latency and cost).

    Conservative by design: a field missing from any candidate, or any
    value difference, counts as disagreement and the decider runs.
    """
    datas = [c.get("data", c) for c in candidates]
    keys: set[str] = set()
    for d in datas:
        keys.update(d.keys())
    for key in keys:
        values = []
        for d in datas:
            if key not in d:
                return False
            values.append(_normalize_value(d[key]))
        if len(set(values)) > 1:
            return False
    return True


async def _run_multi(
    llm: LLMAdapter,
    document: Document,
    schema: type[BaseModel],
    messages: list[dict],
    trace: Trace | None,
    start: float,
    n_instances: int,
    temperatures: list[float] | None,
    pre_build: asyncio.Task | None = None,
) -> ExtractionResult:
    import time

    temps = temperatures or _generate_temperatures(n_instances)
    if len(temps) != n_instances:
        temps = _generate_temperatures(n_instances)

    tasks = [_single_llm_call(llm, messages, t) for t in temps]
    raw_results = await asyncio.gather(*tasks)

    # Work that was overlapped with the candidate calls (e.g. OCR
    # enrichment for evidence grounding) must finish before the document
    # is read for the decider prompt or result building.
    if pre_build is not None:
        await pre_build

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
        parsed = await _validate_or_repair_parsed(
            llm, schema, candidates[0], messages, trace,
        )
        return _build_result(
            document, schema, parsed, first_model, trace,
            usage=_usage_of(llm),
        )

    if _candidates_unanimous(candidates):
        if trace:
            trace.add_event(
                "decider_skipped", step_name="extraction",
                reason="all candidates unanimous", n_candidates=len(candidates),
            )
        first_model = next(
            (r["model"] for r in raw_results if r is not None), "",
        )
        parsed = await _validate_or_repair_parsed(
            llm, schema, candidates[0], messages, trace,
        )
        return _build_result(
            document, schema, parsed, first_model, trace,
            candidates=candidates, n_instances=n_instances,
            usage=_usage_of(llm),
        )

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
    decider_parsed = await _validate_or_repair_parsed(
        llm, schema, decider_parsed, decider_messages, trace,
    )
    return _build_result(
        document, schema, decider_parsed, decider_response.model, trace,
        candidates=candidates, n_instances=n_instances,
        usage=_usage_of(llm),
    )


class ExtractionEngine:
    """Text-based extraction. Requires parsed document with text."""

    def __init__(
        self,
        llm: LLMAdapter,
        context: str | None = None,
        normalize_output: bool = False,
    ):
        self.llm = llm
        self.context = context
        self.normalize_output = normalize_output

    async def extract(
        self,
        document: Document,
        schema: type[BaseModel],
        trace: Trace | None = None,
        mode: str = "single",
        n_instances: int = 5,
        temperatures: list[float] | None = None,
        shards: int | None = None,
    ) -> ExtractionResult:
        import time

        if shards and shards > 1:
            from docuflow.extraction.sharding import merge_shard_results, shard_schema

            sub_schemas = shard_schema(schema, shards)
            if len(sub_schemas) > 1:
                if trace:
                    trace.add_event(
                        "schema_sharding", step_name="extraction",
                        n_shards=len(sub_schemas),
                        fields_per_shard=[
                            len(s.model_fields) for s in sub_schemas
                        ],
                    )
                results = await asyncio.gather(*(
                    self.extract(
                        document, sub, trace=trace, mode=mode,
                        n_instances=n_instances, temperatures=temperatures,
                    )
                    for sub in sub_schemas
                ))
                return merge_shard_results(list(results), schema)

        start = time.monotonic()
        llm = _UsageTracker(self.llm)
        page_texts = [p.text for p in document.pages] if document.pages else None
        messages = build_extraction_prompt(
            schema,
            document.raw_text,
            page_texts,
            context=self.context,
            normalize_output=self.normalize_output,
        )

        if mode == "multi":
            return await _run_multi(
                llm, document, schema, messages, trace, start,
                n_instances=n_instances, temperatures=temperatures,
            )

        try:
            response = await llm.complete(
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

        parsed = await _parse_json_with_retry(llm, response.content, messages)
        parsed = await _validate_or_repair_parsed(
            llm, schema, parsed, messages, trace,
        )
        return _build_result(
            document, schema, parsed, response.model, trace,
            usage=llm.total(),
        )


class VisionExtractionEngine:
    """Vision-based extraction. Renders PDF pages to images and sends them to a vision LLM.

    Automatically runs Tesseract OCR on the rendered images to populate
    document blocks with bounding boxes and confidence scores. This enriches
    evidence grounding without requiring a separate Parse step.
    """

    def __init__(
        self,
        llm: LLMAdapter,
        dpi: int = DEFAULT_DPI,
        context: str | None = None,
        normalize_output: bool = False,
    ):
        self.llm = llm
        self.dpi = dpi
        self.context = context
        self.normalize_output = normalize_output

    async def _render_pages(self, file_path: str) -> list:
        from docuflow.rendering.renderer import render_all_pages

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
        from docuflow.documents.models import Page
        from docuflow.ocr.base import blocks_to_points
        from docuflow.ocr.tesseract import TesseractOCR

        ocr = TesseractOCR(preprocess_steps=[])
        scale = 72.0 / dpi
        # Pages OCR concurrently — the Tesseract executor runs 4 workers
        ocr_results = await asyncio.gather(*(ocr.ocr(image) for image in images))
        pages: list[Page] = [
            Page(
                page_number=i,
                width=float(image.width) * scale,
                height=float(image.height) * scale,
                blocks=blocks_to_points(ocr_result.blocks, dpi),
                text=ocr_result.text,
            )
            for i, (image, ocr_result) in enumerate(zip(images, ocr_results, strict=True))
        ]
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

        # The vision LLM reads images, not OCR text — OCR enrichment is only
        # needed for evidence grounding AFTER the response, so it overlaps
        # with the LLM call(s) instead of preceding them.
        ocr_start = time.monotonic()
        enrich_task = asyncio.ensure_future(
            self._enrich_document_with_ocr(document, images, dpi=self.dpi)
        )

        def _trace_enrichment() -> None:
            if trace:
                trace.add_event(
                    "vision_ocr_enrichment",
                    step_name="extraction",
                    duration_ms=(time.monotonic() - ocr_start) * 1000,
                    n_pages=len(images),
                    overlapped_with_llm=True,
                )

        messages = build_vision_extraction_prompt(
            schema,
            images_b64,
            context=self.context,
            normalize_output=self.normalize_output,
        )
        llm = _UsageTracker(self.llm)

        if mode == "multi":
            try:
                result = await _run_multi(
                    llm, document, schema, messages, trace, start,
                    n_instances=n_instances, temperatures=temperatures,
                    pre_build=enrich_task,
                )
            finally:
                if not enrich_task.done():
                    enrich_task.cancel()
            _trace_enrichment()
            return result

        try:
            response = await llm.complete(
                messages, temperature=0.0, response_format=JSON_MODE,
            )
        except Exception as exc:
            enrich_task.cancel()
            raise SchemaExtractionError(f"Vision LLM extraction failed: {exc}") from exc

        duration_ms = (time.monotonic() - start) * 1000
        if trace:
            trace.add_event(
                "vision_llm_call", step_name="extraction",
                duration_ms=duration_ms, model=response.model, usage=response.usage,
            )

        parsed = await _parse_json_with_retry(llm, response.content, messages)
        parsed = await _validate_or_repair_parsed(
            llm, schema, parsed, messages, trace,
        )

        await enrich_task
        _trace_enrichment()

        return _build_result(
            document, schema, parsed, response.model, trace,
            usage=llm.total(),
        )


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

    def __init__(
        self,
        llm: LLMAdapter,
        dpi: int = DEFAULT_DPI,
        context: str | None = None,
        normalize_output: bool = False,
    ):
        self.llm = llm
        self.dpi = dpi
        self.context = context
        self.normalize_output = normalize_output

    async def extract(
        self,
        document: Document,
        schema: type[BaseModel],
        trace: Trace | None = None,
        n_instances: int = 5,
        temperatures: list[float] | None = None,
    ) -> ExtractionResult:
        import time

        start = time.monotonic()

        from docuflow.rendering.renderer import render_all_pages

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

        temps = temperatures or _generate_temperatures(n_instances)
        if len(temps) != n_instances:
            temps = _generate_temperatures(n_instances)

        llm = _UsageTracker(self.llm)
        vision_messages = build_vision_extraction_prompt(
            schema,
            images_b64,
            context=self.context,
            normalize_output=self.normalize_output,
        )

        # Vision candidates need only the images — launch them immediately
        # and run OCR enrichment concurrently. Text candidates need the OCR
        # text, so they start as soon as enrichment completes.
        ocr_start = time.monotonic()
        enrich_task = asyncio.ensure_future(
            VisionExtractionEngine._enrich_document_with_ocr(
                document, images, dpi=self.dpi,
            )
        )
        vision_tasks = [
            asyncio.ensure_future(_single_llm_call(llm, vision_messages, t))
            for t in temps
        ]

        try:
            await enrich_task
        except Exception:
            for t in vision_tasks:
                t.cancel()
            raise
        ocr_ms = (time.monotonic() - ocr_start) * 1000
        if trace:
            trace.add_event(
                "hybrid_ocr_enrichment", step_name="extraction",
                duration_ms=ocr_ms, n_pages=len(images),
                overlapped_with_llm=True,
            )

        page_texts = [p.text for p in document.pages] if document.pages else None
        text_messages = build_extraction_prompt(
            schema,
            document.raw_text,
            page_texts,
            context=self.context,
            normalize_output=self.normalize_output,
        )
        text_tasks = [_single_llm_call(llm, text_messages, t) for t in temps]
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
            parsed = await _validate_or_repair_parsed(
                llm, schema, candidates[0], vision_messages, trace,
            )
            return _build_result(
                document, schema, parsed, first_model, trace,
                usage=llm.total(),
            )

        if _candidates_unanimous(candidates):
            if trace:
                trace.add_event(
                    "decider_skipped", step_name="extraction",
                    reason="all candidates unanimous",
                    n_candidates=len(candidates),
                )
            first_model = next(
                (r["model"] for r in all_results if r is not None), "",
            )
            parsed = await _validate_or_repair_parsed(
                llm, schema, candidates[0], vision_messages, trace,
            )
            return _build_result(
                document, schema, parsed, first_model, trace,
                candidates=candidates,
                n_instances=n_instances * 2, usage=llm.total(),
            )

        decider_messages = _build_hybrid_decider_prompt(
            schema, candidates, candidate_labels, images_b64,
        )

        try:
            decider_response = await llm.complete(
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
            llm, decider_response.content, decider_messages,
        )
        decider_parsed = await _validate_or_repair_parsed(
            llm, schema, decider_parsed, decider_messages, trace,
        )

        return _build_result(
            document, schema, decider_parsed, decider_response.model, trace,
            candidates=candidates, n_instances=n_instances * 2,
            usage=llm.total(),
        )
