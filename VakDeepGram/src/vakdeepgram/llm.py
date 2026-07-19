"""
Builds the Strands Agent model for the configured LLM provider.

Strands Agents (the framework used for the /chat endpoint and voice
function-calling) supports pluggable model providers. Vak exposes three via
LLM_PROVIDER: "bedrock" (default, AWS Bedrock/Claude — no extra API key
needed if the deployment already has AWS credentials), "anthropic" (calls
the Anthropic API directly), and "openai" (calls the OpenAI API directly,
e.g. GPT-4o). See docs/CONFIGURATION.md for the full settings reference.

To add another Strands-supported provider (Gemini, Mistral, Ollama, etc.),
add a branch here — no other code needs to change, since every call site
just asks this module for "the configured model".
"""
from __future__ import annotations

from typing import Any, Optional

from vakdeepgram import config

DEFAULT_MODEL_IDS = {
    "bedrock": "us.anthropic.claude-opus-4-6-v1",
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o",
}


def build_llm_model(
    model_id: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> Any:
    """Build a Strands Model instance for config.settings.llm_provider.

    Any of model_id/max_tokens/temperature can be overridden per call (e.g.
    from a request payload); otherwise they fall back to settings.
    """
    settings = config.settings
    provider = (settings.llm_provider or "bedrock").strip().lower()
    resolved_max_tokens = max_tokens if max_tokens is not None else settings.bedrock_max_tokens
    resolved_temperature = temperature if temperature is not None else settings.bedrock_temperature
    resolved_model_id = model_id or settings.llm_model_id

    if provider == "openai":
        from strands.models.openai import OpenAIModel

        return OpenAIModel(
            client_args={"api_key": settings.openai_api_key},
            model_id=resolved_model_id or DEFAULT_MODEL_IDS["openai"],
            params={"max_tokens": resolved_max_tokens, "temperature": resolved_temperature},
        )

    if provider == "anthropic":
        from strands.models.anthropic import AnthropicModel

        return AnthropicModel(
            client_args={"api_key": settings.anthropic_api_key},
            model_id=resolved_model_id or DEFAULT_MODEL_IDS["anthropic"],
            max_tokens=resolved_max_tokens,
            params={"temperature": resolved_temperature},
        )

    # Default: AWS Bedrock (the only provider that needs no separate API key
    # when the deployment already has AWS credentials).
    from strands.models import BedrockModel

    return BedrockModel(
        model_id=resolved_model_id or settings.bedrock_model_id or DEFAULT_MODEL_IDS["bedrock"],
        temperature=resolved_temperature,
        max_tokens=resolved_max_tokens,
        region_name=settings.aws_region,
    )
