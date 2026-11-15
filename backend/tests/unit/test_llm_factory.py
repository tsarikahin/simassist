import pytest
from agent_framework.openai import (
    OpenAIChatClient,
    OpenAIChatCompletionClient,
)
from pydantic import SecretStr, ValidationError
from simassist.llm.config import LLMConfig
from simassist.llm.factory import create_chat_client


def test_lm_studio_factory():
    config = LLMConfig(
        provider="lm_studio",
        model="local-model",
    )

    client = create_chat_client(config)

    assert isinstance(client, OpenAIChatCompletionClient)


def test_openai_factory():
    config = LLMConfig(
        provider="openai",
        model="test-model",
        api_key=SecretStr("test-key"),
    )

    client = create_chat_client(config)

    assert isinstance(client, OpenAIChatClient)


def test_custom_provider_requires_credentials():
    with pytest.raises(ValidationError):
        LLMConfig(
            provider="openai_compatible",
            model="custom-model",
            endpoint="https://example.com/v1",
        )


def test_api_key_excluded_from_serialization():
    config = LLMConfig(
        provider="anthropic",
        model="test-model",
        api_key=SecretStr("secret-value"),
    )

    assert "secret-value" not in config.model_dump_json()
    assert "api_key" not in config.model_dump()
