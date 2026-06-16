from __future__ import annotations

import shutil
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from docuflow._sync import run_sync
from docuflow.constants import DEFAULT_DPI
from docuflow.filling.detector import detect_blank_field_map
from docuflow.filling.inspector import inspect_pdf_form
from docuflow.filling.llm_detector import detect_blank_field_map_llm
from docuflow.filling.models import (
    BlankDetectionMode,
    DocxFillStrategy,
    FillingResult,
    FillPlan,
    FillStrategy,
    MatchStrategy,
    OverflowPolicy,
    UnmatchedPolicy,
)
from docuflow.filling.planner import (
    build_acroform_plan,
    build_overlay_plan,
    collect_data_fields,
    dump_data,
    schema_name_for,
)
from docuflow.filling.review import evaluate_fill_review
from docuflow.filling.writer import write_acroform, write_overlay
from docuflow.observability.traces import Trace


async def fill_pdf_form_async(
    path: str,
    data: BaseModel | Mapping[str, Any],
    output_path: str | None = None,
    *,
    document_id: str = "",
    review: bool = False,
    strategy: FillStrategy = "auto",
    match_by: MatchStrategy = "auto",
    field_map: Mapping[str, Any] | None = None,
    formats: Mapping[str, str | Callable[[Any], Any]] | None = None,
    flatten: bool = False,
    detect_blank_spaces: bool = False,
    blank_detection_mode: BlankDetectionMode = "heuristic",
    llm: Any = None,
    model: str = "gemini/gemini-2.5-flash",
    llm_kwargs: Mapping[str, Any] | None = None,
    vision_dpi: int = DEFAULT_DPI,
    min_detection_confidence: float = 0.5,
    skip_none: bool = True,
    unmatched: UnmatchedPolicy = "warn",
    overflow: OverflowPolicy = "shrink",
) -> FillingResult:
    """Fill a PDF with values from a Pydantic instance or mapping.

    Args:
        path: Input PDF path.
        data: Pydantic model instance or mapping used to fill the form.
        output_path: Optional output PDF path. Defaults to a sibling ``filled`` file.
        document_id: Optional document identifier.
        review: If ``True``, prepare a fill without writing it yet.
        strategy: Form filling strategy (``auto``, ``acroform``, ``overlay``).
        match_by: How to match model fields to PDF fields.
        field_map: Explicit field placements or AcroForm mapping.
        formats: Optional field-format overrides.
        flatten: Flatten AcroForm widgets after fill when supported.
        detect_blank_spaces: Enable blank-space detection for overlay filling.
        blank_detection_mode: Heuristic, LLM, or hybrid blank detection.
        llm: Optional LLM adapter for blank detection.
        model: Model used for LLM-assisted blank detection.
        llm_kwargs: Extra LLM kwargs.
        vision_dpi: Render DPI used by visual detection.
        min_detection_confidence: Minimum confidence for visual blank detection.
        skip_none: Skip ``None`` values from ``data``.
        unmatched: Policy for unmatched fields.
        overflow: Overflow policy for overlay filling.

    Returns:
        FillingResult: Planned or committed fill result.
    """
    return await _fill_pdf_form(
        path,
        data,
        output_path=output_path,
        document_id=document_id,
        review=review,
        strategy=strategy,
        match_by=match_by,
        field_map=field_map,
        formats=formats,
        flatten=flatten,
        detect_blank_spaces=detect_blank_spaces,
        blank_detection_mode=blank_detection_mode,
        llm=llm,
        model=model,
        llm_kwargs=llm_kwargs,
        vision_dpi=vision_dpi,
        min_detection_confidence=min_detection_confidence,
        skip_none=skip_none,
        unmatched=unmatched,
        overflow=overflow,
    )


