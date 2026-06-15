from __future__ import annotations

from pathlib import Path

import pytest


class TestRendering:
    async def test_render_all_pages_supports_image_input(self, tmp_path):
        image_mod = pytest.importorskip("PIL.Image")
        from docuflow.rendering.renderer import render_all_pages, render_page

        image_path = tmp_path / "scan.png"
        image_mod.new("RGB", (32, 16), "white").save(image_path)

        images = await render_all_pages(image_path, dpi=100)
        assert len(images) == 1
        assert images[0].size == (32, 16)

        page = await render_page(image_path, page_number=0, dpi=100)
        assert page.size == (32, 16)

    @pytest.mark.integration
    async def test_render_page(self, tmp_path):
        from docuflow.rendering.renderer import render_page

        pdf_path = tmp_path / "test.pdf"
        _create_test_pdf(pdf_path)

        img = await render_page(pdf_path, page_number=0, dpi=150)
        assert img.width > 0
        assert img.height > 0

    @pytest.mark.integration
    async def test_render_all_pages(self, tmp_path):
        from docuflow.rendering.renderer import render_all_pages

        pdf_path = tmp_path / "test.pdf"
        _create_test_pdf(pdf_path)

        images = await render_all_pages(pdf_path, dpi=100)
        assert len(images) == 1
        assert images[0].width > 0

    @pytest.mark.integration
    async def test_render_invalid_page(self, tmp_path):
        from docuflow.errors import ParsingError
        from docuflow.rendering.renderer import render_page

        pdf_path = tmp_path / "test.pdf"
        _create_test_pdf(pdf_path)

        with pytest.raises(ParsingError):
            await render_page(pdf_path, page_number=99)


def _create_test_pdf(path: Path) -> None:
    from tests.conftest import make_test_pdf

    make_test_pdf(path, [(72, 72, "Test rendering content")])
