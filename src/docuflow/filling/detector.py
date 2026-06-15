from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from docuflow.documents.models import BoundingBox
from docuflow.filling.models import FieldPlacement
from docuflow.filling.planner import DataField, collect_data_fields, normalize_key

_MIN_BLANK_WIDTH = 40.0
_FIELD_HEIGHT = 16.0
_LABEL_LOOKBACK = 220.0
_LABEL_VERTICAL_TOLERANCE = 18.0
_MIN_MATCH_SCORE = 0.6
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "is",
    "no",
    "number",
    "of",
    "on",
    "the",
    "to",
    "value",
}


@dataclass(frozen=True)
class BlankCandidate:
    placement: FieldPlacement
    label_text: str
    source: str


def detect_blank_field_map(
    path: str | Path,
    data: BaseModel | Mapping[str, Any],
    *,
    skip_none: bool = True,
) -> tuple[dict[str, FieldPlacement], list[str]]:
    """Detect static blank-line placements and map them to data fields.

    This is intentionally heuristic and opt-in. It only uses PDF geometry and
    nearby label text; it never asks an LLM to infer values or locations.
    """
    pdfplumber = _require_pdfplumber()
    data_fields = collect_data_fields(data, skip_none=skip_none)
    warnings: list[str] = []
    candidates: list[BlankCandidate] = []

    with pdfplumber.open(str(path)) as pdf:
        for page_number, page in enumerate(pdf.pages):
            words = page.extract_words() or []
            candidates.extend(_line_candidates(page_number, page, words))
            candidates.extend(_rect_candidates(page_number, page, words))
            candidates.extend(_underscore_candidates(page_number, words))

    field_map: dict[str, FieldPlacement] = {}
    used_candidates: set[int] = set()

    for data_field in data_fields:
        best_index = -1
        best_score = 0.0
        for index, candidate in enumerate(candidates):
            if index in used_candidates:
                continue
            score = _score_candidate(data_field, candidate)
            if score > best_score:
                best_score = score
                best_index = index

        if best_index >= 0 and best_score >= _MIN_MATCH_SCORE:
            field_map[data_field.name] = candidates[best_index].placement
            used_candidates.add(best_index)

    warnings.append(
        "Automatic blank-space detection is opt-in and heuristic; review the generated PDF before use."
    )
    warnings.append(
        f"Detected {len(candidates)} blank candidate(s) and mapped "
        f"{len(field_map)}/{len(data_fields)} data field(s)."
    )
    if data_fields and not field_map:
        warnings.append(
            "No static blank spaces could be matched to the provided field names, aliases, or descriptions."
        )

    return field_map, warnings


def _require_pdfplumber() -> Any:
    try:
        import pdfplumber
    except ImportError as exc:
        raise ImportError(
            "Automatic blank-space detection requires pdfplumber. Install it with: "
            "pip install 'docuflow[forms]' or pip install 'docuflow[pdf,forms]'"
        ) from exc
    return pdfplumber


def _line_candidates(page_number: int, page: Any, words: list[dict[str, Any]]) -> list[BlankCandidate]:
    candidates: list[BlankCandidate] = []
    page_height = float(page.height)
    for line in getattr(page, "lines", []) or []:
        x0 = min(float(line.get("x0", 0.0)), float(line.get("x1", 0.0)))
        x1 = max(float(line.get("x0", 0.0)), float(line.get("x1", 0.0)))
        if x1 - x0 < _MIN_BLANK_WIDTH:
            continue
        y0 = float(line.get("y0", 0.0))
        y1 = float(line.get("y1", 0.0))
        if abs(y1 - y0) > 2.0:
            continue
        top = _line_top(line, page_height)
        placement = FieldPlacement(
            page_number=page_number,
            bbox=BoundingBox(
                x0=x0,
                y0=max(0.0, top - _FIELD_HEIGHT),
                x1=x1,
                y1=max(0.0, top - 1.0),
            ),
            source="heuristic",
            label_text=_label_for_blank(words, x0=x0, y=top),
            reason="Detected horizontal blank line with nearby label text.",
        )
        candidates.append(
            BlankCandidate(
                placement=placement,
                label_text=placement.label_text,
                source="line",
            )
        )
    return candidates


