from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from docflow.ocr.base import OCREngine, OCRResult


class TestOCRProtocol:
    def test_protocol_is_runtime_checkable(self):
        class FakeOCR:
            async def ocr(self, image, language="eng"):
                return OCRResult()

        assert isinstance(FakeOCR(), OCREngine)


class TestOCRResult:
    def test_defaults(self):
        result = OCRResult()
        assert result.text == ""
        assert result.confidence == 0.0
        assert result.blocks == []
        assert result.language == "eng"

    def test_with_data(self):
        result = OCRResult(
            text="Hello World",
            confidence=0.92,
            word_count=2,
            mean_word_confidence=92.0,
        )
        assert result.text == "Hello World"
        assert result.confidence == 0.92


def _make_mock_pytesseract(mock_data: dict, full_text: str) -> MagicMock:
    mock_pyt = MagicMock()
    mock_pyt.Output.DICT = "dict"
    mock_pyt.image_to_data.return_value = mock_data
    mock_pyt.image_to_string.return_value = full_text
    return mock_pyt


class TestTesseractOCR:
    async def test_ocr_with_mocked_tesseract(self):
        mock_data = {
            "text": ["Hello", "World", ""],
            "conf": [95.0, 88.0, -1.0],
            "left": [10, 100, 0],
            "top": [20, 20, 0],
            "width": [50, 60, 0],
            "height": [15, 15, 0],
        }
        mock_pyt = _make_mock_pytesseract(mock_data, "Hello World")
        mock_image = MagicMock()

        with patch.dict(sys.modules, {"pytesseract": mock_pyt}):
            # Force re-import of the module so it picks up the mocked pytesseract
            if "docflow.ocr.tesseract" in sys.modules:
                del sys.modules["docflow.ocr.tesseract"]
            from docflow.ocr.tesseract import TesseractOCR

            ocr = TesseractOCR(preprocess_steps=[])
            result = await ocr.ocr(mock_image)

        assert result.text == "Hello World"
        assert result.word_count == 2
        assert result.confidence > 0
        assert len(result.blocks) == 2
        assert result.blocks[0].text == "Hello"

    async def test_ocr_confidence_calculation(self):
        mock_data = {
            "text": ["High", "Low"],
            "conf": [95.0, 40.0],
            "left": [10, 100],
            "top": [20, 20],
            "width": [50, 60],
            "height": [15, 15],
        }
        mock_pyt = _make_mock_pytesseract(mock_data, "High Low")
        mock_image = MagicMock()

        with patch.dict(sys.modules, {"pytesseract": mock_pyt}):
            if "docflow.ocr.tesseract" in sys.modules:
                del sys.modules["docflow.ocr.tesseract"]
            from docflow.ocr.tesseract import TesseractOCR

            ocr = TesseractOCR(preprocess_steps=[])
            result = await ocr.ocr(mock_image)

        assert result.mean_word_confidence == pytest.approx(67.5)
        assert result.low_confidence_word_ratio == pytest.approx(0.5)


class TestPreprocessing:
    def test_to_grayscale(self):
        from PIL import Image

        from docflow.ocr.preprocessing import to_grayscale

        img = Image.new("RGB", (100, 100), color="red")
        gray = to_grayscale(img)
        assert gray.mode == "L"

    def test_threshold(self):
        from PIL import Image

        from docflow.ocr.preprocessing import threshold

        img = Image.new("L", (100, 100), color=128)
        result = threshold(img, thresh=100)
        assert result.mode == "L"

    def test_denoise(self):
        from PIL import Image

        from docflow.ocr.preprocessing import denoise

        img = Image.new("RGB", (100, 100))
        result = denoise(img)
        assert result.size == (100, 100)

    def test_preprocess_chain(self):
        from PIL import Image

        from docflow.ocr.preprocessing import preprocess

        img = Image.new("RGB", (100, 100))
        result = preprocess(img, steps=["grayscale", "denoise"])
        assert result.mode == "L"

    def test_preprocess_unknown_step_ignored(self):
        from PIL import Image

        from docflow.ocr.preprocessing import preprocess

        img = Image.new("RGB", (100, 100))
        result = preprocess(img, steps=["grayscale", "nonexistent"])
        assert result.mode == "L"
