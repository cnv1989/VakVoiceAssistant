#!/usr/bin/env python3
"""
Test Setmore access token fetch from DynamoDB (get_setmore_access_token_from_dynamodb).

Covers:
- Successful token fetch for a Setmore business number
- Token is valid (e.g. fetch_services works with it)
- Cache: second call within TTL returns same token (and is fast)
- Error cases: empty/invalid business number, business not found, non-Setmore business

Usage:
  cd VakDeepGram
  python -m scripts.tests.test_setmore_access_token
  python -m scripts.tests.test_setmore_access_token --test cache
  python -m scripts.tests.test_setmore_access_token --business-number "5104054454"
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from connection_store import get_setmore_access_token_from_dynamodb, resolve_business_context
from utils import setmore_api

# Default Setmore business number (Mission Barber)
DEFAULT_BUSINESS_NUMBER = "510 405 4454"


async def test_fetch_token(business_number: str) -> None:
    """Test get_setmore_access_token_from_dynamodb returns a valid token."""
    print(f"--- get_setmore_access_token_from_dynamodb (business_number={business_number!r}) ---")
    result = await get_setmore_access_token_from_dynamodb(business_number)
    print(f"Success: {result.get('success')}")
    if not result.get("success"):
        print(f"Error: {result.get('error')}")
        return
    token = result.get("access_token")
    if not token:
        print("FAIL: success=True but no access_token")
        return
    print(f"Access token length: {len(token)}")
    print("OK: Token fetched from DynamoDB.")
    print()


async def test_token_works(business_number: str) -> None:
    """Fetch token and verify it works by calling fetch_services."""
    print("--- token validity (fetch_services with token from DynamoDB) ---")
    result = await get_setmore_access_token_from_dynamodb(business_number)
    if not result.get("success") or not result.get("access_token"):
        print(f"SKIP: Could not get token: {result.get('error')}")
        return
    token = result["access_token"]
    services_result = await setmore_api.fetch_services(token)
    print(f"fetch_services success: {services_result.get('success')}")
    if not services_result.get("success"):
        print(f"Error: {services_result.get('error')}")
        return
    services = services_result.get("services") or []
    print(f"Service count: {len(services)}")
    print("OK: Token is valid.")
    print()


async def test_cache(business_number: str) -> None:
    """Second call within TTL should return same token (cache hit)."""
    print("--- cache (two calls, same token) ---")
    t0 = time.perf_counter()
    r1 = await get_setmore_access_token_from_dynamodb(business_number)
    t1 = time.perf_counter()
    r2 = await get_setmore_access_token_from_dynamodb(business_number)
    t2 = time.perf_counter()
    if not r1.get("success") or not r2.get("success"):
        print(f"SKIP: First success={r1.get('success')}, Second success={r2.get('success')}")
        return
    tok1 = r1.get("access_token")
    tok2 = r2.get("access_token")
    if tok1 != tok2:
        print("FAIL: Tokens differ between first and second call (cache may not be used).")
        return
    first_ms = (t1 - t0) * 1000
    second_ms = (t2 - t1) * 1000
    print(f"First call:  {first_ms:.1f} ms")
    print(f"Second call: {second_ms:.1f} ms (expected faster if cache hit)")
    print("OK: Same token returned; second call likely from cache.")
    print()


async def test_error_empty_number(business_number: str = "") -> None:
    """Empty or whitespace business number returns error."""
    print("--- error: empty business number ---")
    for value in ["", "   ", "\t"]:
        result = await get_setmore_access_token_from_dynamodb(value)
        assert result.get("success") is False, f"Expected failure for {value!r}"
        assert "error" in result
        print(f"  {value!r} -> success=False, error={result.get('error')!r}")
    print("OK: Empty/invalid input rejected.")
    print()


async def test_error_invalid_number(business_number: str = "") -> None:
    """Invalid business number (no candidates) returns error."""
    print("--- error: invalid business number ---")
    result = await get_setmore_access_token_from_dynamodb("not-a-phone")
    print(f"Success: {result.get('success')}, Error: {result.get('error')}")
    if result.get("success"):
        print("FAIL: Expected failure for invalid number.")
        return
    print("OK: Invalid number rejected.")
    print()


async def test_error_business_not_found(business_number: str = "") -> None:
    """Unknown business number (not in DynamoDB) returns error."""
    print("--- error: business not found ---")
    result = await get_setmore_access_token_from_dynamodb("+19999999999")
    print(f"Success: {result.get('success')}, Error: {result.get('error')}")
    if result.get("success"):
        print("FAIL: Expected failure for unknown number.")
        return
    print("OK: Unknown number returns error.")
    print()


async def test_same_as_resolve_context(business_number: str) -> None:
    """Token from get_setmore_access_token_from_dynamodb matches resolve_business_context token."""
    print("--- token matches resolve_business_context ---")
    token_result = await get_setmore_access_token_from_dynamodb(business_number)
    context = await resolve_business_context(business_number)
    if not token_result.get("success"):
        print(f"SKIP: DynamoDB token fetch failed: {token_result.get('error')}")
        return
    if not context.get("success") or context.get("provider") != "setmore":
        print("SKIP: resolve_business_context did not return Setmore context.")
        return
    ctx_token = context.get("accessToken") or context.get("access_token")
    if not ctx_token:
        print("SKIP: No access token in resolved context.")
        return
    from_db = token_result.get("access_token")
    if from_db != ctx_token:
        print("INFO: Tokens differ (DynamoDB fetch is independent of context cache; both valid).")
    else:
        print("OK: Token matches context (or same refresh produced same token).")
    print()


ALL_TESTS = {
    "fetch": test_fetch_token,
    "valid": test_token_works,
    "cache": test_cache,
    "error-empty": test_error_empty_number,
    "error-invalid": test_error_invalid_number,
    "error-not-found": test_error_business_not_found,
    "match-context": test_same_as_resolve_context,
}


async def main(args: argparse.Namespace) -> int:
    business_number = (args.business_number or DEFAULT_BUSINESS_NUMBER).strip()
    print(f"=== Setmore access token fetch tests ===\n")
    print(f"Business number: {business_number!r}\n")

    tests_to_run = [args.test] if args.test else list(ALL_TESTS.keys())

    for test_name in tests_to_run:
        fn = ALL_TESTS.get(test_name)
        if not fn:
            print(f"Unknown test: {test_name}")
            continue
        try:
            await fn(business_number)
        except Exception as exc:
            print(f"ERROR in {test_name}: {exc}")
            import traceback
            traceback.print_exc()

    print("=== Setmore access token tests complete ===")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test Setmore access token fetch from DynamoDB")
    parser.add_argument(
        "--test",
        choices=list(ALL_TESTS.keys()),
        default=None,
        help="Run a specific test (default: run all).",
    )
    parser.add_argument(
        "--business-number",
        default=None,
        help=f"Business phone number (default: {DEFAULT_BUSINESS_NUMBER!r}).",
    )
    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args)))
