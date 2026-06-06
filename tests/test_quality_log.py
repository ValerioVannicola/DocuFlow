from __future__ import annotations

import json
from datetime import datetime

import pytest

from docflow.documents.evidence import Evidence
from docflow.extraction.models import ExtractedField, ExtractionResult, FieldTrust
from docflow.quality import QualityLog, QualityReport, QualitySnapshot, quality_report


def _field(value, confidence=0.9, found_in_source=True, auto_accept=True):
    trust = FieldTrust(
        agreement="5/5",
        agreement_ratio=1.0,
        found_in_source=found_in_source,
        auto_accept=auto_accept,
        score=confidence,
    )
    evidence = [Evidence(document_id="d", page_number=0, text="some text")]
    return ExtractedField(
        value=value, confidence=confidence, trust=trust, evidence=evidence,
    )


def _make_result(fields_dict):
    data = {k: f.value for k, f in fields_dict.items()}
    return ExtractionResult(
        document_id="doc-1",
        schema_name="Invoice",
        data=data,
        fields=fields_dict,
        confidence=0.9,
    )


def _good_report():
    return quality_report(_make_result({"a": _field("x"), "b": _field("y")}))


# ---------------------------------------------------------------------------
# QualitySnapshot
# ---------------------------------------------------------------------------


class TestQualitySnapshot:
    def test_from_report(self):
        report = _good_report()
        snap = QualitySnapshot.from_report(report, tags={"schema": "Invoice"})

        assert snap.score == report.score
        assert snap.completeness_rate == report.completeness_rate
        assert snap.grounding_rate == report.grounding_rate
        assert snap.evidence_coverage == report.evidence_coverage
        assert snap.mean_confidence == report.mean_confidence
        assert snap.auto_accept_rate == report.auto_accept_rate
        assert snap.correction_rate == report.correction_rate
        assert snap.field_count == report.field_count
        assert snap.ok == report.ok
        assert snap.tags == {"schema": "Invoice"}

    def test_auto_id_and_timestamp(self):
        snap = QualitySnapshot.from_report(_good_report())
        assert snap.snapshot_id
        assert isinstance(snap.timestamp, datetime)

    def test_unique_ids(self):
        s1 = QualitySnapshot.from_report(_good_report())
        s2 = QualitySnapshot.from_report(_good_report())
        assert s1.snapshot_id != s2.snapshot_id

    def test_no_tags(self):
        snap = QualitySnapshot.from_report(_good_report())
        assert snap.tags == {}

    def test_json_roundtrip(self):
        snap = QualitySnapshot.from_report(
            _good_report(), tags={"model": "gpt-4o"},
        )
        data = json.loads(snap.model_dump_json())
        restored = QualitySnapshot.model_validate(data)
        assert restored.snapshot_id == snap.snapshot_id
        assert restored.score == snap.score
        assert restored.tags == {"model": "gpt-4o"}


# ---------------------------------------------------------------------------
# QualityLog — sync methods
# ---------------------------------------------------------------------------


