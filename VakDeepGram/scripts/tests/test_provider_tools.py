#!/usr/bin/env python3
"""
Test provider-specific tool and function definition selection.

Resolves the provider for business number 510 405 4454 and verifies
the correct tools and Deepgram function definitions are returned.

Usage:
  cd VakDeepGram
  python -m scripts.tests.test_provider_tools
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from connection_store import resolve_business_context
from providers import get_tools_for_provider, get_voice_prompt_for_provider, get_chat_prompt_for_provider
from providers.square.tools import TOOLS as SQUARE_TOOLS
from providers.setmore.tools import TOOLS as SETMORE_TOOLS
from agent_functions import (
    FUNCTION_DEFINITIONS,
    SQUARE_FUNCTION_DEFINITIONS,
    SETMORE_FUNCTION_DEFINITIONS,
    get_function_definitions_for_provider,
)

BUSINESS_NUMBER = "510 405 4454"


def _tool_names(tools: list) -> list[str]:
    return [getattr(t, "__name__", getattr(t, "name", str(t))) for t in tools]


def _fn_names(definitions: list[dict]) -> list[str]:
    return [d.get("name", "?") for d in definitions]


async def main() -> int:
    print(f"=== Provider tool selection for: {BUSINESS_NUMBER} ===\n")

    context = await resolve_business_context(BUSINESS_NUMBER)
    if not context.get("success"):
        print(f"FAIL: Could not resolve business context: {context.get('error')}")
        return 1

    provider = context.get("provider", "square")
    print(f"Resolved provider: {provider}\n")

    # ---- Strands tools ----
    provider_tools = get_tools_for_provider(provider)
    square_names = set(_tool_names(SQUARE_TOOLS))
    setmore_names = set(_tool_names(SETMORE_TOOLS))
    provider_names = set(_tool_names(provider_tools))
    all_names = square_names | setmore_names
    excluded_strands = all_names - provider_names
    print(f"--- Strands tools ({len(provider_tools)}) ---")
    for name in sorted(provider_names):
        print(f"  + {name}")
    if excluded_strands:
        print(f"  Excluded for {provider}: {sorted(excluded_strands)}")
    else:
        print(f"  (All tools included)")

    # ---- Deepgram function definitions ----
    provider_fns = get_function_definitions_for_provider(provider)
    all_fn_names = set(_fn_names(FUNCTION_DEFINITIONS))
    provider_fn_names = set(_fn_names(provider_fns))
    excluded_fns = all_fn_names - provider_fn_names
    print(f"\n--- Deepgram function definitions ({len(provider_fns)}) ---")
    for name in sorted(provider_fn_names):
        print(f"  + {name}")
    if excluded_fns:
        print(f"  Excluded for {provider}: {sorted(excluded_fns)}")
    else:
        print(f"  (All functions included)")

    # ---- Prompts ----
    voice_prompt = get_voice_prompt_for_provider(provider)
    chat_prompt = get_chat_prompt_for_provider(provider)
    print(f"\n--- System prompts ---")
    print(f"  Voice prompt length: {len(voice_prompt)} chars")
    print(f"  Chat prompt length: {len(chat_prompt)} chars")
    if provider == "setmore":
        assert "Setmore Notes" in voice_prompt, "Voice prompt should have Setmore Notes section"
        assert "Setmore Notes" in chat_prompt, "Chat prompt should have Setmore Notes section"
        assert "#Reschedule Flow" not in voice_prompt, "Voice prompt should not have Reschedule Flow"
        assert "#Reschedule Flow" not in chat_prompt, "Chat prompt should not have Reschedule Flow"
        print(f"  Setmore prompt assertions PASSED")
    else:
        assert "#Reschedule Flow" in voice_prompt, "Square voice prompt should have Reschedule Flow"
        print(f"  Square prompt assertions PASSED")

    # ---- Consistency checks ----
    print(f"\n--- Consistency ---")
    if provider == "setmore":
        assert "update_appointment" not in provider_names, "Setmore should not have update_appointment tool"
        assert "get_orders" not in provider_names, "Setmore should not have get_orders tool"
        assert "update_appointment" not in provider_fn_names, "Setmore should not have update_appointment fn"
        assert "get_orders" not in provider_fn_names, "Setmore should not have get_orders fn"
        print(f"  Setmore tool exclusions PASSED")
    else:
        assert "update_appointment" in provider_names, "Square should have update_appointment tool"
        assert "get_orders" in provider_names, "Square should have get_orders tool"
        print(f"  Square tool inclusions PASSED")

    print(f"\n=== PASS: Provider tool selection verified (provider={provider}) ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