def _rect_candidates(page_number: int, page: Any, words: list[dict[str, Any]]) -> list[BlankCandidate]:
    candidates: list[BlankCandidate] = []
    for rect in getattr(page, "rects", []) or []:
        x0 = float(rect.get("x0", 0.0))
        x1 = float(rect.get("x1", 0.0))
        top = float(rect.get("top", 0.0))
        bottom = float(rect.get("bottom", top))
        width = x1 - x0
        height = bottom - top
        if width < _MIN_BLANK_WIDTH or height < 8.0 or height > 40.0:
            continue
        placement = FieldPlacement(
            page_number=page_number,
            bbox=BoundingBox(x0=x0 + 2.0, y0=top + 2.0, x1=x1 - 2.0, y1=bottom - 2.0),
            source="heuristic",
            label_text=_label_for_blank(words, x0=x0, y=(top + bottom) / 2),
            reason="Detected blank rectangle with nearby label text.",
        )
        candidates.append(
            BlankCandidate(
                placement=placement,
                label_text=placement.label_text,
                source="rect",
            )
        )
    return candidates


def _underscore_candidates(page_number: int, words: list[dict[str, Any]]) -> list[BlankCandidate]:
    candidates: list[BlankCandidate] = []
    for word in words:
        text = str(word.get("text", ""))
        if "___" not in text:
            continue
        x0 = float(word.get("x0", 0.0))
        x1 = float(word.get("x1", 0.0))
        top = float(word.get("top", 0.0))
        bottom = float(word.get("bottom", top + _FIELD_HEIGHT))
        if x1 - x0 < _MIN_BLANK_WIDTH:
            continue
        placement = FieldPlacement(
            page_number=page_number,
            bbox=BoundingBox(x0=x0, y0=top, x1=x1, y1=bottom),
            source="heuristic",
            label_text=_label_for_blank(words, x0=x0, y=(top + bottom) / 2),
            reason="Detected underscore blank with nearby label text.",
        )
        candidates.append(
            BlankCandidate(
                placement=placement,
                label_text=placement.label_text,
                source="underscores",
            )
        )
    return candidates


def _line_top(line: dict[str, Any], page_height: float) -> float:
    if "top" in line:
        return float(line["top"])
    y0 = float(line.get("y0", 0.0))
    y1 = float(line.get("y1", y0))
    return page_height - max(y0, y1)


def _label_for_blank(words: list[dict[str, Any]], *, x0: float, y: float) -> str:
    same_line = [
        word
        for word in words
        if float(word.get("x1", 0.0)) <= x0 + 2.0
        and float(word.get("x1", 0.0)) >= x0 - _LABEL_LOOKBACK
        and abs(_word_center_y(word) - y) <= _LABEL_VERTICAL_TOLERANCE
    ]
    same_line.sort(key=lambda word: float(word.get("x0", 0.0)))
    if same_line:
        return " ".join(str(word.get("text", "")) for word in same_line[-6:]).strip()

    above = [
        word
        for word in words
        if float(word.get("bottom", 0.0)) <= y
        and float(word.get("bottom", 0.0)) >= y - 40.0
        and float(word.get("x0", 0.0)) <= x0 + 40.0
        and float(word.get("x1", 0.0)) >= x0 - 40.0
    ]
    above.sort(key=lambda word: (float(word.get("top", 0.0)), float(word.get("x0", 0.0))))
    return " ".join(str(word.get("text", "")) for word in above[-6:]).strip()


def _word_center_y(word: dict[str, Any]) -> float:
    return (float(word.get("top", 0.0)) + float(word.get("bottom", 0.0))) / 2


def _score_candidate(data_field: DataField, candidate: BlankCandidate) -> float:
    if not candidate.label_text:
        return 0.0
    phrases = [data_field.name, *data_field.aliases]
    if data_field.description:
        phrases.append(data_field.description)
    return max((_score_phrase(phrase, candidate.label_text) for phrase in phrases), default=0.0)


def _score_phrase(phrase: str, label: str) -> float:
    phrase_norm = normalize_key(phrase)
    label_norm = normalize_key(label)
    if not phrase_norm or not label_norm:
        return 0.0
    if phrase_norm in label_norm or label_norm in phrase_norm:
        return 1.0

    phrase_tokens = _tokens(phrase)
    label_tokens = set(_tokens(label))
    if not phrase_tokens or not label_tokens:
        return 0.0
    overlap = sum(1 for token in phrase_tokens if token in label_tokens)
    return overlap / len(phrase_tokens)


def _tokens(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 1 and token not in _STOP_WORDS
    ]
