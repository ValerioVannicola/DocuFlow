from __future__ import annotations

from docflow.documents.models import Document, DocumentMetadata
from docflow.extraction.models import ExtractionResult
from docflow.observability.traces import create_trace
from docflow.storage.base import Storage
from docflow.storage.local import LocalDocumentStore


class TestLocalDocumentStore:
    async def test_save_and_load_document(self, tmp_path):
        store = LocalDocumentStore(str(tmp_path / "store"))
        doc = Document(
            id="test-doc-1",
            metadata=DocumentMetadata(
                file_name="test.pdf",
                file_path="C:/test/test.pdf",
                mime_type="application/pdf",
            ),
            raw_text="Hello World",
        )

        await store.save_document(doc)
        loaded = await store.load_document("test-doc-1")
        assert loaded is not None
        assert loaded.id == "test-doc-1"
        assert loaded.raw_text == "Hello World"

    async def test_save_and_load_result(self, tmp_path):
        store = LocalDocumentStore(str(tmp_path / "store"))
        result = ExtractionResult(
            document_id="test-doc-1",
            schema_name="Invoice",
            data={"total": 100.0},
            confidence=0.9,
        )

        await store.save_result(result)
        loaded = await store.load_result("test-doc-1")
        assert loaded is not None
        assert loaded.schema_name == "Invoice"
        assert loaded.data["total"] == 100.0

    async def test_load_nonexistent(self, tmp_path):
        store = LocalDocumentStore(str(tmp_path / "store"))
        result = await store.load_result("nonexistent")
        assert result is None

    async def test_save_trace(self, tmp_path):
        store = LocalDocumentStore(str(tmp_path / "store"))
        trace = create_trace("test-doc-1")
        trace.add_event("test", step_name="test_step")

        await store.save_trace(trace)
        trace_path = tmp_path / "store" / "test-doc-1" / "trace.json"
        assert trace_path.is_file()

    async def test_protocol_compliance(self, tmp_path):
        store = LocalDocumentStore(str(tmp_path / "store"))
        assert isinstance(store, Storage)
