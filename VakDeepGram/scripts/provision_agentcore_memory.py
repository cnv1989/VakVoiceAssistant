#!/usr/bin/env python3
"""Provision Bedrock AgentCore Memory instances per stage.

Creates one memory per stage with the naming convention:
    memory_id = {account_id}_{region}_{stage}

Usage:
    python scripts/provision_agentcore_memory.py [--region us-west-2] [--stages alpha,beta,prod]

Prints the memory IDs for each stage (to be set as AGENTCORE_MEMORY_ID env var).
"""
import argparse
import json
import sys

import boto3


DEFAULT_REGION = "us-west-2"
DEFAULT_STAGES = ["alpha", "beta", "prod"]

# Default memory strategies: semantic + summary extraction
DEFAULT_STRATEGIES = [
    {
        "semanticMemoryStrategy": {
            "name": "semantic",
            "description": "Stores customer interaction facts (preferences, booking history, names).",
            "namespaces": ["customer_facts"],
        }
    },
    {
        "summaryMemoryStrategy": {
            "name": "summary",
            "description": "Summarizes conversations for long-term recall.",
            "namespaces": ["{sessionId}/conversation_summaries"],
        }
    },
]


def get_account_id(sts_client) -> str:
    return sts_client.get_caller_identity()["Account"]


def list_existing_memories(memory_client) -> dict:
    """Return a dict of memory name prefix -> memory_id for existing memories.

    The API returns id like 'groommate_..._alpha-KuP9gY21Rq' (name + suffix).
    We extract the name prefix (before the last '-') to match against our naming.
    """
    memories = memory_client.list_memories()
    result = {}
    for m in memories:
        mid = m.get("id") or m.get("memoryId", "")
        # The id is "{name}-{randomSuffix}" — extract the name prefix
        # e.g. "groommate_844341423871_us_west_2_alpha-KuP9gY21Rq"
        last_dash = mid.rfind("-")
        if last_dash > 0:
            name_prefix = mid[:last_dash]
        else:
            name_prefix = mid
        result[name_prefix] = mid
    return result


def provision_memory(memory_client, name: str, stage: str) -> str:
    """Create a memory and return its ID."""
    result = memory_client.create_memory(
        name=name,
        description=f"GroomMate voice AI agent memory for {stage} stage",
        strategies=DEFAULT_STRATEGIES,
        event_expiry_days=90,
    )
    # The response structure may vary; try common paths
    if isinstance(result, dict):
        if "memory" in result:
            return result["memory"].get("id") or result["memory"].get("memoryId")
        if "id" in result:
            return result["id"]
        if "memoryId" in result:
            return result["memoryId"]
    print(f"  [DEBUG] create_memory response: {json.dumps(result, default=str)}")
    return str(result)


def main():
    parser = argparse.ArgumentParser(description="Provision AgentCore Memory per stage")
    parser.add_argument("--region", default=DEFAULT_REGION, help="AWS region")
    parser.add_argument("--stages", default=",".join(DEFAULT_STAGES), help="Comma-separated stages")
    args = parser.parse_args()

    region = args.region
    stages = [s.strip() for s in args.stages.split(",")]

    sts = boto3.client("sts", region_name=region)
    account_id = get_account_id(sts)

    from bedrock_agentcore.memory import MemoryClient
    memory_client = MemoryClient(region_name=region)
    existing = list_existing_memories(memory_client)

    results = {}
    for stage in stages:
        # Name must match [a-zA-Z][a-zA-Z0-9_]{0,47}
        safe_region = region.replace("-", "_")
        memory_name = f"groommate_{account_id}_{safe_region}_{stage}"
        if memory_name in existing:
            memory_id = existing[memory_name]
            print(f"[{stage}] Memory already exists: {memory_name} -> {memory_id}")
        else:
            memory_id = provision_memory(memory_client, memory_name, stage)
            print(f"[{stage}] Created memory: {memory_name} -> {memory_id}")
        results[stage] = memory_id

    print("\n--- Set these in CDK cdk.json or environment ---")
    for stage, memory_id in results.items():
        print(f"  {stage}: AGENTCORE_MEMORY_ID={memory_id}")

    return results


if __name__ == "__main__":
    main()
