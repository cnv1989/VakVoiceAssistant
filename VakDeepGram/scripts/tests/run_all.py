#!/usr/bin/env python3
"""
Run all test scripts for business number 510 405 4454.

Resolves the provider first, then runs the appropriate test suite:
1. test_resolve_business_context  (always)
2. test_provider_tools            (always)
3. test_setmore_apis OR test_square_apis (based on provider)
4. test_full_stack_e2e            (optional via --with-e2e)

Usage:
  cd VakDeepGram
  python -m scripts.tests.run_all
  python -m scripts.tests.run_all --with-e2e --base-url http://localhost:8080 [--oauth-token TOKEN]
"""
from __future__ import annotations

import asyncio
import argparse
import os
import sys
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT_DIR, "src")
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, SRC_DIR)

from vakdeepgram.connection_store import resolve_business_context

BUSINESS_NUMBER = "510 405 4454"


def _separator(title: str) -> None:
    width = 60
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width + "\n")


async def main(args: argparse.Namespace) -> int:
    start = time.time()
    print(f"=== Running all tests for: {BUSINESS_NUMBER} ===\n")

    # Resolve provider first
    context = await resolve_business_context(BUSINESS_NUMBER)
    if not context.get("success"):
        print(f"FAIL: Cannot resolve business context: {context.get('error')}")
        return 1
    provider = context.get("provider", "square")
    print(f"Provider: {provider}")
    print(f"Business: {(context.get('location') or {}).get('business_name')}\n")

    failures = 0

    # 1. Resolve business context
    _separator("1. Resolve Business Context")
    try:
        from scripts.tests.test_resolve_business_context import main as test_resolve
        rc = await test_resolve()
        if rc != 0:
            failures += 1
    except Exception as exc:
        print(f"ERROR: {exc}")
        failures += 1

    # 2. Provider tool selection
    _separator("2. Provider Tool Selection")
    try:
        from scripts.tests.test_provider_tools import main as test_tools
        rc = await test_tools()
        if rc != 0:
            failures += 1
    except Exception as exc:
        print(f"ERROR: {exc}")
        failures += 1

    # 3. Provider-specific API tests
    if provider == "setmore":
        _separator("3. Setmore API Tests")
        try:
            from scripts.tests.test_setmore_apis import main as test_setmore
            import argparse
            ns = argparse.Namespace(test=None, service=None, first_name=None)
            rc = await test_setmore(ns)
            if rc != 0:
                failures += 1
        except Exception as exc:
            print(f"ERROR: {exc}")
            failures += 1
    else:
        _separator("3. Square API Tests")
        try:
            from scripts.tests.test_square_apis import main as test_square
            import argparse
            ns = argparse.Namespace(test=None, service=None)
            rc = await test_square(ns)
            if rc != 0:
                failures += 1
        except Exception as exc:
            print(f"ERROR: {exc}")
            failures += 1

    # 4. Optional full-stack E2E (/chat + /ws + /twilio)
    if args.with_e2e:
        _separator("4. Full Stack E2E")
        try:
            from scripts.tests.test_full_stack_e2e import main as full_stack_main
            ns = argparse.Namespace(
                base_url=args.base_url,
                oauth_token=args.oauth_token,
                skip_twilio_voice=args.skip_twilio_voice,
            )
            rc = await full_stack_main(ns)
            if rc != 0:
                failures += 1
        except Exception as exc:
            print(f"ERROR: {exc}")
            failures += 1

    elapsed = time.time() - start
    _separator("Summary")
    print(f"Provider:  {provider}")
    print(f"Failures:  {failures}")
    print(f"Elapsed:   {elapsed:.1f}s")

    if failures:
        print(f"\nFAIL: {failures} test(s) failed.")
        return 1

    print(f"\nPASS: All tests passed.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run all integration tests.")
    parser.add_argument(
        "--with-e2e",
        action="store_true",
        help="Also run full stack E2E (/chat, /ws, /twilio). Requires running server.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("VAKDEEPGRAM_URL", "http://localhost:8080"),
        help="Server base URL for E2E tests.",
    )
    parser.add_argument(
        "--oauth-token",
        default=os.environ.get("INTEGRIN_OAUTH_TOKEN"),
        help="OAuth bearer token for /chat and /ws E2E (required for --with-e2e).",
    )
    parser.add_argument(
        "--skip-twilio-voice",
        action="store_true",
        help="Skip /twilio portion of full stack E2E.",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(_build_parser().parse_args())))
