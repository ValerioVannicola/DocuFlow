from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from docuflow.ocr.base import OCREngine, OCRResult


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
            if "docuflow.ocr.tesseract" in sys.modules:
                del sys.modules["docuflow.ocr.tesseract"]
            from docuflow.ocr.tesseract import TesseractOCR

            ocr = TesseractOCR(preprocess_steps=[])
            result = await ocr.ocr(mock_image)

        assert result.text == "Hello World"
        assert result.word_count == 2
        assert result.confidence > 0
        # Words on the same line are grouped into one line-level block
        assert len(result.blocks) == 1
        line = result.blocks[0]
        assert line.text == "Hello World"
        assert [w.text for w in line.words] == ["Hello", "World"]
        assert line.words[0].confidence == pytest.approx(0.95)
        assert line.confidence == pytest.approx(0.915)
        assert line.bbox.x0 == 10.0
        assert line.bbox.x1 == 160.0

    async def test_ocr_groups_words_into_lines(self):
        mock_data = {
            "text": ["Invoice", "Total:", "100.00"],
            "conf": [96.0, 91.0, 85.0],
            "left": [10, 10, 80],
            "top": [20, 60, 60],
            "width": [70, 60, 60],
            "height": [15, 15, 15],
            "block_num": [1, 1, 1],
            "par_num": [1, 1, 1],
            "line_num": [1, 2, 2],
        }
        mock_pyt = _make_mock_pytesseract(mock_data, "Invoice\nTotal: 100.00")
        mock_image = MagicMock()

        with patch.dict(sys.modules, {"pytesseract": mock_pyt}):
            if "docuflow.ocr.tesseract" in sys.modules:
                del sys.modules["docuflow.ocr.tesseract"]
            from docuflow.ocr.tesseract import TesseractOCR

            ocr = TesseractOCR(preprocess_steps=[])
            result = await ocr.ocr(mock_image)

        assert len(result.blocks) == 2
        assert result.blocks[0].text == "Invoice"
        assert result.blocks[1].text == "Total: 100.00"
        assert len(result.blocks[1].words) == 2
        assert result.blocks[1].confidence == pytest.approx(0.88)

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
            if "docuflow.ocr.tesseract" in sys.modules:
                del sys.modules["docuflow.ocr.tesseract"]
            from docuflow.ocr.tesseract import TesseractOCR

            ocr = TesseractOCR(preprocess_steps=[])
            result = await ocr.ocr(mock_image)

        assert result.mean_word_confidence == pytest.approx(67.5)
        assert result.low_confidence_word_ratio == pytest.approx(0.5)


class TestTesseractBinaryConfig:
    async def test_binary_not_found_raises_actionable_error(self):
        from docuflow.errors import OCRError

        class FakeNotFoundError(Exception):
            pass

        mock_pyt = _make_mock_pytesseract({}, "")
        mock_pyt.TesseractNotFoundError = FakeNotFoundError
        mock_pyt.image_to_data.side_effect = FakeNotFoundError("tesseract is not installed")
        mock_image = MagicMock()

        with patch.dict(sys.modules, {"pytesseract": mock_pyt}):
            if "docuflow.ocr.tesseract" in sys.modules:
                del sys.modules["docuflow.ocr.tesseract"]
            from docuflow.ocr.tesseract import TesseractOCR

            ocr = TesseractOCR(preprocess_steps=[])
            with pytest.raises(OCRError) as exc_info:
                await ocr.ocr(mock_image)

        msg = str(exc_info.value)
        # The error must tell the user how to fix it, not just echo the failure.
        assert "DOCUFLOW_TESSERACT_CMD" in msg
        assert "PATH" in msg

    async def test_env_var_sets_tesseract_cmd(self, monkeypatch):
        mock_data = {
            "text": ["Hi"], "conf": [95.0],
            "left": [1], "top": [1], "width": [5], "height": [5],
        }
        mock_pyt = _make_mock_pytesseract(mock_data, "Hi")
        mock_image = MagicMock()

        custom = r"C:\custom\Tesseract-OCR\tesseract.exe"
        monkeypatch.setenv("DOCUFLOW_TESSERACT_CMD", custom)

        with patch.dict(sys.modules, {"pytesseract": mock_pyt}):
            if "docuflow.ocr.tesseract" in sys.modules:
                del sys.modules["docuflow.ocr.tesseract"]
            from docuflow.ocr.tesseract import TesseractOCR

            ocr = TesseractOCR(preprocess_steps=[])
            await ocr.ocr(mock_image)

        assert mock_pyt.pytesseract.tesseract_cmd == custom


class TestPreprocessing:
    def test_to_grayscale(self):
        from PIL import Image

        from docuflow.ocr.preprocessing import to_grayscale

        img = Image.new("RGB", (100, 100), color="red")
        gray = to_grayscale(img)
        assert gray.mode == "L"

    def test_threshold(self):
        from PIL import Image

        from docuflow.ocr.preprocessing import threshold

        img = Image.new("L", (100, 100), color=128)
        result = threshold(img, thresh=100)
        assert result.mode == "L"

    def test_denoise(self):
        from PIL import Image

        from docuflow.ocr.preprocessing import denoise

        img = Image.new("RGB", (100, 100))
        result = denoise(img)
        assert result.size == (100, 100)

    def test_preprocess_chain(self):
        from PIL import Image

        from docuflow.ocr.preprocessing import preprocess

        img = Image.new("RGB", (100, 100))
        result = preprocess(img, steps=["grayscale", "denoise"])
        assert result.mode == "L"

    def test_preprocess_unknown_step_ignored(self):
        from PIL import Image

        from docuflow.ocr.preprocessing import preprocess

        img = Image.new("RGB", (100, 100))
        result = preprocess(img, steps=["grayscale", "nonexistent"])
        assert result.mode == "L"
