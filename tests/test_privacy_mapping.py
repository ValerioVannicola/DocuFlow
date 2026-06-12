from __future__ import annotations

from docuflow.privacy.mapping_store import LocalMappingStore, MappingStore
from docuflow.privacy.models import TokenMapping


class TestLocalMappingStore:
    async def test_save_and_load(self, tmp_path):
        store = LocalMappingStore(str(tmp_path / "mappings"))
        mappings = [
            TokenMapping(token="PERSON_001", original="John Doe", entity_type="PERSON"),
            TokenMapping(token="EMAIL_001", original="john@example.com", entity_type="EMAIL"),
        ]
        await store.save_mapping("map-1", mappings)
        loaded = await store.load_mapping("map-1")
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded[0].token == "PERSON_001"
        assert loaded[0].original == "John Doe"
        assert loaded[1].token == "EMAIL_001"

    async def test_load_nonexistent(self, tmp_path):
        store = LocalMappingStore(str(tmp_path / "mappings"))
        result = await store.load_mapping("nonexistent")
        assert result is None

    async def test_delete(self, tmp_path):
        store = LocalMappingStore(str(tmp_path / "mappings"))
        mappings = [TokenMapping(token="X", original="Y", entity_type="Z")]
        await store.save_mapping("map-del", mappings)
        await store.delete_mapping("map-del")
        assert await store.load_mapping("map-del") is None

    async def test_delete_nonexistent(self, tmp_path):
        store = LocalMappingStore(str(tmp_path / "mappings"))
        await store.delete_mapping("nope")  # should not raise

    def test_protocol_compliance(self, tmp_path):
        store = LocalMappingStore(str(tmp_path / "mappings"))
        assert isinstance(store, MappingStore)

    async def test_multiple_mappings(self, tmp_path):
        store = LocalMappingStore(str(tmp_path / "mappings"))
        m1 = [TokenMapping(token="A", original="B", entity_type="C")]
        m2 = [TokenMapping(token="X", original="Y", entity_type="Z")]
        await store.save_mapping("id-1", m1)
        await store.save_mapping("id-2", m2)
        assert (await store.load_mapping("id-1"))[0].token == "A"
        assert (await store.load_mapping("id-2"))[0].token == "X"
