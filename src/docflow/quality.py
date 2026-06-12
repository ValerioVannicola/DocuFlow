from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import aiofiles
from pydantic import BaseModel, Field

from docflow.extraction.models import ExtractionResult


class FieldQuality(BaseModel):
    confidence: float = 0.0
    found_in_source: bool = False
    has_evidence: bool = False
    auto_accept: bool = False
    corrected: bool = False
    missing: bool = False
    warning: str = ""


class QualityReport(BaseModel):
    score: float = 0.0
    completeness_rate: float = 0.0
    grounding_rate: float = 0.0
    evidence_coverage: float = 0.0
    mean_confidence: float = 0.0
    auto_accept_rate: float = 0.0
    correction_rate: float = 0.0
    needs_review_count: int = 0
    field_count: int = 0
    ok: bool = True
    warnings: list[str] = Field(default_factory=list)
    field_details: dict[str, FieldQuality] = Field(default_factory=dict)
    n_results: int = 1
    worst_fields: list[str] = Field(default_factory=list)


def _single_report(result: ExtractionResult, threshold: float) -> QualityReport:
    fields = result.fields
    n = len(fields)
    if n == 0:
        return QualityReport(score=0.0, ok=False, warnings=["No fields extracted"])

    present = 0
    grounded = 0
    evidenced = 0
    accepted = 0
    corrected = 0
    conf_sum = 0.0
    warnings: list[str] = []
    details: dict[str, FieldQuality] = {}
    field_scores: dict[str, float] = {}

    for fname, field in fields.items():
        is_missing = field.value is None

        if is_missing:
            warnings.append(f"Field '{fname}': missing (value is None)")
            details[fname] = FieldQuality(missing=True, warning="missing")
            field_scores[fname] = 0.0
            continue

        present += 1
        trust = field.trust
        found = trust.found_in_source if trust else False
        has_ev = len(field.evidence) > 0
        auto = trust.auto_accept if trust else False

        if found:
            grounded += 1
        if has_ev:
            evidenced += 1
        if auto:
            accepted += 1
        if field.corrected:
            corrected += 1
        conf_sum += field.confidence

        warning = ""
        if not has_ev:
            warning = "no evidence"
            warnings.append(f"Field '{fname}': no evidence attached")
        elif not found:
            warning = "value not found in source text"
            warnings.append(f"Field '{fname}': value not found in source text")
        elif not auto and trust:
            if trust.agreement and trust.agreement_ratio < 1.0 and trust.agreement_ratio > 0.0:
                warning = "agent disagreement"
                warnings.append(f"Field '{fname}': not auto-accepted (agent disagreement)")
            elif not auto:
                warning = "needs review"
                warnings.append(f"Field '{fname}': not auto-accepted")

        if field.corrected:
            warnings.append(f"Field '{fname}': human-corrected")

        fq = FieldQuality(
            confidence=field.confidence,
            found_in_source=found,
            has_evidence=has_ev,
            auto_accept=auto,
            corrected=field.corrected,
            warning=warning,
        )
        details[fname] = fq
        field_scores[fname] = (
            (0.3 * (1.0 if has_ev else 0.0))
            + (0.3 * (1.0 if found else 0.0))
            + (0.2 * field.confidence)
            + (0.2 * (1.0 if auto else 0.0))
        )

    completeness_rate = present / n
    grounding_rate = grounded / present if present else 0.0
    evidence_coverage = evidenced / present if present else 0.0
    mean_confidence = conf_sum / present if present else 0.0
    auto_accept_rate = accepted / present if present else 0.0
    correction_rate = corrected / present if present else 0.0

    score = round(
        0.15 * completeness_rate
        + 0.25 * evidence_coverage
        + 0.25 * grounding_rate
        + 0.2 * mean_confidence
        + 0.15 * auto_accept_rate,
        4,
    )

    worst = sorted(field_scores, key=lambda f: field_scores[f])
    worst_fields = [f for f in worst if field_scores[f] < score][:3]

    return QualityReport(
        score=score,
        completeness_rate=round(completeness_rate, 4),
        grounding_rate=round(grounding_rate, 4),
        evidence_coverage=round(evidence_coverage, 4),
        mean_confidence=round(mean_confidence, 4),
        auto_accept_rate=round(auto_accept_rate, 4),
        correction_rate=round(correction_rate, 4),
        needs_review_count=result.review_reasons.__len__() if result.needs_review else 0,
        field_count=n,
        ok=score >= threshold,
        warnings=warnings,
        field_details=details,
        n_results=1,
        worst_fields=worst_fields,
    )


