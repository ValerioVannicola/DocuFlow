from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from docflow.constants import DEFAULT_DPI
from docflow.errors import ParsingError

if TYPE_CHECKING:
    from PIL.Image import Image

_EXECUTOR = ThreadPoolExecutor(max_workers=4)


def _import_pdfium():
    try:
        import pypdfium2 as pdfium
    except ImportError as e:
        raise ImportError(
            "pypdfium2 is required for rendering. Install with: pip install docflow[pdf]"
        ) from e
    return pdfium


def _render_page_sync(file_path: str, page_number: int, dpi: int) -> Image:
    pdfium = _import_pdfium()

    try:
        pdf = pdfium.PdfDocument(file_path)
    except Exception as exc:
        raise ParsingError(f"Failed to open PDF: {file_path}") from exc

    try:
        if page_number < 0 or page_number >= len(pdf):
            raise ParsingError(
                f"Page {page_number} out of range (document has {len(pdf)} pages)"
            )
        page = pdf[page_number]
        bitmap = page.render(scale=dpi / 72.0)
        img = bitmap.to_pil().convert("RGB")
    finally:
        pdf.close()
    return img


def _page_count_sync(file_path: str) -> int:
    pdfium = _import_pdfium()

    try:
        pdf = pdfium.PdfDocument(file_path)
    except Exception as exc:
        raise ParsingError(f"Failed to open PDF: {file_path}") from exc
    try:
        return len(pdf)
    finally:
        pdf.close()


async def render_page(file_path: str | Path, page_number: int = 0, dpi: int = DEFAULT_DPI) -> Image:
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _EXECUTOR, partial(_render_page_sync, str(file_path), page_number, dpi)
    )


async def render_all_pages(file_path: str | Path, dpi: int = DEFAULT_DPI) -> list[Image]:
    import asyncio

    loop = asyncio.get_event_loop()
    page_count = await loop.run_in_executor(
        _EXECUTOR, partial(_page_count_sync, str(file_path))
    )

    tasks = [render_page(file_path, i, dpi) for i in range(page_count)]
    return await asyncio.gather(*tasks)