class TestQualityLogSync:
    def test_record_creates_file(self, tmp_path):
        log_path = tmp_path / "quality.jsonl"
        log = QualityLog(log_path)
        snap = log.record_sync(_good_report(), tags={"schema": "Invoice"})

        assert log_path.exists()
        assert snap.score == _good_report().score
        assert snap.tags == {"schema": "Invoice"}

    def test_record_appends(self, tmp_path):
        log = QualityLog(tmp_path / "quality.jsonl")
        log.record_sync(_good_report())
        log.record_sync(_good_report())

        lines = (tmp_path / "quality.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2

    def test_history_empty_file(self, tmp_path):
        log = QualityLog(tmp_path / "missing.jsonl")
        assert log.history_sync() == []

    def test_history_returns_all(self, tmp_path):
        log = QualityLog(tmp_path / "quality.jsonl")
        log.record_sync(_good_report())
        log.record_sync(_good_report())
        log.record_sync(_good_report())

        history = log.history_sync()
        assert len(history) == 3
        assert all(isinstance(s, QualitySnapshot) for s in history)

    def test_history_last_n(self, tmp_path):
        log = QualityLog(tmp_path / "quality.jsonl")
        for _ in range(5):
            log.record_sync(_good_report())

        history = log.history_sync(last_n=2)
        assert len(history) == 2

    def test_history_filter_by_tags(self, tmp_path):
        log = QualityLog(tmp_path / "quality.jsonl")
        log.record_sync(_good_report(), tags={"schema": "Invoice"})
        log.record_sync(_good_report(), tags={"schema": "Contract"})
        log.record_sync(_good_report(), tags={"schema": "Invoice"})

        invoices = log.history_sync(tags={"schema": "Invoice"})
        assert len(invoices) == 2
        assert all(s.tags["schema"] == "Invoice" for s in invoices)

    def test_history_filter_multiple_tags(self, tmp_path):
        log = QualityLog(tmp_path / "quality.jsonl")
        log.record_sync(
            _good_report(), tags={"schema": "Invoice", "model": "gpt-4o"},
        )
        log.record_sync(
            _good_report(), tags={"schema": "Invoice", "model": "gpt-3.5"},
        )
        log.record_sync(
            _good_report(), tags={"schema": "Contract", "model": "gpt-4o"},
        )

        result = log.history_sync(
            tags={"schema": "Invoice", "model": "gpt-4o"},
        )
        assert len(result) == 1

    def test_history_last_n_with_tags(self, tmp_path):
        log = QualityLog(tmp_path / "quality.jsonl")
        for _ in range(5):
            log.record_sync(_good_report(), tags={"schema": "Invoice"})
        log.record_sync(_good_report(), tags={"schema": "Contract"})

        result = log.history_sync(last_n=3, tags={"schema": "Invoice"})
        assert len(result) == 3

    def test_creates_parent_dirs(self, tmp_path):
        log_path = tmp_path / "nested" / "dir" / "quality.jsonl"
        log = QualityLog(log_path)
        log.record_sync(_good_report())
        assert log_path.exists()

    def test_each_line_is_valid_json(self, tmp_path):
        log = QualityLog(tmp_path / "quality.jsonl")
        log.record_sync(_good_report(), tags={"a": "1"})
        log.record_sync(_good_report(), tags={"b": "2"})

        content = (tmp_path / "quality.jsonl").read_text()
        for line in content.strip().splitlines():
            data = json.loads(line)
            assert "snapshot_id" in data
            assert "timestamp" in data
            assert "score" in data


# ---------------------------------------------------------------------------
# QualityLog — async methods
# ---------------------------------------------------------------------------


class TestQualityLogAsync:
    @pytest.mark.asyncio
    async def test_record_and_history(self, tmp_path):
        log = QualityLog(tmp_path / "quality.jsonl")
        snap = await log.record(_good_report(), tags={"schema": "Invoice"})
        assert snap.tags == {"schema": "Invoice"}

        history = await log.history()
        assert len(history) == 1
        assert history[0].snapshot_id == snap.snapshot_id

    @pytest.mark.asyncio
    async def test_async_appends(self, tmp_path):
        log = QualityLog(tmp_path / "quality.jsonl")
        await log.record(_good_report())
        await log.record(_good_report())
        await log.record(_good_report())

        history = await log.history()
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_async_filter_tags(self, tmp_path):
        log = QualityLog(tmp_path / "quality.jsonl")
        await log.record(_good_report(), tags={"schema": "Invoice"})
        await log.record(_good_report(), tags={"schema": "Contract"})

        invoices = await log.history(tags={"schema": "Invoice"})
        assert len(invoices) == 1

    @pytest.mark.asyncio
    async def test_async_last_n(self, tmp_path):
        log = QualityLog(tmp_path / "quality.jsonl")
        for _ in range(5):
            await log.record(_good_report())

        history = await log.history(last_n=2)
        assert len(history) == 2

    @pytest.mark.asyncio
    async def test_async_empty(self, tmp_path):
        log = QualityLog(tmp_path / "missing.jsonl")
        assert await log.history() == []

    @pytest.mark.asyncio
    async def test_async_creates_parent_dirs(self, tmp_path):
        log_path = tmp_path / "deep" / "nested" / "quality.jsonl"
        log = QualityLog(log_path)
        await log.record(_good_report())
        assert log_path.exists()
