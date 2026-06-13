from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docuflow.extraction.llm.base import LLMAdapter, LLMResponse


class TestLLMAdapterProtocol:
    def test_protocol_is_runtime_checkable(self):
        class FakeLLM:
            async def complete(self, messages, response_format=None, temperature=0.0):
                return LLMResponse(content="test")

        assert isinstance(FakeLLM(), LLMAdapter)


class TestLLMResponse:
    def test_defaults(self):
        resp = LLMResponse()
        assert resp.content == ""
        assert resp.usage == {}
        assert resp.model == ""

    def test_with_data(self):
        resp = LLMResponse(
            content='{"test": true}',
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            model="gpt-4o",
        )
        assert resp.content == '{"test": true}'
        assert resp.usage["prompt_tokens"] == 100


class TestLiteLLMAdapter:
    async def test_model_name_translation(self):
        from docuflow.extraction.llm.litellm_adapter import _translate_model_name

        assert _translate_model_name("openai:gpt-4o") == "openai/gpt-4o"
        assert (
            _translate_model_name("anthropic:claude-sonnet-4-20250514")
            == "anthropic/claude-sonnet-4-20250514"
        )
        assert _translate_model_name("gemini:gemini-2.0-flash") == "gemini/gemini-2.0-flash"
        assert _translate_model_name("openai/gpt-4o") == "openai/gpt-4o"

    async def test_complete_with_mock(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"result": "test"}'
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150
        mock_response.model = "gpt-4o"

        mock_litellm = MagicMock()
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        with patch.dict(sys.modules, {"litellm": mock_litellm}):
            if "docuflow.extraction.llm.litellm_adapter" in sys.modules:
                del sys.modules["docuflow.extraction.llm.litellm_adapter"]
            from docuflow.extraction.llm.litellm_adapter import LiteLLMAdapter

            adapter = LiteLLMAdapter(model="openai:gpt-4o")
            result = await adapter.complete([{"role": "user", "content": "test"}])

        assert result.content == '{"result": "test"}'
        assert result.model == "gpt-4o"
        assert result.usage["prompt_tokens"] == 100
        assert mock_litellm.suppress_debug_info is True

    async def test_litellm_debug_info_can_be_enabled(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"result": "test"}'
        mock_response.usage = None
        mock_response.model = "gpt-4o"

        mock_litellm = MagicMock()
        mock_litellm.suppress_debug_info = True
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        with patch.dict(sys.modules, {"litellm": mock_litellm}):
            if "docuflow.extraction.llm.litellm_adapter" in sys.modules:
                del sys.modules["docuflow.extraction.llm.litellm_adapter"]
            from docuflow.extraction.llm.litellm_adapter import LiteLLMAdapter

            adapter = LiteLLMAdapter(model="openai:gpt-4o", suppress_debug_info=False)
            await adapter.complete([{"role": "user", "content": "test"}])

        assert mock_litellm.suppress_debug_info is False

    async def test_retry_on_failure(self):
        mock_litellm = MagicMock()
        mock_litellm.acompletion = AsyncMock(side_effect=RuntimeError("API error"))

        with patch.dict(sys.modules, {"litellm": mock_litellm}):
            if "docuflow.extraction.llm.litellm_adapter" in sys.modules:
                del sys.modules["docuflow.extraction.llm.litellm_adapter"]
            from docuflow.extraction.llm.litellm_adapter import LiteLLMAdapter

            adapter = LiteLLMAdapter(model="openai:gpt-4o", max_retries=2)

            with patch("asyncio.sleep", new_callable=AsyncMock):
                from docuflow.errors import SchemaExtractionError

                with pytest.raises(SchemaExtractionError, match="failed after 2 attempts"):
                    await adapter.complete([{"role": "user", "content": "test"}])

        assert mock_litellm.acompletion.call_count == 2
