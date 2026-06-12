"""Tests for the DocFlow dockerize module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from docflow.dockerize import generate_deployment


@pytest.fixture()
def workflow_yaml(tmp_path):
    config = {
        "name": "test-invoice",
        "version": "1.0",
        "schema": {
            "supplier": {"type": "str", "required": True},
            "total": {"type": "float"},
        },
        "parser": "pdfplumber",
        "model": "openai/gpt-4o",
    }
    path = tmp_path / "workflow.yaml"
    path.write_text(yaml.dump(config), encoding="utf-8")
    return path


class TestGenerateDeployment:
    def test_creates_all_files(self, workflow_yaml):
        with tempfile.TemporaryDirectory() as out:
            result = generate_deployment(workflow_yaml, out)
            assert (result / "Dockerfile").is_file()
            assert (result / "server.py").is_file()
            assert (result / "workflow.yaml").is_file()
            assert (result / "docker-compose.yml").is_file()
            assert (result / "requirements.txt").is_file()
            assert (result / ".dockerignore").is_file()

    def test_dockerfile_has_python_base(self, workflow_yaml):
        with tempfile.TemporaryDirectory() as out:
            result = generate_deployment(workflow_yaml, out)
            content = (result / "Dockerfile").read_text()
            assert "python:3.11-slim" in content
            assert "uvicorn" in content

    def test_server_imports_docflow(self, workflow_yaml):
        with tempfile.TemporaryDirectory() as out:
            result = generate_deployment(workflow_yaml, out)
            content = (result / "server.py").read_text()
            assert "from docflow.serve import create_app" in content
            assert "workflow.yaml" in content

    def test_requirements_has_deps(self, workflow_yaml):
        with tempfile.TemporaryDirectory() as out:
            result = generate_deployment(workflow_yaml, out)
            content = (result / "requirements.txt").read_text()
            assert "docflow" in content
            assert "fastapi" in content
            assert "uvicorn" in content

    def test_workflow_copied(self, workflow_yaml):
        with tempfile.TemporaryDirectory() as out:
            result = generate_deployment(workflow_yaml, out)
            copied = yaml.safe_load((result / "workflow.yaml").read_text())
            assert copied["name"] == "test-invoice"
            assert copied["model"] == "openai/gpt-4o"

    def test_compose_default_port(self, workflow_yaml):
        with tempfile.TemporaryDirectory() as out:
            result = generate_deployment(workflow_yaml, out)
            content = (result / "docker-compose.yml").read_text()
            assert "8000:8000" in content

    def test_compose_custom_port(self, workflow_yaml):
        with tempfile.TemporaryDirectory() as out:
            result = generate_deployment(workflow_yaml, out, port=9090)
            content = (result / "docker-compose.yml").read_text()
            assert "9090:8000" in content

    def test_compose_without_storage(self, workflow_yaml):
        with tempfile.TemporaryDirectory() as out:
            result = generate_deployment(workflow_yaml, out, with_storage=False)
            content = (result / "docker-compose.yml").read_text()
            assert "docflow_data" not in content

    def test_compose_with_storage(self, workflow_yaml):
        with tempfile.TemporaryDirectory() as out:
            result = generate_deployment(workflow_yaml, out, with_storage=True)
            content = (result / "docker-compose.yml").read_text()
            assert "docflow_data:/data" in content
            assert "volumes:" in content

    def test_missing_config_raises(self):
        with tempfile.TemporaryDirectory() as out:
            with pytest.raises(FileNotFoundError):
                generate_deployment("/nonexistent/workflow.yaml", out)

    def test_dockerignore(self, workflow_yaml):
        with tempfile.TemporaryDirectory() as out:
            result = generate_deployment(workflow_yaml, out)
            content = (result / ".dockerignore").read_text()
            assert "__pycache__" in content
            assert ".git" in content


class TestCLI:
    def test_dockerize_command(self, workflow_yaml):
        from click.testing import CliRunner
        from docflow.cli.main import dockerize

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as out:
            result = runner.invoke(dockerize, [str(workflow_yaml), "-o", out])
            assert result.exit_code == 0
            assert "Deployment generated" in result.output
            assert Path(out, "Dockerfile").is_file()

    def test_dockerize_missing_config(self):
        from click.testing import CliRunner
        from docflow.cli.main import dockerize

        runner = CliRunner()
        result = runner.invoke(dockerize, ["/nonexistent.yaml"])
        assert result.exit_code != 0
        assert "not found" in result.output
