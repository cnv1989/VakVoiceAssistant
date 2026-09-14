"""
Async utility for writing per-call analytics records to DynamoDB.

Records are written at the end of each call and contain key metrics
that power a call analytics dashboard.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import aioboto3

logger = logging.getLogger("vak.call_records")


async def write_call_record(
    *,
    connection_id: str,
    endpoint: str,
    duration_ms: float,
    table_name: str,
    aws_region: str = "us-west-2",
    business_number: Optional[str] = None,
    caller_number: Optional[str] = None,
    call_sid: Optional[str] = None,
    provider: Optional[str] = None,
    merchant_id: Optional[str] = None,
    location_id: Optional[str] = None,
    setmore_account_id: Optional[str] = None,
    outcome: str = "completed",
    user_message_count: int = 0,
    tool_call_count: int = 0,
    tool_call_error_count: int = 0,
    booking_created: bool = False,
    customer_found: bool = False,
    sms_booking_link_sent: bool = False,
    max_tokens_reached: bool = False,
    forwarded_call: bool = False,
    hour_of_day: Optional[int] = None,
    sms_sent_count: int = 0,
    whatsapp_sent_count: int = 0,
    transcript_s3_key: Optional[str] = None,
    recording_s3_key: Optional[str] = None,
    customer_id: Optional[str] = None,
    customer_first_name: Optional[str] = None,
    customer_last_name: Optional[str] = None,
) -> Optional[str]:
    """Write a call record to DynamoDB for analytics.

    Called from the WebSocket handler finally-block so it never raises —
    failures are logged but do not affect the call outcome.

    Returns the call_id that was written (useful for correlating the S3 key
    prefix with the DynamoDB record), or None on failure.
    """
    call_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    hour = hour_of_day if hour_of_day is not None else now.hour
    date_str = now.strftime("%Y-%m-%d")
    anon_caller: Optional[str] = None
    if caller_number:
        digits = "".join(c for c in caller_number if c.isdigit())
        if len(digits) >= 10:
            anon_caller = caller_number[:3] + "****" + caller_number[-4:]
        else:
            anon_caller = "***"

    item: dict = {
        "callId": call_id,
        "connectionId": connection_id,
        "endpoint": endpoint,
        "startTime": now.isoformat(),
        "dateStr": date_str,
        "hourOfDay": hour,
        "durationMs": int(duration_ms),
        "outcome": outcome,
        "userMessageCount": user_message_count,
        "toolCallCount": tool_call_count,
        "toolCallErrorCount": tool_call_error_count,
        "bookingCreated": booking_created,
        "customerFound": customer_found,
        "smsBookingLinkSent": sms_booking_link_sent,
        "maxTokensReached": max_tokens_reached,
        "forwardedCall": forwarded_call,
        "createdAt": now.isoformat(),
        "updatedAt": now.isoformat(),
    }
    if sms_sent_count:
        item["smsSentCount"] = sms_sent_count
    if whatsapp_sent_count:
        item["whatsappSentCount"] = whatsapp_sent_count
    if transcript_s3_key:
        item["transcriptS3Key"] = transcript_s3_key
    if recording_s3_key:
        item["recordingS3Key"] = recording_s3_key
    if customer_id:
        item["customerId"] = customer_id
    if customer_first_name:
        item["customerFirstName"] = customer_first_name
    if customer_last_name:
        item["customerLastName"] = customer_last_name
    # Amplify DataStore compatibility fields
    item["__typename"] = "CallRecord"
    item["_version"] = 1
    item["_lastChangedAt"] = int(now.timestamp() * 1000)

    if business_number:
        item["businessNumber"] = business_number
    if anon_caller:
        item["callerNumber"] = anon_caller
    if call_sid:
        item["callSid"] = call_sid
    if provider:
        item["provider"] = provider
    if merchant_id:
        item["merchantId"] = merchant_id
    if location_id:
        item["locationId"] = location_id
    if setmore_account_id:
        item["setmoreAccountId"] = setmore_account_id

    try:
        session = aioboto3.Session()
        async with session.resource("dynamodb", region_name=aws_region) as dynamodb:
            table = await dynamodb.Table(table_name)
            await table.put_item(Item=item)
        logger.info(
            "Call record written: callId=%s connectionId=%s businessNumber=%s "
            "durationMs=%d outcome=%s bookingCreated=%s forwardedCall=%s "
            "transcriptS3Key=%s recordingS3Key=%s",
            call_id,
            connection_id,
            business_number,
            int(duration_ms),
            outcome,
            booking_created,
            forwarded_call,
            transcript_s3_key,
            recording_s3_key,
        )
        return call_id
    except Exception as exc:
        logger.error(
            "Failed to write call record for %s: %s",
            connection_id,
            exc,
            exc_info=True,
        )
        return None