def fill_pdf_form(
    path: str,
    data: BaseModel | Mapping[str, Any],
    output_path: str | None = None,
    *,
    document_id: str = "",
    review: bool = False,
    strategy: FillStrategy = "auto",
    match_by: MatchStrategy = "auto",
    field_map: Mapping[str, Any] | None = None,
    formats: Mapping[str, str | Callable[[Any], Any]] | None = None,
    flatten: bool = False,
    detect_blank_spaces: bool = False,
    blank_detection_mode: BlankDetectionMode = "heuristic",
    llm: Any = None,
    model: str = "gemini/gemini-2.5-flash",
    llm_kwargs: Mapping[str, Any] | None = None,
    vision_dpi: int = DEFAULT_DPI,
    min_detection_confidence: float = 0.5,
    skip_none: bool = True,
    unmatched: UnmatchedPolicy = "warn",
    overflow: OverflowPolicy = "shrink",
) -> FillingResult:
    """Synchronously fill a PDF and return a FillingResult.

    Args:
        path: Input PDF path.
        data: Pydantic model instance or mapping used to fill the form.
        output_path: Optional output PDF path. Defaults to a sibling ``filled`` file.
        document_id: Optional document identifier.
        review: If ``True``, prepare a fill without writing it yet.
        strategy: Form filling strategy (``auto``, ``acroform``, ``overlay``).
        match_by: How to match model fields to PDF fields.
        field_map: Explicit field placements or AcroForm mapping.
        formats: Optional field-format overrides.
        flatten: Flatten AcroForm widgets after fill when supported.
        detect_blank_spaces: Enable blank-space detection for overlay filling.
        blank_detection_mode: Heuristic, LLM, or hybrid blank detection.
        llm: Optional LLM adapter for blank detection.
        model: Model used for LLM-assisted blank detection.
        llm_kwargs: Extra LLM kwargs.
        vision_dpi: Render DPI used by visual detection.
        min_detection_confidence: Minimum confidence for visual blank detection.
        skip_none: Skip ``None`` values from ``data``.
        unmatched: Policy for unmatched fields.
        overflow: Overflow policy for overlay filling.

    Returns:
        FillingResult: Planned or committed fill result.
    """
    return run_sync(
        _fill_pdf_form(
            path,
            data,
            output_path=output_path,
            document_id=document_id,
            review=review,
            strategy=strategy,
            match_by=match_by,
            field_map=field_map,
            formats=formats,
            flatten=flatten,
            detect_blank_spaces=detect_blank_spaces,
            blank_detection_mode=blank_detection_mode,
            llm=llm,
            model=model,
            llm_kwargs=llm_kwargs,
            vision_dpi=vision_dpi,
            min_detection_confidence=min_detection_confidence,
            skip_none=skip_none,
            unmatched=unmatched,
            overflow=overflow,
        )
    )


