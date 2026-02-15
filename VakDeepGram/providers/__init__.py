"""
Provider-specific tools, prompts, and business logic for VakDeepGram.

Usage:
    from providers import get_tools_for_provider, get_prompt_for_provider
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def get_tools_for_provider(provider: str) -> list:
    """Return the Strands tool list for the given provider."""
    if provider == "setmore":
        from providers.setmore.tools import TOOLS as setmore_tools
        return setmore_tools
    from providers.square.tools import TOOLS as square_tools
    return square_tools


def get_chat_prompt_for_provider(provider: str) -> str:
    """Return the chat agent prompt tailored to the given provider."""
    if provider == "setmore":
        from providers.setmore.prompts import CHAT_PROMPT
        return CHAT_PROMPT
    from providers.square.prompts import CHAT_PROMPT
    return CHAT_PROMPT


def get_voice_prompt_for_provider(provider: str) -> str:
    """Return the voice agent prompt tailored to the given provider."""
    if provider == "setmore":
        from providers.setmore.prompts import VOICE_PROMPT
        return VOICE_PROMPT
    from providers.square.prompts import VOICE_PROMPT
    return VOICE_PROMPT
