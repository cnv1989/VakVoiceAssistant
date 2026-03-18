"""
Async utility for upserting VoiceCustomer records in DynamoDB.

A VoiceCustomer is a unique caller deduplicated by their phone number.

Primary key: customerId = "caller:{callerNumber}:{businessNumber}"
Fallback (no caller number): "{provider}:{providerCustomerId}:{businessNumber}"

On each call:
  - firstSeenAt is set only if not already present (if_not_exists)
  - lastSeenAt is always updated
  - callCount / bookingCount are incremented atomically (ADD)
  - name / phone / providerCustomerId are refreshed

The record is also linked to the CallRecord via the customerId field.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import aioboto3

logger = logging.getLogger("vak.customers")


def _extract_customer_fields(customer: dict) -> dict:
    """Normalise the customer dict (Square or Setmore) into common fields."""
    # Square: givenName / familyName / id / phoneNumber
    # Setmore: first_name / last_name / key / work_phone
    first_name = (
        customer.get("given_name")
        or customer.get("givenName")
        or customer.get("first_name")
        or ""
    )
    last_name = (
        customer.get("family_name")
        or customer.get("familyName")
        or customer.get("last_name")
        or ""
    )
    phone = (
        customer.get("phone_number")
        or customer.get("phoneNumber")
        or customer.get("work_phone")
        or ""
    )
    provider_id = (
        customer.get("id")
        or customer.get("key")
        or ""
    )
    return {
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone,
        "provider_id": provider_id,
    }


async def upsert_voice_customer(
    *,
    customer: dict,
    provider: str,
    business_number: str,
    caller_number: Optional[str] = None,
    booking_created: bool = False,
    table_name: str,
    aws_region: str = "us-west-2",
) -> Optional[str]:
    """Upsert a VoiceCustomer record and return the customerId.

    Never raises — failures are logged but do not affect the call outcome.
    """
    fields = _extract_customer_fields(customer)
    provider_customer_id = fields["provider_id"]

    # Deduplicate by caller number (phone) when available; fall back to provider ID.
    if caller_number:
        customer_id = f"caller:{caller_number}:{business_number}"
    elif provider_customer_id and business_number:
        customer_id = f"{provider}:{provider_customer_id}:{business_number}"
    else:
        return None

    if not business_number:
        return None

    now = datetime.now(timezone.utc).isoformat()

    try:
        session = aioboto3.Session()
        async with session.client("dynamodb", region_name=aws_region) as ddb:
            await ddb.update_item(
                TableName=table_name,
                Key={"customerId": {"S": customer_id}},
                UpdateExpression=(
                    "SET firstName = :fn, lastName = :ln, #ph = :phone, "
                    "provider = :prov, businessNumber = :bn, "
                    "providerCustomerId = :pcid, "
                    "callerNumber = :caller, "
                    "lastSeenAt = :now, "
                    "firstSeenAt = if_not_exists(firstSeenAt, :now), "
                    "#typename = :tn "
                    "ADD callCount :one, bookingCount :bc"
                ),
                ExpressionAttributeNames={
                    "#ph": "phone",
                    "#typename": "__typename",
                },
                ExpressionAttributeValues={
                    ":fn":    {"S": fields["first_name"]},
                    ":ln":    {"S": fields["last_name"]},
                    ":phone": {"S": fields["phone"]},
                    ":prov":  {"S": provider},
                    ":bn":    {"S": business_number},
                    ":pcid":  {"S": provider_customer_id},
                    ":now":   {"S": now},
                    ":caller": {"S": caller_number or ""},
                    ":tn":    {"S": "VoiceCustomer"},
                    ":one":   {"N": "1"},
                    ":bc":    {"N": "1" if booking_created else "0"},
                },
            )
        logger.info(
            "VoiceCustomer upserted: customerId=%s name=%s %s",
            customer_id,
            fields["first_name"],
            fields["last_name"],
        )
        return customer_id
    except Exception as exc:
        logger.error(
            "Failed to upsert VoiceCustomer %s: %s", customer_id, exc, exc_info=True
        )
        return None
