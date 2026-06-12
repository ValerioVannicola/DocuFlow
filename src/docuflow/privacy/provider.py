from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from docuflow.privacy.models import AnonymizationMode, PrivacyFinding, TokenMapping

if TYPE_CHECKING:
    from PIL.Image import Image


@runtime_checkable
class PrivacyProvider(Protocol):
    async def adetect_text(
        self,
        text: str,
        entities: list[str] | None = None,
        language: str = "en",
        score_threshold: float = 0.35,
    ) -> list[PrivacyFinding]: ...

    async def aanonymize_text(
        self,
        text: str,
        findings: list[PrivacyFinding],
        mode: AnonymizationMode,
        token_map: dict[str, str] | None = None,
    ) -> tuple[str, list[TokenMapping]]: ...

    async def arestore_text(
        self,
        text: str,
        mappings: list[TokenMapping],
    ) -> str: ...


@runtime_checkable
class ImagePrivacyProvider(Protocol):
    async def aredact_image(
        self,
        image: Image,
        findings: list[PrivacyFinding],
    ) -> Image: ...
