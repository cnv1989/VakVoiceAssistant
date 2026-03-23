#!/usr/bin/env python3
"""
Seed realistic CallRecord entries into DynamoDB for testing the Call Analytics dashboard.

Usage:
    python scripts/seed_analytics.py --business-number +15551234567
    python scripts/seed_analytics.py --business-number +15551234567 --days 30 --count 120
    python scripts/seed_analytics.py --business-number +15551234567 --dry-run
"""
import argparse
import random
import uuid
from datetime import datetime, timedelta, timezone

import boto3

TABLE_NAME = "CallRecord-pxy5meaaojbaxjwedt6v6oidw4-NONE"
AWS_REGION = "us-west-2"

# Weighted outcomes: mostly completed, some forwarded, few error/no_context
_OUTCOMES = (
    ["completed"] * 14
    + ["forwarded"] * 4
    + ["error"] * 1
    + ["no_context"] * 1
)

# Salon/barber hours: weighted towards late morning and afternoon
_SALON_HOURS = (
    [9, 9] + [10, 10, 10] + [11, 11, 11] + [12, 12]
    + [13, 13] + [14, 14, 14] + [15, 15, 15] + [16, 16]
    + [17, 17] + [18]
)


def _make_record(business_number: str, day_offset: int) -> dict:
    now = datetime.now(timezone.utc)
    call_date = now - timedelta(days=day_offset)

    hour = random.choice(_SALON_HOURS)
    call_time = call_date.replace(
        hour=hour,
        minute=random.randint(0, 59),
        second=random.randint(0, 59),
        microsecond=0,
    )

    outcome = random.choice(_OUTCOMES)

    if outcome == "completed":
        duration_ms = random.randint(45_000, 280_000)   # 45s – 4.5min
    elif outcome == "forwarded":
        duration_ms = random.randint(15_000, 80_000)    # 15s – 1.3min (before transfer)
    elif outcome == "error":
        duration_ms = random.randint(5_000, 25_000)
    else:  # no_context
        duration_ms = random.randint(10_000, 40_000)

    booking_created = (outcome == "completed") and random.random() < 0.35
    customer_found = random.random() < 0.52
    sms_sent = booking_created and random.random() < 0.60
    forwarded = outcome == "forwarded"

    call_id = str(uuid.uuid4())
    return {
        "callId": call_id,
        "connectionId": f"ws-seed-{call_id[:12]}",
        "endpoint": "twilio_ws",
        "businessNumber": business_number,
        "startTime": call_time.isoformat(),
        "dateStr": call_time.strftime("%Y-%m-%d"),
        "hourOfDay": hour,
        "durationMs": duration_ms,
        "outcome": outcome,
        "bookingCreated": booking_created,
        "customerFound": customer_found,
        "smsBookingLinkSent": sms_sent,
        "forwardedCall": forwarded,
        "maxTokensReached": False,
        "userMessageCount": random.randint(1, 8),
        "toolCallCount": random.randint(1, 6),
        "toolCallErrorCount": random.randint(0, 1),
        "createdAt": call_time.isoformat(),
        "updatedAt": call_time.isoformat(),
        "__typename": "CallRecord",
        "_version": 1,
        "_lastChangedAt": int(call_time.timestamp() * 1000),
    }


def seed(
    business_number: str,
    days: int,
    count: int,
    table: str,
    region: str,
    dry_run: bool,
) -> None:
    records = []
    for _ in range(count):
        # Slightly bias towards more recent days (beta distribution)
        day_offset = max(0, min(days - 1, int(random.betavariate(1.5, 4) * days)))
        records.append(_make_record(business_number, day_offset))

    if dry_run:
        print(f"DRY RUN — would write {len(records)} records for {business_number}")
        for r in records[:3]:
            print(r)
        return

    dynamodb = boto3.resource("dynamodb", region_name=region)
    tbl = dynamodb.Table(table)
    print(f"Writing {len(records)} CallRecord entries to {table} ({region}) …")
    for i, item in enumerate(records):
        tbl.put_item(Item=item)
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(records)} written")
    print(f"Done! {len(records)} records seeded for {business_number}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed CallRecord entries for analytics dashboard testing."
    )
    parser.add_argument(
        "--business-number",
        required=True,
        help="Business phone number stored in BusinessNumber table (e.g. +15551234567)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Days of history to generate (default: 30)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="Number of records to create (default: 100)",
    )
    parser.add_argument(
        "--table",
        default=TABLE_NAME,
        help=f"DynamoDB table name (default: {TABLE_NAME})",
    )
    parser.add_argument(
        "--region",
        default=AWS_REGION,
        help=f"AWS region (default: {AWS_REGION})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print sample records without writing to DynamoDB",
    )
    args = parser.parse_args()
    seed(args.business_number, args.days, args.count, args.table, args.region, args.dry_run)
