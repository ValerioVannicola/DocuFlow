from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class LLMResponse(BaseModel):
    content: str = ""
    usage: dict = Field(default_factory=dict)
    model: str = ""
    raw_response: Any = None


@runtime_checkable
class LLMAdapter(Protocol):
    async def complete(
        self,
        messages: list[dict],
        response_format: type[BaseModel] | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse: ...
