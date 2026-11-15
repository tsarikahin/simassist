from enum import StrEnum

from pydantic import BaseModel, Field, SecretStr, model_validator


class ProviderType(StrEnum):
    LM_STUDIO = "lm_studio"
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"
    ANTHROPIC = "anthropic"


class LLMConfig(BaseModel):
    provider: ProviderType = ProviderType.LM_STUDIO
    model: str = Field(min_length=1)
    endpoint: str | None = None
    api_key: SecretStr | None = Field(
        default=None,
        exclude=True,
        repr=False,
    )

    @model_validator(mode="after")
    def validate_connection(self):
        if self.provider == ProviderType.OPENAI_COMPATIBLE and (
            not self.endpoint or not self.api_key
        ):
            raise ValueError("Custom provider requires endpoint and API key")

        if (
            self.provider
            in {
                ProviderType.OPENAI,
                ProviderType.ANTHROPIC,
            }
            and not self.api_key
        ):
            raise ValueError(f"{self.provider.value} requires an API key")

        return self
