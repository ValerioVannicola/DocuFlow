from __future__ import annotations

from pathlib import Path

import pytest

from docuflow.documents.models import Document
from docuflow.errors import UnsupportedFileTypeError
from docuflow.ingestion.local import ingest_file, ingest_file_sync, ingest_folder
from docuflow.ingestion.mime import MIME_TYPES, detect_mime_type


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