async def _fill_pdf_form(
    path: str,
    data: BaseModel | Mapping[str, Any],
    output_path: str | None = None,
    *,
    document_id: str = "",
    review: bool = False,
    strategy: FillStrategy = "auto",
    match_by: MatchStrategy = "auto",
    field_map: Mapping[str, Any] | None = None,
    formats: Mapping[str, str | Callable[[Any], Any]] | None = None,
    flatten: bool = False,
    detect_blank_spaces: bool = False,
    blank_detection_mode: BlankDetectionMode = "heuristic",
    llm: Any = None,
    model: str = "gemini/gemini-2.5-flash",
    llm_kwargs: Mapping[str, Any] | None = None,
    vision_dpi: int = DEFAULT_DPI,
    min_detection_confidence: float = 0.5,
    skip_none: bool = True,
    unmatched: UnmatchedPolicy = "warn",
    overflow: OverflowPolicy = "shrink",
) -> FillingResult:
    input_path = Path(path)
    resolved_output = Path(output_path) if output_path else _default_output_path(input_path)
    trace = Trace()
    result = FillingResult(
        input_path=str(input_path),
        document_id=document_id,
        output_path=str(resolved_output),
        schema_name=schema_name_for(data),
        data=dump_data(data, skip_none=skip_none),
        trace_id=trace.trace_id,
        trace=trace,
    )

    start = time.monotonic()
    try:
        selected_strategy = _select_strategy(
            input_path,
            strategy,
            field_map,
            detect_blank_spaces=detect_blank_spaces,
        )
        result.strategy = selected_strategy
        trace.add_event("fill_plan", step_name="fill_form", strategy=selected_strategy)

        if selected_strategy == "acroform":
            pdf_fields = inspect_pdf_form(input_path)
            plan = build_acroform_plan(
                pdf_fields=pdf_fields,
                data=data,
                field_map=field_map,
                match_by=match_by,
                formats=formats,
                skip_none=skip_none,
                unmatched=unmatched,
            )
        else:
            detected_field_names: set[str] = set()
            overlay_field_map = field_map
            detection_warnings: list[str] = []
            if overlay_field_map is None and detect_blank_spaces:
                overlay_field_map, detection_warnings = await _detect_overlay_field_map(
                    input_path=input_path,
                    data=data,
                    mode=blank_detection_mode,
                    llm=llm,
                    model=model,
                    llm_kwargs=llm_kwargs,
                    vision_dpi=vision_dpi,
                    min_detection_confidence=min_detection_confidence,
                    skip_none=skip_none,
                    trace=trace,
                )
                detected_field_names = set(overlay_field_map)
                trace.add_event(
                    "blank_detection",
                    step_name="fill_form",
                    detected_fields=len(detected_field_names),
                )

            plan = build_overlay_plan(
                data=data,
                field_map=overlay_field_map,
                formats=formats,
                skip_none=skip_none,
                unmatched=unmatched,
            )
            if detection_warnings:
                plan.warnings = [*detection_warnings, *plan.warnings]
            for field_name in detected_field_names:
                if field_name in plan.fields:
                    placement = plan.fields[field_name].placement
                    source = placement.source if placement is not None else ""
                    plan.fields[field_name].method = (
                        "llm_detected_blank" if source == "llm" else "auto_detected_blank"
                    )

        # Populate the result from the plan before deciding whether to write.
        result.fields = plan.fields
        result.pdf_fields = plan.pdf_fields
        result.unmapped_model_fields = plan.unmapped_model_fields
        result.unmapped_pdf_fields = plan.unmapped_pdf_fields
        result.warnings = plan.warnings
        result.errors = plan.errors
        result.flatten = flatten
        result.overflow = overflow

        has_writable = any(f.status == "filled" for f in result.fields.values())
        if not plan.errors and not has_writable:
            kind = (
                "PDF form field"
                if selected_strategy == "acroform"
                else "static PDF overlay placement"
            )
            plan.errors.append(f"No {kind}s were assigned values.")

        if review:
            # Defer the write: run review heuristics and leave the result pending.
            result.review_reasons = evaluate_fill_review(result) if not plan.errors else []
            result.needs_review = bool(result.review_reasons)
        elif plan.errors:
            _copy_input_if_needed(input_path, resolved_output)
            result.warnings.append(
                f"Output at '{resolved_output}' is an unmodified copy of the input "
                "— no fields were written. Check result.errors for details."
            )
        else:
            result.warnings.extend(_write_from_result(result))
            result.committed = True

        result.success = not result.errors and has_writable
    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        trace.add_event("error", step_name="fill_form", error=str(exc))
    finally:
        duration = (time.monotonic() - start) * 1000
        trace.add_event(
            "fill_form",
            step_name="fill_form",
            duration_ms=duration,
            success=result.success,
        )
        trace.complete()

    if unmatched == "error" and result.errors:
        raise ValueError("; ".join(result.errors))
    return result


async def commit_fill_async(result: FillingResult, *, force: bool = False) -> FillingResult:
    """Write an approved (reviewed) fill to its output PDF.

    Args:
        result: Filling result to commit.
        force: Write even if the result has not been approved yet.

    Returns:
        FillingResult: The same result marked as committed.
    """
    if result.committed:
        raise ValueError("This filling result has already been committed.")
    if result.review_status == "rejected":
        raise ValueError("Cannot commit a rejected filling result.")
    if not force and result.review_status != "approved":
        raise ValueError(
            "commit_fill requires an approved result. Call result.approve(...) "
            "first, or pass force=True."
        )
    if result.errors:
        raise ValueError(f"Cannot commit a result with errors: {'; '.join(result.errors)}")

    result.warnings.extend(_write_from_result(result))
    result.committed = True
    result.success = True
    return result


def commit_fill(result: FillingResult, *, force: bool = False) -> FillingResult:
    """Synchronous version of :func:`commit_fill_async`.

    Args:
        result: Filling result to commit.
        force: Write even if the result has not been approved yet.

    Returns:
        FillingResult: The same result marked as committed.
    """
    return run_sync(commit_fill_async(result, force=force))


