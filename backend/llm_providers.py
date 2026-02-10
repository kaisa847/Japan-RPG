"""LLM provider abstraction for multi-provider support."""

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# Supported providers and their default models
PROVIDERS = {
    "anthropic": {
        "name": "Anthropic (Claude)",
        "default_model": "claude-sonnet-4-5-20250929",
        "models": [
            "claude-sonnet-4-5-20250929",
            "claude-haiku-4-5-20250929",
        ],
    },
    "openai": {
        "name": "OpenAI (GPT)",
        "default_model": "gpt-4o",
        "models": [
            "gpt-4o",
            "gpt-4o-mini",
        ],
    },
    "google": {
        "name": "Google (Gemini)",
        "default_model": "gemini-2.0-flash",
        "models": [
            "gemini-2.0-flash",
            "gemini-2.5-flash",
        ],
    },
}

DEFAULT_PROVIDER = "anthropic"


class LLMProvider(ABC):
    """Abstract base for LLM API providers."""

    @abstractmethod
    async def generate(
        self, system_prompt: str, messages: list[dict], max_tokens: int = 1500
    ) -> str:
        """Send messages to the LLM and return the response text."""
        ...


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider."""

    def __init__(
        self, api_key: str, model: str = "claude-sonnet-4-5-20250929", timeout: int = 30
    ):
        from anthropic import AsyncAnthropic

        self.client = AsyncAnthropic(api_key=api_key, timeout=timeout)
        self.model = model

    async def generate(
        self, system_prompt: str, messages: list[dict], max_tokens: int = 1500
    ) -> str:
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text


class OpenAIProvider(LLMProvider):
    """OpenAI GPT API provider."""

    def __init__(
        self, api_key: str, model: str = "gpt-4o", timeout: int = 30
    ):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key, timeout=timeout)
        self.model = model

    async def generate(
        self, system_prompt: str, messages: list[dict], max_tokens: int = 1500
    ) -> str:
        oai_messages = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            oai_messages.append({"role": msg["role"], "content": msg["content"]})

        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=oai_messages,
        )
        return response.choices[0].message.content


class GoogleProvider(LLMProvider):
    """Google Gemini API provider."""

    def __init__(
        self, api_key: str, model: str = "gemini-2.0-flash", timeout: int = 30
    ):
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.model = model

    async def generate(
        self, system_prompt: str, messages: list[dict], max_tokens: int = 1500
    ) -> str:
        from google.genai import types

        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part(text=msg["content"])],
                )
            )

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=max_tokens,
            ),
        )
        return response.text


def create_provider(
    provider_name: str, api_key: str, model: str | None = None
) -> LLMProvider:
    """Factory function to create a provider by name."""
    provider_info = PROVIDERS.get(provider_name)
    if not provider_info:
        raise ValueError(f"Unbekannter Provider: {provider_name}")

    effective_model = model or provider_info["default_model"]

    if provider_name == "anthropic":
        return AnthropicProvider(api_key=api_key, model=effective_model)
    elif provider_name == "openai":
        return OpenAIProvider(api_key=api_key, model=effective_model)
    elif provider_name == "google":
        return GoogleProvider(api_key=api_key, model=effective_model)
    else:
        raise ValueError(f"Unbekannter Provider: {provider_name}")
