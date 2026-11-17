from agent_framework.openai import (
    OpenAIChatClient,
    OpenAIChatCompletionClient,
)

from simassist.llm.config import LLMConfig, ProviderType


def create_chat_client(config: LLMConfig):
    key = config.api_key.get_secret_value() if config.api_key else None

    if config.provider == ProviderType.LM_STUDIO:
        return OpenAIChatCompletionClient(
            model=config.model,
            base_url=(config.endpoint or "http://127.0.0.1:1235/v1"),
            api_key=key or "lm-studio",
        )

    if config.provider == ProviderType.OPENAI:
        return OpenAIChatClient(
            model=config.model,
            api_key=key,
            base_url=config.endpoint,
        )

    if config.provider == ProviderType.OPENAI_COMPATIBLE:
        return OpenAIChatCompletionClient(
            model=config.model,
            base_url=config.endpoint,
            api_key=key,
        )

    if config.provider == ProviderType.ANTHROPIC:
        from agent_framework_anthropic import AnthropicClient

        return AnthropicClient(
            model=config.model,
            api_key=key,
        )

    raise ValueError(f"Unsupported provider: {config.provider}")
