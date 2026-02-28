import argparse
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3

from vakdeepgram import config
from utils import setmore_api


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def _resolve_user_id(refresh_token: str) -> Optional[str]:
    result = await setmore_api.get_access_token(refresh_token)
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "Failed to obtain Setmore access token.")
    return result.get("user_id")


def _put_item(table_name: str, region: str, item: Dict[str, Any]) -> None:
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)
    table.put_item(Item=item)


def _build_item(
    refresh_token: str,
    account_id: str,
    user_id: str,
) -> Dict[str, Any]:
    return {
        "accountId": account_id,
        "userId": user_id,
        "refreshToken": refresh_token,
        "createdAt": _utc_now_iso(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed SetmoreAccount table with a refresh token.",
    )
    parser.add_argument("--refresh-token", required=True, help="Setmore refresh token.")
    parser.add_argument(
        "--account-id",
        help="Setmore account id (defaults to user_id from token response).",
    )
    parser.add_argument(
        "--user-id",
        help="Setmore user id (defaults to user_id from token response).",
    )
    parser.add_argument(
        "--table",
        default=config.settings.setmore_account_table,
        help="DynamoDB table name for Setmore accounts.",
    )
    parser.add_argument(
        "--region",
        default=config.settings.aws_region,
        help="AWS region for DynamoDB.",
    )
    args = parser.parse_args()

    refresh_token = args.refresh_token
    user_id = args.user_id or asyncio.run(_resolve_user_id(refresh_token))
    account_id = args.account_id or user_id

    if not user_id:
        raise RuntimeError("Setmore user_id could not be resolved; provide --user-id explicitly.")

    item = _build_item(refresh_token, account_id, user_id)
    _put_item(args.table, args.region, item)

    print("Seeded Setmore account record.")
    print(f"Table: {args.table}")
    print(f"accountId: {account_id}")
    print(f"userId: {user_id}")


if __name__ == "__main__":
    main()
