from __future__ import annotations

import shutil
from pathlib import Path

import aiofiles

from docuflow.documents.models import Document
from docuflow.extraction.models import ExtractionResult
from docuflow.filling.models import FillingResult
from docuflow.observability.traces import Trace


class LocalDocumentStore:
    def __init__(self, base_path: str = "./.docuflow_store"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _doc_dir(self, document_id: str) -> Path:
        doc_dir = self.base_path / document_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        return doc_dir

    async def save_document(self, document: Document) -> str:
        doc_dir = self._doc_dir(document.id)

        src_path = Path(document.metadata.file_path)
        if src_path.is_file():
            dest = doc_dir / f"original{src_path.suffix}"
            shutil.copy2(str(src_path), str(dest))

        async with aiofiles.open(doc_dir / "document.json", "w") as f:
            await f.write(document.model_dump_json(indent=2))

        return document.id

    async def save_result(self, result: ExtractionResult) -> str:
        doc_dir = self._doc_dir(result.document_id)
        async with aiofiles.open(doc_dir / "extraction.json", "w") as f:
            await f.write(result.model_dump_json(indent=2))
        return result.document_id

    async def save_filling_result(self, result: FillingResult) -> str:
        doc_id = result.document_id or result.trace_id or "unknown"
        doc_dir = self._doc_dir(doc_id)
        async with aiofiles.open(doc_dir / "filling.json", "w") as f:
            await f.write(result.model_dump_json(indent=2))
        return doc_id

    async def save_trace(self, trace: Trace) -> str:
        doc_id = trace.document_id or "unknown"
        doc_dir = self._doc_dir(doc_id)
        async with aiofiles.open(doc_dir / "trace.json", "w") as f:
            await f.write(trace.model_dump_json(indent=2))
        return doc_id

    async def load_result(self, document_id: str) -> ExtractionResult | None:
        result_path = self.base_path / document_id / "extraction.json"
        if not result_path.is_file():
            return None
        async with aiofiles.open(result_path) as f:
            content = await f.read()
        return ExtractionResult.model_validate_json(content)

    async def load_document(self, document_id: str) -> Document | None:
        doc_path = self.base_path / document_id / "document.json"
        if not doc_path.is_file():
            return None
        async with aiofiles.open(doc_path) as f:
            content = await f.read()
        return Document.model_validate_json(content)

    async def list_documents(self) -> list[str]:
        doc_ids: list[str] = []
        if not self.base_path.is_dir():
            return doc_ids
        for entry in sorted(self.base_path.iterdir()):
            if entry.is_dir() and (entry / "extraction.json").is_file():
                doc_ids.append(entry.name)
        return doc_ids

    async def get_pending_reviews(self) -> list[str]:
        return await self.get_by_status("pending_review")

    async def get_by_status(self, status: str) -> list[str]:
        doc_ids: list[str] = []
        for doc_id in await self.list_documents():
            result = await self.load_result(doc_id)
            if result is None:
                continue
            if (status == "pending_review" and result.needs_review and result.review_status == "pending") or (status == "approved" and result.review_status == "approved") or (status == "rejected" and result.review_status == "rejected") or (status == "pending" and result.review_status == "pending" and not result.needs_review):
                doc_ids.append(doc_id)
        return doc_ids
