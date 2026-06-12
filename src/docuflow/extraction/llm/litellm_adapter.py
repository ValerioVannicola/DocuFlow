from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel

from docuflow.errors import SchemaExtractionError
from docuflow.extraction.llm.base import LLMResponse


def _translate_model_name(model: str) -> str:
    """Translate user-facing model string to litellm format.

    'openai:gpt-4o' -> 'openai/gpt-4o'
    'anthropic:claude-sonnet-4-20250514' -> 'anthropic/claude-sonnet-4-20250514'
    'gemini:gemini-2.0-flash' -> 'gemini/gemini-2.0-flash'
    """
    if ":" in model and "/" not in model:
        return model.replace(":", "/", 1)
    return model


class LiteLLMAdapter:
    def __init__(
        self,
        model: str = "openai/gpt-4o",
        api_key: str | None = None,
        max_retries: int = 3,
        **kwargs: Any,
    ):
        self.model = _translate_model_name(model)
        self.api_key = api_key
        self.max_retries = max_retries
        self.extra_kwargs = kwargs

    async def complete(
        self,
        messages: list[dict],
        response_format: type[BaseModel] | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        try:
            import litellm
        except ImportError as e:
            raise ImportError(
                "litellm is required for LLM calls. Install with: pip install docuflow[llm]"
            ) from e

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            **self.extra_kwargs,
        }

        if self.api_key:
            kwargs["api_key"] = self.api_key

        if response_format is not None:
            kwargs["response_format"] = response_format

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = await litellm.acompletion(**kwargs)
                content = response.choices[0].message.content or ""
                usage = {}
                if response.usage:
                    usage = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                    }
                    try:
                        cost = litellm.completion_cost(completion_response=response)
                        if cost:
                            usage["cost_usd"] = round(cost, 6)
                    except Exception:  # noqa: S110 — unknown model pricing; tokens still reported
                        pass
                return LLMResponse(
                    content=content,
                    usage=usage,
                    model=response.model or self.model,
                    raw_response=response,
                )
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    wait = min(2**attempt * 1.0, 30.0)
                    await asyncio.sleep(wait)

        raise SchemaExtractionError(
            f"LLM call failed after {self.max_retries} attempts: {last_error}"
        ) from last_error
