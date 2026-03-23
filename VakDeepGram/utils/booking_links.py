"""
Async utility for tracking booking links sent to customers.

When a booking link is sent via SMS/WhatsApp, a record is written to the
UserBookingLink DynamoDB table.  The WhatsApp inbound endpoint uses this
to resolve which business a customer was last interacting with.

Table schema:
  PK: customerPhone  (E.164, e.g. +14155551234)
  SK: createdAt       (ISO-8601 timestamp, e.g. 2026-03-23T12:00:00Z)
  TTL: ttl            (epoch seconds, 90 days from creation)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

import aioboto3

logger = logging.getLogger("vak.booking_links")

BOOKING_LINK_TTL_DAYS = 90


async def write_booking_link(
    *,
    table_name: str,
    customer_phone: str,
    business_phone: str,
    booking_url: str,
    service_name: Optional[str] = None,
    staff_name: Optional[str] = None,
    channel: str = "sms",
    aws_region: str = "us-west-2",
) -> bool:
    """Write a booking link record to DynamoDB.

    Returns True on success, False on failure (never raises).
    """
    now = datetime.now(timezone.utc)
    ttl = int((now + timedelta(days=BOOKING_LINK_TTL_DAYS)).timestamp())

    item: Dict[str, Any] = {
        "customerPhone": customer_phone,
        "createdAt": now.isoformat(),
        "businessPhone": business_phone,
        "bookingUrl": booking_url,
        "channel": channel,
        "ttl": ttl,
    }
    if service_name:
        item["serviceName"] = service_name
    if staff_name:
        item["staffName"] = staff_name

    try:
        session = aioboto3.Session()
        async with session.resource("dynamodb", region_name=aws_region) as ddb:
            table = await ddb.Table(table_name)
            await table.put_item(Item=item)
        logger.info(
            "Wrote booking link: customer=%s business=%s channel=%s",
            customer_phone, business_phone, channel,
        )
        return True
    except Exception as exc:
        logger.error("Failed to write booking link record: %s", exc, exc_info=True)
        return False


async def get_latest_booking_link(
    *,
    table_name: str,
    customer_phone: str,
    aws_region: str = "us-west-2",
) -> Optional[Dict[str, Any]]:
    """Fetch the most recent booking link for a customer phone.

    Returns the DynamoDB item dict or None if no records found / on error.
    """
    try:
        session = aioboto3.Session()
        async with session.resource("dynamodb", region_name=aws_region) as ddb:
            table = await ddb.Table(table_name)
            response = await table.query(
                KeyConditionExpression="customerPhone = :pk",
                ExpressionAttributeValues={":pk": customer_phone},
                ScanIndexForward=False,  # newest first
                Limit=1,
            )
            items = response.get("Items", [])
            if items:
                logger.debug(
                    "Found latest booking link for %s: business=%s",
                    customer_phone, items[0].get("businessPhone"),
                )
                return items[0]
            return None
    except Exception as exc:
        logger.error("Failed to query booking links for %s: %s", customer_phone, exc, exc_info=True)
        return None
