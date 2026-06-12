from __future__ import annotations

from types import SimpleNamespace

import pytest

from docflow.errors import ParsingError
from docflow.parsing.azure_di import (
    AzureDocumentIntelligenceParser,
    map_analyze_result,
)
from docflow.parsing.google_docai import GoogleDocumentAIParser, map_docai_document
from docflow.parsing.textract import TextractParser, map_textract_response


class TestAzureDIMapping:
    def _fake_result(self):
        words = [
            SimpleNamespace(
                content="Total:",
                span=SimpleNamespace(offset=0, length=6),
                polygon=[1.0, 1.0, 2.0, 1.0, 2.0, 1.2, 1.0, 1.2],
                confidence=0.98,
            ),
            SimpleNamespace(
                content="100.00",
                span=SimpleNamespace(offset=7, length=6),
                polygon=[2.1, 1.0, 3.0, 1.0, 3.0, 1.2, 2.1, 1.2],
                confidence=0.91,
            ),
        ]
        lines = [
            SimpleNamespace(
                content="Total: 100.00",
                spans=[SimpleNamespace(offset=0, length=13)],
                polygon=[1.0, 1.0, 3.0, 1.0, 3.0, 1.2, 1.0, 1.2],
            ),
        ]
        page = SimpleNamespace(
            page_number=1, width=8.5, height=11.0, unit="inch",
            words=words, lines=lines,
        )
        return SimpleNamespace(pages=[page])

    def test_maps_lines_and_words(self):
        pages = map_analyze_result(self._fake_result())
        assert len(pages) == 1
        page = pages[0]
        assert page.page_number == 0
        assert page.text == "Total: 100.00"
        assert len(page.blocks) == 1
        line = page.blocks[0]
        assert [w.text for w in line.words] == ["Total:", "100.00"]
        assert line.words[1].confidence == pytest.approx(0.91)
        assert line.confidence == pytest.approx(0.945)
        # DI inches convert to the canonical point space (x72)
        assert page.unit == "pt"
        assert page.width == pytest.approx(8.5 * 72)
        assert line.bbox.x0 == pytest.approx(72.0)
        assert line.bbox.x1 == pytest.approx(216.0)

    async def test_missing_credentials_raises(self, tmp_path):
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF")
        from docflow.documents.models import Document, DocumentMetadata

        doc = Document(
            id="d1",
            metadata=DocumentMetadata(file_name="doc.pdf", file_path=str(f)),
        )
        parser = AzureDocumentIntelligenceParser(endpoint="", key="")
        with pytest.raises(ParsingError, match="credentials missing"):
            await parser.parse(doc)


class TestTextractMapping:
    def _fake_response(self):
        return {
            "Blocks": [
                {
                    "Id": "line-1",
                    "BlockType": "LINE",
                    "Text": "Invoice INV-001",
                    "Confidence": 95.0,
                    "Geometry": {
                        "BoundingBox": {
                            "Left": 0.1, "Top": 0.1, "Width": 0.4, "Height": 0.05,
                        }
                    },
                    "Relationships": [{"Type": "CHILD", "Ids": ["w1", "w2"]}],
                },
                {
                    "Id": "w1",
                    "BlockType": "WORD",
                    "Text": "Invoice",
                    "Confidence": 99.0,
                    "Geometry": {
                        "BoundingBox": {
                            "Left": 0.1, "Top": 0.1, "Width": 0.2, "Height": 0.05,
                        }
                    },
                },
                {
                    "Id": "w2",
                    "BlockType": "WORD",
                    "Text": "INV-001",
                    "Confidence": 87.0,
                    "Geometry": {
                        "BoundingBox": {
                            "Left": 0.32, "Top": 0.1, "Width": 0.18, "Height": 0.05,
                        }
                    },
                },
            ]
        }

    def test_maps_lines_and_words(self):
        page = map_textract_response(
            self._fake_response(), page_number=0, page_width=1000, page_height=800,
        )
        assert page.text == "Invoice INV-001"
        assert len(page.blocks) == 1
        line = page.blocks[0]
        assert [w.text for w in line.words] == ["Invoice", "INV-001"]
        assert line.words[1].confidence == pytest.approx(0.87)
        assert line.confidence == pytest.approx(0.93)
        # bbox scaled from ratios to pixels
        assert line.bbox.x0 == pytest.approx(100.0)
        assert line.words[0].bbox.x1 == pytest.approx(300.0)


