from __future__ import annotations

from pathlib import Path

import pytest


class TestRendering:
    @pytest.mark.integration
    async def test_render_page(self, tmp_path):
        from docflow.rendering.renderer import render_page

        pdf_path = tmp_path / "test.pdf"
        _create_test_pdf(pdf_path)

        img = await render_page(pdf_path, page_number=0, dpi=150)
        assert img.width > 0
        assert img.height > 0

    @pytest.mark.integration
    async def test_render_all_pages(self, tmp_path):
        from docflow.rendering.renderer import render_all_pages

        pdf_path = tmp_path / "test.pdf"
        _create_test_pdf(pdf_path)

        images = await render_all_pages(pdf_path, dpi=100)
        assert len(images) == 1
        assert images[0].width > 0

    @pytest.mark.integration
    async def test_render_invalid_page(self, tmp_path):
        from docflow.errors import ParsingError
        from docflow.rendering.renderer import render_page

        pdf_path = tmp_path / "test.pdf"
        _create_test_pdf(pdf_path)

        with pytest.raises(ParsingError):
            await render_page(pdf_path, page_number=99)


def _create_test_pdf(path: Path) -> None:
    from tests.conftest import make_test_pdf

    make_test_pdf(path, [(72, 72, "Test rendering content")])
