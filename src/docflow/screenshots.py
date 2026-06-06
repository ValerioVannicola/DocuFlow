from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from docflow._sync import run_sync
from docflow.constants import DEFAULT_DPI

if TYPE_CHECKING:
    pass


class PageScreenshot(BaseModel):
    page_number: int
    width: int = 0
    height: int = 0
    file_path: str = ""

    class Config:
        arbitrary_types_allowed = True


async def screenshot_pages(
    file_path: str | Path,
    output_dir: str | Path | None = None,
    pages: list[int] | None = None,
    dpi: int = DEFAULT_DPI,
    format: str = "png",
) -> list[PageScreenshot]:
    from docflow.rendering.renderer import render_all_pages, render_page

    file_path = str(file_path)

    if pages is not None:
        images = []
        for p in pages:
            img = await render_page(file_path, p, dpi=dpi)
            images.append((p, img))
    else:
        all_images = await render_all_pages(file_path, dpi=dpi)
        images = list(enumerate(all_images))

    results: list[PageScreenshot] = []
    for page_num, img in images:
        screenshot = PageScreenshot(
            page_number=page_num,
            width=img.width,
            height=img.height,
        )

        if output_dir is not None:
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            stem = Path(file_path).stem
            dest = out / f"{stem}_page_{page_num}.{format}"
            img.save(str(dest), format=format.upper())
            screenshot.file_path = str(dest)

        results.append(screenshot)

    return results


def screenshot_pages_sync(
    file_path: str | Path,
    output_dir: str | Path | None = None,
    pages: list[int] | None = None,
    dpi: int = DEFAULT_DPI,
    format: str = "png",
) -> list[PageScreenshot]:
    return run_sync(screenshot_pages(file_path, output_dir, pages, dpi, format))
