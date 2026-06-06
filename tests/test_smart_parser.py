from __future__ import annotations

from docflow.documents.models import Block, BlockType, BoundingBox, Page
from docflow.parsing.base import Parser
from docflow.parsing.smart_parser import SmartParser, _page_needs_ocr


class TestPageNeedsOCR:
    def test_empty_page_needs_ocr(self):
        page = Page(page_number=0, text="", blocks=[])
        assert _page_needs_ocr(page) is True

    def test_short_text_needs_ocr(self):
        page = Page(page_number=0, text="Hi", blocks=[])
        assert _page_needs_ocr(page) is True

    def test_good_text_no_ocr(self):
        blocks = [
            Block(
                block_id="b1", block_type=BlockType.TEXT,
                text="This is a complete paragraph with enough text to be useful.",
                bbox=BoundingBox(x0=72, y0=72, x1=500, y1=90),
            ),
        ]
        page = Page(
            page_number=0,
            text="This is a complete paragraph with enough text to be useful.",
            blocks=blocks,
        )
        assert _page_needs_ocr(page) is False

    def test_image_with_little_text_needs_ocr(self):
        blocks = [
            Block(block_id="b1", block_type=BlockType.IMAGE, text=""),
            Block(block_id="b2", block_type=BlockType.TEXT, text="Caption"),
        ]
        page = Page(page_number=0, text="Caption", blocks=blocks)
        assert _page_needs_ocr(page) is True

    def test_no_text_blocks_needs_ocr(self):
        blocks = [Block(block_id="b1", block_type=BlockType.IMAGE, text="")]
        page = Page(page_number=0, text="some extracted text that is long enough", blocks=blocks)
        assert _page_needs_ocr(page) is True


class TestSmartParser:
    def test_protocol_compliance(self):
        assert isinstance(SmartParser(), Parser)

    def test_default_config(self):
        p = SmartParser()
        assert p.ocr_languages == ["eng"]
        assert p.dpi == 200

    def test_custom_config(self):
        p = SmartParser(ocr_languages=["eng", "deu"], dpi=300)
        assert p.ocr_languages == ["eng", "deu"]
        assert p.dpi == 300


class TestSmartParserResolution:
    def test_processor_resolves_smart(self):
        from docflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(parser="smart")
        resolved = pipeline._resolve_parser()
        assert isinstance(resolved, SmartParser)

    async def test_parse_step_resolves_smart(self):
        from docflow.workflow.steps import Parse

        step = Parse(parser="smart")
        assert step.parser == "smart"
