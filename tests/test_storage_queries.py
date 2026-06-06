from __future__ import annotations

from docflow.extraction.models import ExtractionResult
from docflow.storage.base import Storage
from docflow.storage.local import LocalDocumentStore


class TestStorageProtocol:
    def test_protocol_compliance(self, tmp_path):
        store = LocalDocumentStore(str(tmp_path / "store"))
        assert isinstance(store, Storage)


class TestListDocuments:
    async def test_empty_store(self, tmp_path):
        store = LocalDocumentStore(str(tmp_path / "store"))
        docs = await store.list_documents()
        assert docs == []

    async def test_lists_saved_documents(self, tmp_path):
        store = LocalDocumentStore(str(tmp_path / "store"))

        for doc_id in ["doc-1", "doc-2", "doc-3"]:
            result = ExtractionResult(
                document_id=doc_id, schema_name="Test", data={"x": 1},
            )
            await store.save_result(result)

        docs = await store.list_documents()
        assert len(docs) == 3
        assert "doc-1" in docs
        assert "doc-2" in docs
        assert "doc-3" in docs


class TestGetByStatus:
    async def test_pending_review(self, tmp_path):
        store = LocalDocumentStore(str(tmp_path / "store"))

        r1 = ExtractionResult(
            document_id="d1", schema_name="T", needs_review=True, review_status="pending",
        )
        r2 = ExtractionResult(
            document_id="d2", schema_name="T", needs_review=False, review_status="pending",
        )
        r3 = ExtractionResult(
            document_id="d3", schema_name="T", needs_review=True, review_status="approved",
        )

        await store.save_result(r1)
        await store.save_result(r2)
        await store.save_result(r3)

        pending = await store.get_pending_reviews()
        assert pending == ["d1"]

    async def test_approved(self, tmp_path):
        store = LocalDocumentStore(str(tmp_path / "store"))

        r1 = ExtractionResult(document_id="d1", schema_name="T", review_status="approved")
        r2 = ExtractionResult(document_id="d2", schema_name="T", review_status="rejected")
        r3 = ExtractionResult(document_id="d3", schema_name="T", review_status="approved")

        await store.save_result(r1)
        await store.save_result(r2)
        await store.save_result(r3)

        approved = await store.get_by_status("approved")
        assert len(approved) == 2
        assert "d1" in approved
        assert "d3" in approved

    async def test_rejected(self, tmp_path):
        store = LocalDocumentStore(str(tmp_path / "store"))

        r1 = ExtractionResult(document_id="d1", schema_name="T", review_status="rejected")
        await store.save_result(r1)

        rejected = await store.get_by_status("rejected")
        assert rejected == ["d1"]

    async def test_empty_results(self, tmp_path):
        store = LocalDocumentStore(str(tmp_path / "store"))
        assert await store.get_by_status("approved") == []
        assert await store.get_pending_reviews() == []
