# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""LLM Factory 测试"""

from unittest.mock import MagicMock

from agentconf import ProviderType

from ghrah.core.exceptions import LLMError
from ghrah.llm.factory import LLMFactory, _get_secret_value


class TestGetSecretValue:
    def test_none_returns_none(self):
        assert _get_secret_value(None) is None

    def test_string_returns_string(self):
        assert _get_secret_value("sk-test") == "sk-test"

    def test_secret_str_extracted(self):
        mock_secret = MagicMock()
        mock_secret.get_secret_value.return_value = "sk-secret"
        assert _get_secret_value(mock_secret) == "sk-secret"


class TestLLMFactory:
    def _make_resolved_agent(
        self,
        provider_type: ProviderType = ProviderType.OPENAI,
        model_name: str = "gpt-4o",
        base_url: str = "https://api.openai.com/v1",
        api_key: str = "sk-test",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        top_p: float | None = None,
    ) -> MagicMock:
        """创建模拟的 agentconf resolved agent 对象。"""
        mock_api_key = MagicMock()
        mock_api_key.get_secret_value.return_value = api_key

        llm_config = MagicMock()
        llm_config.provider_type = provider_type
        llm_config.model_name = model_name
        llm_config.base_url = base_url
        llm_config.api_key = mock_api_key

        resolved = MagicMock()
        resolved.model = llm_config
        resolved.temperature = temperature
        resolved.max_tokens = max_tokens
        resolved.top_p = top_p

        return resolved

    def test_create_openai(self):
        resolved = self._make_resolved_agent(provider_type=ProviderType.OPENAI)
        chat_format = LLMFactory.create(resolved)
        assert chat_format is not None
        assert chat_format.model == "gpt-4o"

    def test_create_custom_provider(self):
        resolved = self._make_resolved_agent(
            provider_type=ProviderType.CUSTOM,
            base_url="https://my-llm.example.com/v1",
        )
        chat_format = LLMFactory.create(resolved)
        assert chat_format is not None

    def test_create_deepseek(self):
        resolved = self._make_resolved_agent(
            provider_type=ProviderType.DEEPSEEK,
            base_url="https://api.deepseek.com/v1",
        )
        chat_format = LLMFactory.create(resolved)
        assert chat_format is not None
        from ghrah.chat.format.deepseek import DeepSeekFormat

        assert isinstance(chat_format, DeepSeekFormat)

    def test_unsupported_provider_type(self):
        """测试不支持的 ProviderType 枚举值。

        使用一个不在预期范围内的 provider_type 值来触发错误。
        """
        resolved = self._make_resolved_agent()
        resolved.model.provider_type = "unsupported_string"
        try:
            LLMFactory.create(resolved)
            assert False, "Should have raised LLMError"
        except LLMError as e:
            assert "Unsupported provider type" in str(e)
