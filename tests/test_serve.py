"""Tests for the DocuFlow serve module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from docuflow.workflow_config import WorkflowConfig

fastapi_testclient = pytest.importorskip(
    "fastapi.testclient", reason="serve tests require docuflow[serve]"
)
TestClient = fastapi_testclient.TestClient
serve_module = pytest.importorskip("docuflow.serve", reason="serve tests require docuflow[serve]")
create_app = serve_module.create_app


@pytest.fixture()
def config():
    return WorkflowConfig(
        name="test-workflow",
        version="1.0",
        description="Test workflow",
        schema_={"supplier": {"type": "str", "required": True}, "total": {"type": "float"}},
        parser="pdfplumber",
        model="openai/gpt-4o",
    )


@pytest.fixture()
def app(config):
    return create_app(config)


@pytest.fixture()
def client(app):
    return TestClient(app)


class TestHealth:
    def test_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["workflow"] == "test-workflow"
        assert data["version"] == "1.0"
        assert data["model"] == "openai/gpt-4o"
        assert data["parser"] == "pdfplumber"


class TestSchema:
    def test_returns_fields(self, client):
        resp = client.get("/schema")
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow"] == "test-workflow"
        assert "supplier" in data["fields"]
        assert data["fields"]["supplier"]["type"] == "str"
        assert "total" in data["fields"]


class TestExtract:
    @patch("docuflow.serve.quality_report")
    @patch.object(WorkflowConfig, "build_schema")
    @patch.object(WorkflowConfig, "build_pipeline")
    def test_extract_returns_result(self, mock_bp, mock_bs, mock_qr, config):
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {
            "document_id": "doc_123",
            "data": {"supplier": "Acme", "total": 100.0},
            "confidence": 0.95,
        }
        mock_qr.return_value = MagicMock(score=0.88, ok=True)

        mock_pipeline = MagicMock()
        mock_pipeline.run_sync.return_value = mock_result
        mock_bp.return_value = mock_pipeline
        mock_bs.return_value = MagicMock

        app = create_app(config)
        client = TestClient(app)
        resp = client.post(
            "/extract",
            files={"file": ("invoice.pdf", b"fake pdf content", "application/pdf")},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["supplier"] == "Acme"
        assert data["confidence"] == 0.95
        assert data["quality_score"] == 0.88
        assert data["quality_ok"] is True

    def test_extract_requires_file(self, client):
        resp = client.post("/extract")
        assert resp.status_code == 422


class TestAppMetadata:
    def test_title_includes_workflow_name(self, app):
        assert "test-workflow" in app.title

    def test_version_matches(self, app):
        assert app.version == "1.0"
