from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

import aiofiles

from docuflow.privacy.models import TokenMapping


@runtime_checkable
class MappingStore(Protocol):
    async def save_mapping(self, mapping_id: str, mappings: list[TokenMapping]) -> None: ...
    async def load_mapping(self, mapping_id: str) -> list[TokenMapping] | None: ...
    async def delete_mapping(self, mapping_id: str) -> None: ...


class LocalMappingStore:
    def __init__(self, base_path: str = "./.docuflow_mappings"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _path_for(self, mapping_id: str) -> Path:
        return self.base_path / f"{mapping_id}.json"

    async def save_mapping(self, mapping_id: str, mappings: list[TokenMapping]) -> None:
        data = [m.model_dump() for m in mappings]
        async with aiofiles.open(self._path_for(mapping_id), "w") as f:
            await f.write(json.dumps(data, indent=2))

    async def load_mapping(self, mapping_id: str) -> list[TokenMapping] | None:
        path = self._path_for(mapping_id)
        if not path.is_file():
            return None
        async with aiofiles.open(path) as f:
            content = await f.read()
        data = json.loads(content)
        return [TokenMapping.model_validate(item) for item in data]

    async def delete_mapping(self, mapping_id: str) -> None:
        path = self._path_for(mapping_id)
        if path.is_file():
            path.unlink()
