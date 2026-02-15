#!/usr/bin/env python3
"""
Run all test scripts for business number 510 405 4454.

Resolves the provider first, then runs the appropriate test suite:
1. test_resolve_business_context  (always)
2. test_provider_tools            (always)
3. test_setmore_apis OR test_square_apis (based on provider)

Usage:
  cd VakDeepGram
  python -m scripts.tests.run_all
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from connection_store import resolve_business_context

BUSINESS_NUMBER = "510 405 4454"


def _separator(title: str) -> None:
    width = 60
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width + "\n")


async def main() -> int:
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


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
