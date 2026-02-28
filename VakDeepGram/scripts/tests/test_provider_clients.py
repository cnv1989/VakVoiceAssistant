#!/usr/bin/env python3
"""
Integration smoke test for provider clients using auth context/tokens from DynamoDB.

Usage:
  cd VakDeepGram
  python -m scripts.tests.test_provider_clients --business-number "510 405 4454"
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT_DIR, "src")
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, SRC_DIR)

from vakdeepgram.connection_store import resolve_business_context
from providers.clients import (
    SetmoreApiClient,
    SquareApiClient,
    ensure_provider_access_context,
)


async def run_for_business(business_number: str) -> int:
    context = await resolve_business_context(business_number)
    if not context.get("success"):
        print(f"FAIL: Unable to resolve business context: {context.get('error')}")
        return 1

    provider = (context.get("provider") or "square").lower()
    print(f"Provider: {provider}")
    auth = await ensure_provider_access_context(
        business_context=context,
        require_location=(provider == "square"),
    )
    if not auth.get("success"):
        print(f"FAIL: Unable to resolve auth context: {auth.get('error')}")
        return 1

    if provider == "setmore":
        client = SetmoreApiClient(
            auth["access_token"],
            refresh_token=auth.get("refresh_token"),
        )
        services = await client.fetch_services()
        staff = await client.fetch_staff()
        if not services.get("success"):
            print(f"FAIL: Setmore fetch_services failed: {services.get('error')}")
            return 1
        if not staff.get("success"):
            print(f"FAIL: Setmore fetch_staff failed: {staff.get('error')}")
            return 1
        print(f"Setmore services: {len(services.get('services') or [])}")
        print(f"Setmore staff: {len(staff.get('staffs') or [])}")
        return 0

    client = SquareApiClient(auth["access_token"])
    locations_response = await client.locations.list()
    from utils.square_helpers import parse_square_response

    parsed = parse_square_response(locations_response)
    if not parsed.get("success"):
        print(f"FAIL: Square locations.list failed: {parsed.get('error')}")
        return 1
    locations = parsed.get("payload", {}).get("locations") or []
    print(f"Square locations: {len(locations)}")
    print(f"Square location_id from context: {auth.get('location_id')}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test provider clients with auth tokens from DynamoDB")
    parser.add_argument(
        "--business-number",
        required=True,
        help="Business phone number from the BusinessNumber table (e.g. '510 405 4454').",
    )
    return parser


if __name__ == "__main__":
    args = _build_parser().parse_args()
    raise SystemExit(asyncio.run(run_for_business(args.business_number)))

