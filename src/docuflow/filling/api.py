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
    FillingResult,
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
from docuflow.filling.writer import write_acroform, write_overlay
from docuflow.observability.traces import Trace


async def fill_pdf_form_async(
    path: str,
    data: BaseModel | Mapping[str, Any],
    output_path: str | None = None,
    *,
    strategy: FillStrategy = "auto",
    match_by: MatchStrategy = "auto",
    field_map: Mapping[str, Any] | None = None,
    formats: Mapping[str, str | Callable[[Any], Any]] | None = None,
    flatten: bool = False,
    detect_blank_spaces: bool = False,
    blank_detection_mode: BlankDetectionMode = "heuristic",
    llm: Any = None,
    model: str = "openai/gpt-4o",
    llm_kwargs: Mapping[str, Any] | None = None,
    vision_dpi: int = DEFAULT_DPI,
    min_detection_confidence: float = 0.5,
    skip_none: bool = True,
    unmatched: UnmatchedPolicy = "warn",
    overflow: OverflowPolicy = "shrink",
) -> FillingResult:
    """Fill a PDF with values from a Pydantic instance or mapping."""
    return await _fill_pdf_form(
        path,
        data,
        output_path=output_path,
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
    strategy: FillStrategy = "auto",
    match_by: MatchStrategy = "auto",
    field_map: Mapping[str, Any] | None = None,
    formats: Mapping[str, str | Callable[[Any], Any]] | None = None,
    flatten: bool = False,
    detect_blank_spaces: bool = False,
    blank_detection_mode: BlankDetectionMode = "heuristic",
    llm: Any = None,
    model: str = "openai/gpt-4o",
    llm_kwargs: Mapping[str, Any] | None = None,
    vision_dpi: int = DEFAULT_DPI,
    min_detection_confidence: float = 0.5,
    skip_none: bool = True,
    unmatched: UnmatchedPolicy = "warn",
    overflow: OverflowPolicy = "shrink",
) -> FillingResult:
    """Synchronously fill a PDF and return a FillingResult."""
    return run_sync(
        _fill_pdf_form(
            path,
            data,
            output_path=output_path,
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
    strategy: FillStrategy = "auto",
    match_by: MatchStrategy = "auto",
    field_map: Mapping[str, Any] | None = None,
    formats: Mapping[str, str | Callable[[Any], Any]] | None = None,
    flatten: bool = False,
    detect_blank_spaces: bool = False,
    blank_detection_mode: BlankDetectionMode = "heuristic",
    llm: Any = None,
    model: str = "openai/gpt-4o",
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
            if plan.errors:
                _copy_input_if_needed(input_path, resolved_output)
            elif plan.assignments:
                plan.warnings.extend(
                    write_acroform(
                        input_path,
                        resolved_output,
                        plan.assignments,
                        flatten=flatten,
                    )
                )
            else:
                plan.errors.append("No PDF form fields were assigned values.")
                _copy_input_if_needed(input_path, resolved_output)
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
            if plan.errors:
                _copy_input_if_needed(input_path, resolved_output)
            elif plan.placements:
                plan.warnings.extend(
                    write_overlay(
                        input_path,
                        resolved_output,
                        plan,
                        overflow=overflow,
                    )
                )
            else:
                plan.errors.append("No static PDF overlay placements were assigned values.")
                _copy_input_if_needed(input_path, resolved_output)

        result.fields = plan.fields
        result.pdf_fields = plan.pdf_fields
        result.unmapped_model_fields = plan.unmapped_model_fields
        result.unmapped_pdf_fields = plan.unmapped_pdf_fields
        result.warnings = plan.warnings
        result.errors = plan.errors
        result.success = not plan.errors and any(
            field.status == "filled" for field in result.fields.values()
        )
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


async def _detect_overlay_field_map(
    *,
    input_path: Path,
    data: BaseModel | Mapping[str, Any],
    mode: BlankDetectionMode,
    llm: Any = None,
    model: str = "openai/gpt-4o",
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


def _default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}-filled{input_path.suffix}")


def _copy_input_if_needed(input_path: Path, output_path: Path) -> None:
    if input_path.resolve() == output_path.resolve():
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_path, output_path)
