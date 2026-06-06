from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from docflow._sync import run_sync
from docflow.extraction.models import ExtractionResult


class FieldScore(BaseModel):
    field_name: str
    total: int = 0
    exact_match: int = 0
    fuzzy_match: int = 0
    wrong: int = 0
    missing: int = 0
    hallucinated: int = 0
    accuracy: float = 0.0


class EvalReport(BaseModel):
    total_documents: int = 0
    field_scores: dict[str, FieldScore] = Field(default_factory=dict)
    overall_accuracy: float = 0.0
    hallucination_rate: float = 0.0
    correction_rate: float = 0.0
    field_accuracy: dict[str, float] = Field(default_factory=dict)


def _normalize(value: object) -> str:
    s = str(value).strip().lower()
    s = re.sub(r"[,$€£¥%]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _fuzzy_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return True
    return bool(na in nb or nb in na)


def _extract_ground_truth(result: ExtractionResult) -> dict[str, Any]:
    truth: dict[str, Any] = {}
    for field_name, field in result.fields.items():
        truth[field_name] = field.value
    return truth


class EvalHarness:
    def __init__(self) -> None:
        self._ground_truth: list[tuple[str, dict[str, Any]]] = []

    def add_ground_truth(self, result: ExtractionResult) -> None:
        truth = _extract_ground_truth(result)
        doc_id = result.document_id
        self._ground_truth.append((doc_id, truth))

    def add_ground_truth_dict(self, document_id: str, values: dict[str, Any]) -> None:
        self._ground_truth.append((document_id, values))

    @property
    def ground_truth_count(self) -> int:
        return len(self._ground_truth)

    def compare_results(
        self,
        predicted: list[ExtractionResult],
        ground_truth: list[ExtractionResult] | None = None,
    ) -> EvalReport:
        if ground_truth is not None:
            self._ground_truth = []
            for gt in ground_truth:
                self.add_ground_truth(gt)

        pred_by_id: dict[str, ExtractionResult] = {r.document_id: r for r in predicted}

        all_fields: list[str] = []
        seen: set[str] = set()
        for _, truth in self._ground_truth:
            for fname in truth:
                if fname not in seen:
                    all_fields.append(fname)
                    seen.add(fname)

        scores: dict[str, FieldScore] = {
            fname: FieldScore(field_name=fname) for fname in all_fields
        }

        total_fields = 0
        total_correct = 0
        total_hallucinated = 0
        total_corrected = 0

        for doc_id, truth in self._ground_truth:
            pred = pred_by_id.get(doc_id)
            if pred is None:
                for fname in truth:
                    if fname in scores:
                        scores[fname].total += 1
                        scores[fname].missing += 1
                continue

            for fname, expected in truth.items():
                if fname not in scores:
                    scores[fname] = FieldScore(field_name=fname)

                score = scores[fname]
                score.total += 1
                total_fields += 1

                pred_field = pred.fields.get(fname)
                if pred_field is None or pred_field.value is None:
                    score.missing += 1
                    continue

                pred_value = pred_field.value
                expected_norm = _normalize(expected)
                pred_norm = _normalize(pred_value)

                if expected_norm == pred_norm:
                    score.exact_match += 1
                    total_correct += 1
                elif _fuzzy_match(str(expected), str(pred_value)):
                    score.fuzzy_match += 1
                    total_correct += 1
                else:
                    has_evidence = bool(pred_field.evidence)
                    found_in_source = (
                        pred_field.trust and pred_field.trust.found_in_source
                    ) if pred_field.trust else has_evidence
                    if not found_in_source:
                        score.hallucinated += 1
                        total_hallucinated += 1
                    else:
                        score.wrong += 1

                if pred_field.corrected:
                    total_corrected += 1

        for _fname, score in scores.items():
            correct = score.exact_match + score.fuzzy_match
            score.accuracy = correct / score.total if score.total > 0 else 0.0

        overall = total_correct / total_fields if total_fields > 0 else 0.0
        hall_rate = total_hallucinated / total_fields if total_fields > 0 else 0.0
        corr_rate = total_corrected / total_fields if total_fields > 0 else 0.0

        return EvalReport(
            total_documents=len(self._ground_truth),
            field_scores=scores,
            overall_accuracy=round(overall, 4),
            hallucination_rate=round(hall_rate, 4),
            correction_rate=round(corr_rate, 4),
            field_accuracy={fname: round(s.accuracy, 4) for fname, s in scores.items()},
        )

    async def evaluate(
        self,
        pipeline: object,
        schema: type[BaseModel],
        files: list[str] | None = None,
    ) -> EvalReport:
        if not files:
            return self.compare_results(predicted=[])

        results: list[ExtractionResult] = []
        for path in files:
            try:
                result = await pipeline.run(path, schema)
                results.append(result)
            except (OSError, ValueError, RuntimeError):
                pass

        return self.compare_results(predicted=results)

    def evaluate_sync(
        self,
        pipeline: object,
        schema: type[BaseModel],
        files: list[str] | None = None,
    ) -> EvalReport:
        return run_sync(self.evaluate(pipeline, schema, files))
