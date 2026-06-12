from __future__ import annotations

import pytest
from click.testing import CliRunner

from docuflow.cli.main import main


class TestCLI:
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "docuflow" in result.output

    def test_extract_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["extract", "--help"])
        assert result.exit_code == 0
        assert "--schema" in result.output
        assert "--model" in result.output

    def test_templates_list(self):
        runner = CliRunner()
        result = runner.invoke(main, ["templates", "list"])
        assert result.exit_code == 0
        assert "invoice" in result.output
        assert "contract" in result.output

    def test_templates_show(self):
        runner = CliRunner()
        result = runner.invoke(main, ["templates", "show", "invoice"])
        assert result.exit_code == 0
        assert "supplier_name" in result.output

    def test_templates_show_not_found(self):
        runner = CliRunner()
        result = runner.invoke(main, ["templates", "show", "nonexistent"])
        assert result.exit_code != 0

    def test_templates_init(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, ["templates", "init", "invoice", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / "invoice.yaml").is_file()

    def test_extract_bad_schema(self):
        runner = CliRunner()
        result = runner.invoke(main, ["extract", "fake.pdf", "--schema", "nonexistent"])
        assert result.exit_code != 0
        assert "Error" in result.output


class TestCLIUtils:
    def test_load_template_schema(self):
        from pydantic import BaseModel

        from docuflow.cli.utils import load_schema

        schema = load_schema("invoice")
        assert issubclass(schema, BaseModel)

    def test_load_unknown_raises(self):
        from docuflow.cli.utils import load_schema

        with pytest.raises(ValueError):
            load_schema("totally_nonexistent_schema")

    def test_load_dotted_path(self):
        from docuflow.cli.utils import load_schema

        schema = load_schema("examples.schemas.invoice.Invoice")
        assert schema.__name__ == "Invoice"