class TestGoogleDocAIMapping:
    def _fake_document(self):
        full_text = "Supplier: Acme Corp\n"

        def anchor(start, end):
            return SimpleNamespace(
                text_segments=[SimpleNamespace(start_index=start, end_index=end)]
            )

        def layout(start, end, conf):
            return SimpleNamespace(
                text_anchor=anchor(start, end),
                confidence=conf,
                bounding_poly=SimpleNamespace(
                    vertices=[
                        SimpleNamespace(x=10, y=10),
                        SimpleNamespace(x=200, y=10),
                        SimpleNamespace(x=200, y=30),
                        SimpleNamespace(x=10, y=30),
                    ],
                    normalized_vertices=[],
                ),
            )

        tokens = [
            SimpleNamespace(layout=layout(0, 9, 0.97)),    # "Supplier:"
            SimpleNamespace(layout=layout(10, 14, 0.92)),  # "Acme"
            SimpleNamespace(layout=layout(15, 19, 0.88)),  # "Corp"
        ]
        lines = [SimpleNamespace(layout=layout(0, 20, 0.93))]
        page = SimpleNamespace(
            page_number=1,
            dimension=SimpleNamespace(width=612.0, height=792.0),
            tokens=tokens,
            lines=lines,
        )
        return SimpleNamespace(text=full_text, pages=[page])

    def test_maps_lines_and_words(self):
        pages = map_docai_document(self._fake_document())
        assert len(pages) == 1
        page = pages[0]
        assert page.page_number == 0
        assert page.text == "Supplier: Acme Corp"
        line = page.blocks[0]
        assert [w.text for w in line.words] == ["Supplier:", "Acme", "Corp"]
        assert line.words[2].confidence == pytest.approx(0.88)
        assert line.confidence == pytest.approx((0.97 + 0.92 + 0.88) / 3)

    async def test_missing_config_raises(self, tmp_path):
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF")
        from docflow.documents.models import Document, DocumentMetadata

        doc = Document(
            id="d1",
            metadata=DocumentMetadata(file_name="doc.pdf", file_path=str(f)),
        )
        parser = GoogleDocumentAIParser(project="", processor_id="")
        with pytest.raises(ParsingError, match="configuration missing"):
            await parser.parse(doc)


class TestParserResolution:
    def test_pipeline_resolves_new_parser_names(self):
        from docflow.processor import DocumentPipeline

        for name, cls in [
            ("azure-di", AzureDocumentIntelligenceParser),
            ("textract", TextractParser),
            ("google-docai", GoogleDocumentAIParser),
        ]:
            pipeline = DocumentPipeline(parser=name)
            assert isinstance(pipeline._resolve_parser(), cls)

    def test_pipeline_resolves_parser_dicts(self):
        from docflow.processor import DocumentPipeline

        pipeline = DocumentPipeline(
            parser={"type": "azure-di", "model": "prebuilt-layout"}
        )
        parser = pipeline._resolve_parser()
        assert isinstance(parser, AzureDocumentIntelligenceParser)
        assert parser.model == "prebuilt-layout"

        pipeline = DocumentPipeline(parser={"type": "textract", "region": "eu-west-1"})
        parser = pipeline._resolve_parser()
        assert isinstance(parser, TextractParser)
        assert parser.region_name == "eu-west-1"

        pipeline = DocumentPipeline(
            parser={"type": "google-docai", "project": "p1", "processor_id": "x9"}
        )
        parser = pipeline._resolve_parser()
        assert isinstance(parser, GoogleDocumentAIParser)
        assert parser.project == "p1"
        assert parser.processor_id == "x9"
