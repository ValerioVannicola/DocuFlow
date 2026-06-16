from __future__ import annotations

from pathlib import Path

import pytest

from docuflow.documents.models import Document
from docuflow.errors import UnsupportedFileTypeError
from docuflow.ingestion.local import ingest_file, ingest_file_sync, ingest_folder
from docuflow.ingestion.mime import MIME_TYPES, detect_mime_type, detect_source_kind
from docuflow.workflow.state import PipelineState
from docuflow.workflow.steps import Parse


class TestMimeDetection:
    def test_pdf(self):
        assert detect_mime_type(Path("test.pdf")) == "application/pdf"

    def test_png(self):
        assert detect_mime_type(Path("test.png")) == "image/png"

    def test_jpeg_variants(self):
        assert detect_mime_type(Path("test.jpg")) == "image/jpeg"
        assert detect_mime_type(Path("test.jpeg")) == "image/jpeg"

    def test_case_insensitive(self):
        assert detect_mime_type(Path("test.PDF")) == "application/pdf"

    def test_text_like_extensions(self):
        assert detect_mime_type(Path("notes.md")) == "text/markdown"
        assert detect_mime_type(Path("payload.json")) == "application/json"
        assert detect_mime_type(Path("payload.xml")) == "application/xml"

    def test_source_kind_detection(self):
        assert detect_source_kind(Path("test.pdf")) == "pdf"
        assert detect_source_kind(Path("test.png")) == "image"
        assert detect_source_kind(Path("test.txt")) == "text"
        assert detect_source_kind(Path("test.docx")) == "office"
        assert detect_source_kind(Path("test.xlsx")) == "spreadsheet"

    def test_unsupported_raises(self):
        with pytest.raises(UnsupportedFileTypeError):
            detect_mime_type(Path("test.xyz"))

    def test_all_types_are_strings(self):
        for ext, mime in MIME_TYPES.items():
            assert isinstance(ext, str)
            assert isinstance(mime, str)


class TestIngestFile:
    async def test_ingest_pdf(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake content")
        doc = await ingest_file(pdf_path)
        assert isinstance(doc, Document)
        assert doc.metadata.file_name == "test.pdf"
        assert doc.metadata.mime_type == "application/pdf"
        assert doc.metadata.file_size > 0
        assert doc.metadata.file_hash != ""
        assert doc.id != ""
        assert doc.status == "ingested"

    async def test_ingest_missing_file(self):
        with pytest.raises(FileNotFoundError):
            await ingest_file("nonexistent.pdf")

    async def test_ingest_unsupported_type(self, tmp_path):
        bad_file = tmp_path / "test.xyz"
        bad_file.write_text("content")
        with pytest.raises(UnsupportedFileTypeError):
            await ingest_file(bad_file)

    async def test_file_hash_deterministic(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 same content")
        doc1 = await ingest_file(pdf_path)
        doc2 = await ingest_file(pdf_path)
        assert doc1.metadata.file_hash == doc2.metadata.file_hash
        assert doc1.id != doc2.id  # different UUIDs

    def test_ingest_file_sync(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 sync test")
        doc = ingest_file_sync(pdf_path)
        assert doc.metadata.file_name == "test.pdf"

    async def test_ingest_text_file_builds_canonical_document(self, tmp_path):
        text_path = tmp_path / "note.md"
        text_path.write_text("# Claim\nName: Mario Rossi", encoding="utf-8")

        doc = await ingest_file(text_path)

        assert doc.metadata.mime_type == "text/markdown"
        assert doc.metadata.extra["source_kind"] == "text"
        assert doc.status == "parsed"
        assert doc.raw_text == "# Claim\nName: Mario Rossi"
        assert doc.metadata.page_count == 1
        assert len(doc.pages) == 1
        assert doc.pages[0].text == doc.raw_text
        assert doc.pages[0].blocks[0].text == doc.raw_text

    async def test_manual_parse_auto_skips_text_document(self, tmp_path):
        text_path = tmp_path / "note.md"
        text_path.write_text("# Claim\nName: Mario Rossi", encoding="utf-8")
        doc = await ingest_file(text_path)

        state = await Parse(parser="auto").execute(PipelineState(document=doc))

        assert state.status == "pending"
        assert state.errors == []
        assert state.document is doc
        assert state.document.status == "parsed"

    async def test_ingest_image_file_builds_single_page_document(self, tmp_path):
        image_mod = pytest.importorskip("PIL.Image")
        image_path = tmp_path / "scan.png"
        image_mod.new("RGB", (20, 10), "white").save(image_path)

        doc = await ingest_file(image_path)

        assert doc.metadata.mime_type == "image/png"
        assert doc.metadata.extra["source_kind"] == "image"
        assert doc.metadata.page_count == 1
        assert len(doc.pages) == 1
        assert doc.pages[0].width == 20
        assert doc.pages[0].height == 10
        assert doc.pages[0].unit == "px"
        assert doc.pages[0].image_path == str(image_path.resolve())


class TestIngestFolder:
    async def test_ingest_folder(self, tmp_path):
        for i in range(3):
            (tmp_path / f"doc_{i}.pdf").write_bytes(b"%PDF-1.4 content")
        (tmp_path / "readme.txt").write_text("not a pdf")

        docs = []
        async for doc in ingest_folder(tmp_path):
            docs.append(doc)
        assert len(docs) == 3

    async def test_ingest_folder_custom_pattern(self, tmp_path):
        (tmp_path / "image.png").write_bytes(b"PNG fake")
        (tmp_path / "doc.pdf").write_bytes(b"%PDF fake")
        docs = []
        async for doc in ingest_folder(tmp_path, pattern="**/*.png"):
            docs.append(doc)
        assert len(docs) == 1
        assert docs[0].metadata.mime_type == "image/png"

    async def test_ingest_nonexistent_folder(self):
        with pytest.raises(NotADirectoryError):
            async for _ in ingest_folder("nonexistent_dir"):
                pass


class TestDocumentFromFile:
    async def test_from_file(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 test")
        doc = await Document.from_file(pdf_path)
        assert isinstance(doc, Document)
        assert doc.metadata.file_name == "test.pdf"

    def test_from_file_sync(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 test")
        doc = Document.from_file_sync(pdf_path)
        assert isinstance(doc, Document)
