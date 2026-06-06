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


def _render_page_sync(file_path: str, page_number: int, dpi: int) -> Image:
    try:
        import fitz
    except ImportError as e:
        raise ImportError(
            "PyMuPDF is required for rendering. Install with: pip install docflow[pdf]"
        ) from e
    from PIL import Image as PILImage

    try:
        doc = fitz.open(file_path)
    except Exception as exc:
        raise ParsingError(f"Failed to open PDF: {file_path}") from exc

    try:
        if page_number < 0 or page_number >= len(doc):
            raise ParsingError(
                f"Page {page_number} out of range (document has {len(doc)} pages)"
            )
        page = doc[page_number]
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        img = PILImage.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()
    return img


async def render_page(file_path: str | Path, page_number: int = 0, dpi: int = DEFAULT_DPI) -> Image:
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _EXECUTOR, partial(_render_page_sync, str(file_path), page_number, dpi)
    )


async def render_all_pages(file_path: str | Path, dpi: int = DEFAULT_DPI) -> list[Image]:
    try:
        import fitz
    except ImportError as e:
        raise ImportError(
            "PyMuPDF is required for rendering. Install with: pip install docflow[pdf]"
        ) from e

    doc = fitz.open(str(file_path))
    page_count = len(doc)
    doc.close()

    import asyncio

    tasks = [render_page(file_path, i, dpi) for i in range(page_count)]
    return await asyncio.gather(*tasks)
