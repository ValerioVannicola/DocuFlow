from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import TYPE_CHECKING

from docflow.documents.models import Block, BlockType, BoundingBox
from docflow.errors import OCRError
from docflow.ocr.base import OCRResult
from docflow.ocr.preprocessing import preprocess

if TYPE_CHECKING:
    from PIL.Image import Image

_EXECUTOR = ThreadPoolExecutor(max_workers=4)
_LOW_CONFIDENCE_THRESHOLD = 60.0


def _run_tesseract_sync(
    image: Image,
    language: str,
    preprocess_steps: list[str] | None,
    psm: int,
    oem: int,
) -> OCRResult:
    try:
        import pytesseract
    except ImportError as e:
        raise ImportError(
            "pytesseract is required for OCR. Install with: pip install docflow[ocr]"
        ) from e

    if preprocess_steps is not None:
        image = preprocess(image, preprocess_steps)

    config = f"--psm {psm} --oem {oem}"

    try:
        data = pytesseract.image_to_data(
            image, lang=language, config=config, output_type=pytesseract.Output.DICT
        )
    except Exception as exc:
        raise OCRError(f"Tesseract OCR failed: {exc}") from exc

    full_text = pytesseract.image_to_string(image, lang=language, config=config).strip()

    blocks: list[Block] = []
    confidences: list[float] = []
    low_conf_count = 0
    word_count = 0

    n_items = len(data.get("text", []))
    for i in range(n_items):
        text = str(data["text"][i]).strip()
        conf = float(data["conf"][i])

        if not text or conf < 0:
            continue

        word_count += 1
        confidences.append(conf)
        if conf < _LOW_CONFIDENCE_THRESHOLD:
            low_conf_count += 1

        bbox = BoundingBox(
            x0=float(data["left"][i]),
            y0=float(data["top"][i]),
            x1=float(data["left"][i] + data["width"][i]),
            y1=float(data["top"][i] + data["height"][i]),
        )

        blocks.append(
            Block(
                block_id=str(uuid.uuid4()),
                block_type=BlockType.TEXT,
                text=text,
                bbox=bbox,
                confidence=conf / 100.0,
            )
        )

    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
    low_ratio = low_conf_count / word_count if word_count > 0 else 0.0

    return OCRResult(
        text=full_text,
        confidence=mean_conf / 100.0,
        blocks=blocks,
        language=language,
        mean_word_confidence=mean_conf,
        low_confidence_word_ratio=low_ratio,
        word_count=word_count,
    )


class TesseractOCR:
    def __init__(
        self,
        languages: list[str] | None = None,
        psm: int = 6,
        oem: int = 3,
        preprocess_steps: list[str] | None = None,
    ):
        self.languages = languages or ["eng"]
        self.psm = psm
        self.oem = oem
        self.preprocess_steps = preprocess_steps

    async def ocr(self, image: Image, language: str = "eng") -> OCRResult:
        lang = language or "+".join(self.languages)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _EXECUTOR,
            partial(
                _run_tesseract_sync,
                image,
                lang,
                self.preprocess_steps,
                self.psm,
                self.oem,
            ),
        )