def _write_from_result(result: FillingResult) -> list[str]:
    """Write the PDF from a result's planned fields (used for immediate and deferred writes)."""
    input_path = Path(result.input_path)
    output_path = Path(result.output_path)
    filled = {name: f for name, f in result.fields.items() if f.status == "filled"}
    if not filled:
        _copy_input_if_needed(input_path, output_path)
        return [
            f"Output at '{output_path}' is an unmodified copy of the input "
            "— no fields were written. Check result.errors for details."
        ]

    if result.strategy == "acroform":
        assignments = {
            f.target_name: f.formatted_value for f in filled.values() if f.target_name
        }
        return write_acroform(input_path, output_path, assignments, flatten=result.flatten)

    if result.strategy == "content_controls":
        from docuflow.filling.docx_writer import write_content_controls
        return write_content_controls(input_path, output_path, result)

    if result.strategy == "template":
        from docuflow.filling.docx_writer import write_template
        return write_template(input_path, output_path, result)

    placements = {
        name: f.placement for name, f in filled.items() if f.placement is not None
    }
    plan = FillPlan(strategy="overlay", placements=placements, fields=result.fields)
    return write_overlay(input_path, output_path, plan, overflow=result.overflow)


async def _detect_overlay_field_map(
    *,
    input_path: Path,
    data: BaseModel | Mapping[str, Any],
    mode: BlankDetectionMode,
    llm: Any = None,
    model: str = "gemini/gemini-2.5-flash",
    llm_kwargs: Mapping[str, Any] | None = None,
    vision_dpi: int = DEFAULT_DPI,
    min_detection_confidence: float = 0.5,
    skip_none: bool = True,
    trace: Trace | None = None,
) -> tuple[dict[str, Any], list[str]]:
    if mode == "heuristic":
        return detect_blank_field_map(input_path, data, skip_none=skip_none)

    if mode == "llm":
        return await detect_blank_field_map_llm(
            input_path,
            data,
            llm=llm,
            model=model,
            llm_kwargs=llm_kwargs,
            dpi=vision_dpi,
            min_confidence=min_detection_confidence,
            skip_none=skip_none,
            trace=trace,
        )

    heuristic_map, heuristic_warnings = detect_blank_field_map(
        input_path,
        data,
        skip_none=skip_none,
    )
    data_fields = collect_data_fields(data, skip_none=skip_none)
    missing = [field.name for field in data_fields if field.name not in heuristic_map]
    if not missing:
        return heuristic_map, heuristic_warnings

    llm_map, llm_warnings = await detect_blank_field_map_llm(
        input_path,
        data,
        llm=llm,
        model=model,
        llm_kwargs=llm_kwargs,
        dpi=vision_dpi,
        min_confidence=min_detection_confidence,
        skip_none=skip_none,
        trace=trace,
    )
    return {**llm_map, **heuristic_map}, [*heuristic_warnings, *llm_warnings]


def _select_strategy(
    input_path: Path,
    strategy: FillStrategy,
    field_map: Mapping[str, Any] | None,
    *,
    detect_blank_spaces: bool = False,
) -> str:
    if strategy in ("acroform", "overlay"):
        return strategy

    try:
        if inspect_pdf_form(input_path):
            return "acroform"
    except ImportError:
        raise
    except Exception as exc:
        if field_map:
            return "overlay"
        raise ValueError(f"Could not inspect PDF form fields: {exc}") from exc

    return "overlay" if field_map or detect_blank_spaces else "acroform"


async def fill_docx_form_async(
    path: str,
    data: BaseModel | Mapping[str, Any],
    output_path: str | None = None,
    *,
    document_id: str = "",
    review: bool = False,
    strategy: DocxFillStrategy = "auto",
    formats: Mapping[str, str | Callable[[Any], Any]] | None = None,
    flatten: bool = False,
    skip_none: bool = True,
    unmatched: UnmatchedPolicy = "warn",
) -> FillingResult:
    """Fill a DOCX form (content controls or Jinja2 template) and return a FillingResult.

    Args:
        path: Input DOCX path.
        data: Pydantic model instance or mapping used to fill the form.
        output_path: Optional output DOCX path.
        document_id: Optional document identifier.
        review: If ``True``, prepare a fill without writing it yet.
        strategy: DOCX fill strategy (``auto``, ``content_controls``, ``template``).
        formats: Optional field-format overrides.
        flatten: Flatten content controls after fill.
        skip_none: Skip ``None`` values from ``data``.
        unmatched: Policy for unmatched fields.

    Returns:
        FillingResult: Planned or committed fill result.
    """
    return await _fill_docx_form(
        path,
        data,
        output_path=output_path,
        document_id=document_id,
        review=review,
        strategy=strategy,
        formats=formats,
        flatten=flatten,
        skip_none=skip_none,
        unmatched=unmatched,
    )


