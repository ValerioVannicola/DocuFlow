from __future__ import annotations

import base64
import io
import json
from typing import Any

from pydantic import BaseModel

from docuflow.documents.locate import _normalize
from docuflow.documents.models import BoundingBox, Document, Page
from docuflow.extraction.models import ExtractedField, ExtractionResult, FieldVerification


class VerificationPolicy(BaseModel):
    """When and how to zoom-and-verify weak fields.

    A field triggers verification when any explicit weakness signal fires:
    consensus below threshold, OCR span score below threshold, or the value
    couldn't be matched back to the OCR text at all. Verification renders
    the field's page at high DPI, crops around its highlight rect, and asks
    the vision LLM a focused question about just that region.
    """

    trigger_consensus_below: float = 0.7
    trigger_ocr_below: float = 0.6
    include_unmatched: bool = True
    max_fields: int = 5
    padding: float = 40.0  # crop padding around the rect, in page units
    dpi: int = 300
    apply_corrections: bool = True


VERIFIER_SYSTEM_PROMPT = """You are a document field verifier. You receive a zoomed-in \
image of a document region and a field that was extracted from it with low confidence.

Read the region carefully — it is rendered at high resolution exactly so you can \
distinguish characters like 0/O, 1/l/7, 5/S.

Return ONLY a JSON object:
{"value": <the value you read for the field>, "readable": true}

If the region does not contain the field or is unreadable, return:
{"value": null, "readable": false}"""


def _trigger_reason(field: ExtractedField, policy: VerificationPolicy) -> str | None:
    """Why this field needs verification — None when it doesn't."""
    if field.consensus is not None and (
        field.consensus.agreement_ratio < policy.trigger_consensus_below
    ):
        return (
            f"consensus {field.consensus.agreement} "
            f"({field.consensus.agreement_ratio:.0%}) below "
            f"{policy.trigger_consensus_below:.0%}"
        )
    if field.ocr is not None:
        if (
            field.ocr.score is not None
            and field.ocr.score < policy.trigger_ocr_below
        ):
            return (
                f"OCR span confidence {field.ocr.score:.2f} below "
                f"{policy.trigger_ocr_below}"
            )
        if policy.include_unmatched and field.ocr.match_method == "unmatched":
            return "value could not be matched back to the OCR text"
    return None


def _field_region(
    field: ExtractedField,
) -> tuple[int, BoundingBox | None] | None:
    """(page_number, bbox) to zoom into; bbox None means whole page.
    Returns None when there is no location information at all."""
    if field.ocr is not None and field.ocr.bbox is not None:
        return (field.ocr.page_number or 0, field.ocr.bbox)
    if field.ocr is not None and field.ocr.rects:
        rect = field.ocr.rects[0]
        return (rect.page_number, rect.bbox)
    for ev in field.evidence:
        if ev.bbox is not None:
            return (ev.page_number, ev.bbox)
        if ev.rects:
            return (ev.rects[0].page_number, ev.rects[0].bbox)
    if field.evidence:
        return (field.evidence[0].page_number, None)
    return None


def _crop_region(image: Any, bbox: BoundingBox, page: Page, padding: float) -> Any:
    """Crop the rendered page image to the bbox plus padding.

    The bbox and page dims share one coordinate space, so relative
    coordinates map onto the rendered image at any DPI.
    """
    if not page.width or not page.height:
        return image
    rel = bbox.to_relative(page.width, page.height)
    pad_x = padding / page.width
    pad_y = padding / page.height
    x0 = max(0.0, rel.x0 - pad_x) * image.width
    y0 = max(0.0, rel.y0 - pad_y) * image.height
    x1 = min(1.0, rel.x1 + pad_x) * image.width
    y1 = min(1.0, rel.y1 + pad_y) * image.height
    if x1 - x0 < 10 or y1 - y0 < 10:
        return image
    return image.crop((int(x0), int(y0), int(x1), int(y1)))


def _build_messages(
    field_name: str, field: ExtractedField, image: Any,
) -> list[dict]:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    text = (
        f"Field: {field_name}\n"
        f"Currently extracted value: {json.dumps(field.value, default=str)}\n\n"
        "Read this document region and return the correct value for the field. "
        'Respond ONLY with JSON: {"value": ..., "readable": true/false}'
    )
    return [
        {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                },
            ],
        },
    ]


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _validated_value(
    schema: type[BaseModel], result: ExtractionResult,
    field_name: str, new_value: Any,
) -> tuple[bool, Any]:
    """Coerce the verified value through the schema. (ok, canonical_value)."""
    try:
        candidate = {**result.data, field_name: new_value}
        validated = schema.model_validate(candidate)
        return True, validated.model_dump()[field_name]
    except Exception:
        return False, None