def quality_report(
    results: ExtractionResult | list[ExtractionResult],
    threshold: float = 0.7,
) -> QualityReport:
    if isinstance(results, ExtractionResult):
        return _single_report(results, threshold)

    if not results:
        return QualityReport(
            score=0.0, ok=False, n_results=0,
            warnings=["No results to assess"],
        )

    reports = [_single_report(r, threshold) for r in results]
    n = len(reports)

    avg_score = sum(r.score for r in reports) / n
    avg_completeness = sum(r.completeness_rate for r in reports) / n
    avg_grounding = sum(r.grounding_rate for r in reports) / n
    avg_evidence = sum(r.evidence_coverage for r in reports) / n
    avg_confidence = sum(r.mean_confidence for r in reports) / n
    avg_accept = sum(r.auto_accept_rate for r in reports) / n
    avg_correction = sum(r.correction_rate for r in reports) / n
    total_review = sum(r.needs_review_count for r in reports)
    total_fields = sum(r.field_count for r in reports)

    field_score_sums: dict[str, list[float]] = {}
    for report in reports:
        for fname, fq in report.field_details.items():
            if fname not in field_score_sums:
                field_score_sums[fname] = []
            fs = (
                0.3 * (1.0 if fq.has_evidence else 0.0)
                + 0.3 * (1.0 if fq.found_in_source else 0.0)
                + 0.2 * fq.confidence
                + 0.2 * (1.0 if fq.auto_accept else 0.0)
            )
            field_score_sums[fname].append(fs)

    field_avgs = {
        fname: sum(scores) / len(scores)
        for fname, scores in field_score_sums.items()
    }
    worst = sorted(field_avgs, key=lambda f: field_avgs[f])
    worst_fields = [f for f in worst if field_avgs[f] < avg_score][:5]

    all_warnings: list[str] = []
    for i, report in enumerate(reports):
        for w in report.warnings:
            all_warnings.append(f"[result {i}] {w}")

    return QualityReport(
        score=round(avg_score, 4),
        completeness_rate=round(avg_completeness, 4),
        grounding_rate=round(avg_grounding, 4),
        evidence_coverage=round(avg_evidence, 4),
        mean_confidence=round(avg_confidence, 4),
        auto_accept_rate=round(avg_accept, 4),
        correction_rate=round(avg_correction, 4),
        needs_review_count=total_review,
        field_count=total_fields,
        ok=avg_score >= threshold,
        warnings=all_warnings,
        field_details={},
        n_results=n,
        worst_fields=worst_fields,
    )


# ---------------------------------------------------------------------------
# QualitySnapshot — a timestamped, tagged quality record
# ---------------------------------------------------------------------------


class QualitySnapshot(BaseModel):
    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=datetime.now)
    tags: dict[str, str] = Field(default_factory=dict)
    score: float = 0.0
    completeness_rate: float = 0.0
    grounding_rate: float = 0.0
    evidence_coverage: float = 0.0
    mean_confidence: float = 0.0
    auto_accept_rate: float = 0.0
    correction_rate: float = 0.0
    field_count: int = 0
    ok: bool = True

    @classmethod
    def from_report(
        cls,
        report: QualityReport,
        tags: dict[str, str] | None = None,
    ) -> QualitySnapshot:
        return cls(
            tags=tags or {},
            score=report.score,
            completeness_rate=report.completeness_rate,
            grounding_rate=report.grounding_rate,
            evidence_coverage=report.evidence_coverage,
            mean_confidence=report.mean_confidence,
            auto_accept_rate=report.auto_accept_rate,
            correction_rate=report.correction_rate,
            field_count=report.field_count,
            ok=report.ok,
        )


# ---------------------------------------------------------------------------
# QualityLog — append-only JSONL persistence for snapshots
# ---------------------------------------------------------------------------

_METRIC_FIELDS = (
    "score",
    "completeness_rate",
    "grounding_rate",
    "evidence_coverage",
    "mean_confidence",
    "auto_accept_rate",
    "correction_rate",
)


class QualityLog:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    async def record(
        self,
        report: QualityReport,
        tags: dict[str, str] | None = None,
    ) -> QualitySnapshot:
        snapshot = QualitySnapshot.from_report(report, tags=tags)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(self._path, "a", encoding="utf-8") as f:
            await f.write(snapshot.model_dump_json() + "\n")
        return snapshot

    def record_sync(
        self,
        report: QualityReport,
        tags: dict[str, str] | None = None,
    ) -> QualitySnapshot:
        snapshot = QualitySnapshot.from_report(report, tags=tags)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(snapshot.model_dump_json() + "\n")
        return snapshot

    async def history(
        self,
        last_n: int | None = None,
        tags: dict[str, str] | None = None,
    ) -> list[QualitySnapshot]:
        if not self._path.exists():
            return []
        async with aiofiles.open(self._path, "r", encoding="utf-8") as f:
            content = await f.read()
        return self._parse(content, last_n=last_n, tags=tags)

    def history_sync(
        self,
        last_n: int | None = None,
        tags: dict[str, str] | None = None,
    ) -> list[QualitySnapshot]:
        if not self._path.exists():
            return []
        content = self._path.read_text(encoding="utf-8")
        return self._parse(content, last_n=last_n, tags=tags)

    @staticmethod
    def _parse(
        content: str,
        last_n: int | None = None,
        tags: dict[str, str] | None = None,
    ) -> list[QualitySnapshot]:
        snapshots: list[QualitySnapshot] = []
        for line in content.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            snapshots.append(QualitySnapshot.model_validate(json.loads(line)))
        if tags:
            snapshots = [
                s for s in snapshots
                if all(s.tags.get(k) == v for k, v in tags.items())
            ]
        if last_n is not None:
            snapshots = snapshots[-last_n:]
        return snapshots