def fill_docx_form(
    path: str,
    data: BaseModel | Mapping[str, Any],
    output_path: str | None = None,
    *,
    document_id: str = "",
    review: bool = False,
    strategy: DocxFillStrategy = "auto",
    formats: Mapping[str, str | Callable[[Any], Any]] | None = None,
    flatten: bool = False,
    skip_none: bool = True,
    unmatched: UnmatchedPolicy = "warn",
) -> FillingResult:
    """Synchronous version of :func:`fill_docx_form_async`.

    Args:
        path: Input DOCX path.
        data: Pydantic model instance or mapping used to fill the form.
        output_path: Optional output DOCX path.
        document_id: Optional document identifier.
        review: If ``True``, prepare a fill without writing it yet.
        strategy: DOCX fill strategy (``auto``, ``content_controls``, ``template``).
        formats: Optional field-format overrides.
        flatten: Flatten content controls after fill.
        skip_none: Skip ``None`` values from ``data``.
        unmatched: Policy for unmatched fields.

    Returns:
        FillingResult: Planned or committed fill result.
    """
    return run_sync(
        _fill_docx_form(
            path,
            data,
            output_path=output_path,
            document_id=document_id,
            review=review,
            strategy=strategy,
            formats=formats,
            flatten=flatten,
            skip_none=skip_none,
            unmatched=unmatched,
        )
    )


async def _fill_docx_form(
    path: str,
    data: BaseModel | Mapping[str, Any],
    output_path: str | None = None,
    *,
    document_id: str = "",
    review: bool = False,
    strategy: DocxFillStrategy = "auto",
    formats: Mapping[str, str | Callable[[Any], Any]] | None = None,
    flatten: bool = False,
    skip_none: bool = True,
    unmatched: UnmatchedPolicy = "warn",
) -> FillingResult:
    from docuflow.filling.docx_planner import plan_docx_fill

    input_path = Path(path)
    resolved_output = Path(output_path) if output_path else _default_output_path(input_path)
    trace = Trace()
    result = FillingResult(
        input_path=str(input_path),
        document_id=document_id,
        output_path=str(resolved_output),
        schema_name=schema_name_for(data),
        data=dump_data(data, skip_none=skip_none),
        trace_id=trace.trace_id,
        trace=trace,
    )

    import time
    start = time.monotonic()
    try:
        plan, docx_fields, resolved_strategy = plan_docx_fill(
            input_path,
            data,
            strategy=strategy,
            formats=formats,
            skip_none=skip_none,
            unmatched=unmatched,
        )
        result.strategy = resolved_strategy  # type: ignore[assignment]
        trace.add_event("fill_plan", step_name="fill_form", strategy=resolved_strategy)

        result.fields = plan.fields
        result.pdf_fields = docx_fields
        result.unmapped_model_fields = plan.unmapped_model_fields
        result.unmapped_pdf_fields = plan.unmapped_pdf_fields
        result.warnings = plan.warnings
        result.errors = plan.errors
        result.flatten = flatten

        has_writable = any(f.status == "filled" for f in result.fields.values())
        if not plan.errors and not has_writable:
            plan.errors.append(
                f"No DOCX {resolved_strategy.replace('_', ' ')} fields were assigned values."
            )

        if review:
            result.review_reasons = evaluate_fill_review(result) if not plan.errors else []
            result.needs_review = bool(result.review_reasons)
        elif plan.errors:
            _copy_input_if_needed(input_path, resolved_output)
            result.warnings.append(
                f"Output at '{resolved_output}' is an unmodified copy of the input "
                "— no fields were written. Check result.errors for details."
            )
        else:
            result.warnings.extend(_write_from_result(result))
            result.committed = True

        result.success = not result.errors and has_writable
    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        trace.add_event("error", step_name="fill_form", error=str(exc))
    finally:
        duration = (time.monotonic() - start) * 1000
        trace.add_event(
            "fill_form",
            step_name="fill_form",
            duration_ms=duration,
            success=result.success,
        )
        trace.complete()

    if unmatched == "error" and result.errors:
        raise ValueError("; ".join(result.errors))
    return result


def _default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}-filled{input_path.suffix}")


def _copy_input_if_needed(input_path: Path, output_path: Path) -> None:
    if input_path.resolve() == output_path.resolve():
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_path, output_path)