async def verify_result(
    document: Document,
    result: ExtractionResult,
    schema: type[BaseModel],
    llm: Any,
    policy: VerificationPolicy | None = None,
    trace: Any = None,
) -> int:
    """Zoom-and-verify weak fields in place. Returns the number of fields verified.

    Never raises for individual field failures — a verification that errors
    leaves the field untouched with a trace event.
    """
    policy = policy or VerificationPolicy()

    candidates: list[tuple[str, ExtractedField, str]] = []
    for name, field in result.fields.items():
        reason = _trigger_reason(field, policy)
        if reason is not None:
            candidates.append((name, field, reason))
    candidates = candidates[: policy.max_fields]
    if not candidates:
        return 0

    import asyncio

    from docuflow.rendering.renderer import render_page

    pages_by_number = {p.page_number: p for p in document.pages}
    n_verified = 0

    # Resolve regions and pre-render the needed pages once, then run all
    # verification calls concurrently — they are independent of each other.
    regions: list[tuple[str, Any, str, int, Any]] = []
    needed_pages: list[int] = []
    for name, field, reason in candidates:
        region = _field_region(field)
        if region is None:
            continue
        page_number, bbox = region
        regions.append((name, field, reason, page_number, bbox))
        if page_number not in needed_pages:
            needed_pages.append(page_number)

    rendered: dict[int, Any] = {}
    for page_number in needed_pages:
        try:
            rendered[page_number] = await render_page(
                document.metadata.file_path, page_number, dpi=policy.dpi,
            )
        except Exception as exc:
            if trace:
                trace.add_event(
                    "field_verification_error", step_name="verify_fields",
                    page=page_number, error=str(exc),
                )

    async def _ask(name: str, field: Any, page_number: int, bbox: Any):
        image = rendered[page_number]
        page = pages_by_number.get(page_number)
        if bbox is not None and page is not None:
            image = _crop_region(image, bbox, page, policy.padding)
        response = await llm.complete(
            _build_messages(name, field, image),
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        return json.loads(_strip_fences(response.content)), response

    regions = [r for r in regions if r[3] in rendered]
    outcomes = await asyncio.gather(
        *(_ask(name, field, pn, bbox) for name, field, _, pn, bbox in regions),
        return_exceptions=True,
    )

    for (name, field, reason, page_number, _bbox), outcome in zip(
        regions, outcomes, strict=True,
    ):
        if isinstance(outcome, BaseException):
            if trace:
                trace.add_event(
                    "field_verification_error", step_name="verify_fields",
                    field=name, error=str(outcome),
                )
            continue
        parsed, response = outcome

        readable = bool(parsed.get("readable", False))
        raw_value = parsed.get("value")
        usage = getattr(response, "usage", None) or {}

        if not readable or raw_value is None:
            field.verification = FieldVerification(
                verified=False, reason=reason,
                original_value=field.value, page_number=page_number,
            )
            n_verified += 1
            _merge_usage(result, usage)
            continue

        original = field.value
        agrees = _normalize(raw_value) == _normalize(original)
        applied = False

        if not agrees and policy.apply_corrections:
            ok, canonical = _validated_value(schema, result, name, raw_value)
            if ok:
                field.value = canonical
                result.data[name] = canonical
                applied = True

        field.verification = FieldVerification(
            verified=True,
            agrees=agrees,
            changed=applied,
            original_value=original,
            verified_value=raw_value,
            reason=reason,
            page_number=page_number,
        )
        if field.trust is not None and (agrees or applied):
            field.trust.trust_gate = True

        if trace:
            trace.add_event(
                "field_verification", step_name="verify_fields",
                field=name, reason=reason, agrees=agrees, changed=applied,
            )
        n_verified += 1
        _merge_usage(result, usage)

    if result.fields:
        result.confidence = sum(
            1.0 if (f.trust.trust_gate if f.trust else False) else 0.0
            for f in result.fields.values()
        ) / len(result.fields)

    return n_verified


def _merge_usage(result: ExtractionResult, usage: dict) -> None:
    if not usage:
        return
    from docuflow.extraction.models import TokenUsage

    result.usage = (result.usage or TokenUsage()).merged(usage)
