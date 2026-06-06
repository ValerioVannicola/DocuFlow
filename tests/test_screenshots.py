from __future__ import annotations

from pathlib import Path

import pytest


class TestScreenshots:
    @pytest.mark.integration
    async def test_screenshot_all_pages(self, tmp_path):
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF not installed")

        pdf_path = tmp_path / "test.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.new_page()
        doc.save(str(pdf_path))
        doc.close()

        from docflow.screenshots import screenshot_pages

        output_dir = tmp_path / "screenshots"
        results = await screenshot_pages(str(pdf_path), output_dir=str(output_dir))

        assert len(results) == 2
        assert results[0].page_number == 0
        assert results[1].page_number == 1
        assert results[0].width > 0
        assert Path(results[0].file_path).is_file()

    @pytest.mark.integration
    async def test_screenshot_specific_pages(self, tmp_path):
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF not installed")

        pdf_path = tmp_path / "test.pdf"
        doc = fitz.open()
        for _ in range(5):
            doc.new_page()
        doc.save(str(pdf_path))
        doc.close()

        from docflow.screenshots import screenshot_pages

        output_dir = tmp_path / "screenshots"
        results = await screenshot_pages(
            str(pdf_path), output_dir=str(output_dir), pages=[0, 2, 4],
        )

        assert len(results) == 3
        assert results[0].page_number == 0
        assert results[1].page_number == 2
        assert results[2].page_number == 4


class TestScreenshotCLI:
    @pytest.mark.integration
    def test_cli_screenshot(self, tmp_path):
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF not installed")

        pdf_path = tmp_path / "test.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.save(str(pdf_path))
        doc.close()

        from click.testing import CliRunner

        from docflow.cli.main import main

        output_dir = tmp_path / "output"
        runner = CliRunner()
        result = runner.invoke(main, [
            "screenshot", str(pdf_path), "-o", str(output_dir),
        ])

        assert result.exit_code == 0
        assert "1 screenshot" in result.output


class TestBatchCLI:
    def test_extract_folder_help(self):
        from click.testing import CliRunner

        from docflow.cli.main import main

        runner = CliRunner()
        result = runner.invoke(main, ["extract-folder", "--help"])

        assert result.exit_code == 0
        assert "--schema" in result.output
        assert "--pattern" in result.output
        assert "--concurrency" in result.output

    def test_extract_folder_nonexistent_dir(self):
        from click.testing import CliRunner

        from docflow.cli.main import main

        runner = CliRunner()
        result = runner.invoke(main, [
            "extract-folder", "nonexistent_dir", "--schema", "invoice",
        ])

        assert result.exit_code != 0
