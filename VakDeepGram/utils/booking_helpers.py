"""
Shared helpers for Square booking availability, date parsing, and staff/service resolution.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import difflib

import config


def _as_dict(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


def select_service_variation_id(context: Dict[str, Any]) -> Optional[str]:
    services = context.get("services") or []
    for item in services:
        item = _as_dict(item)
        item_data = item.get("item_data") or {}
        variations = item_data.get("variations") or item.get("variations") or []
        for variation in variations:
            variation = _as_dict(variation)
            variation_id = variation.get("id")
            if variation_id:
                return variation_id
    return None


def match_service_variation(
    context: Dict[str, Any],
    service_name: Optional[str],
) -> tuple[Optional[str], Optional[int], Optional[int]]:
    if not service_name:
        return select_service_variation_id(context), None, None
    target = service_name.strip().lower()
    services = context.get("services") or []
    for item in services:
        item = _as_dict(item)
        item_data = item.get("item_data") or {}
        item_name = (item_data.get("name") or item.get("name") or "").strip().lower()
        variations = item_data.get("variations") or item.get("variations") or []
        for variation in variations:
            variation = _as_dict(variation)
            variation_data = variation.get("item_variation_data") or variation
            variation_name = (variation_data.get("name") or "").strip().lower()
            if target in item_name or target in variation_name:
                duration_ms = variation_data.get("service_duration")
                duration_minutes = (
                    int(duration_ms / 60000)
                    if duration_ms
                    else variation_data.get("duration_minutes")
                )
                version = variation.get("version") or variation_data.get("version")
                return variation.get("id"), duration_minutes, version
    fallback_id = select_service_variation_id(context)
    fallback_version = None
    services = context.get("services") or []
    for item in services:
        item = _as_dict(item)
        item_data = item.get("item_data") or {}
        variations = item_data.get("variations") or item.get("variations") or []
        for variation in variations:
            variation = _as_dict(variation)
            if variation.get("id") == fallback_id:
                fallback_version = variation.get("version")
                break
    return fallback_id, None, fallback_version


def suggest_services(
    context: Dict[str, Any],
    service_name: Optional[str],
    limit: int = 3,
) -> list[str]:
    if not service_name:
        return []
    services = context.get("services") or []
    candidates: list[str] = []
    for item in services:
        item = _as_dict(item)
        item_data = item.get("item_data") or {}
        item_name = item_data.get("name") or item.get("name")
        if item_name:
            candidates.append(str(item_name))
        variations = item_data.get("variations") or item.get("variations") or []
        for variation in variations:
            variation = _as_dict(variation)
            variation_data = variation.get("item_variation_data") or variation
            variation_name = variation_data.get("name")
            if variation_name:
                candidates.append(str(variation_name))
    if not candidates:
        return []
    unique_candidates = list(dict.fromkeys(candidates))
    matches = difflib.get_close_matches(
        service_name,
        unique_candidates,
        n=limit,
        cutoff=0.4,
    )
    if matches:
        return matches
    lower_target = service_name.strip().lower()
    contains = [
        name for name in unique_candidates if lower_target in name.strip().lower()
    ]
    return contains[:limit]




def normalize_iso(value: str) -> str:
    return value.replace("Z", "+00:00")


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(normalize_iso(value))


def isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def start_of_day(dt_value: datetime) -> datetime:
    return dt_value.replace(hour=0, minute=0, second=0, microsecond=0)


def end_of_day(dt_value: datetime) -> datetime:
    return dt_value.replace(hour=23, minute=59, second=59, microsecond=999000)


def ensure_minimum_range(start_at: datetime, end_at: datetime) -> tuple[datetime, datetime]:
    if end_at <= start_at or end_at - start_at < timedelta(days=1):
        end_at = start_at + timedelta(days=1)
    if end_at - start_at > timedelta(days=32):
        end_at = start_at + timedelta(days=32)
    return start_at, end_at


def resolve_location_timezone(context: Dict[str, Any]) -> Optional[str]:
    location = context.get("location") or {}
    return location.get("timezone") or context.get("timezone")


def availability_start_at(availability: Any) -> Optional[str]:
    if isinstance(availability, dict):
        return availability.get("start_at") or availability.get("startAt")
    for attr in ("start_at", "startAt"):
        value = getattr(availability, attr, None)
        if value:
            return value
    if hasattr(availability, "model_dump"):
        data = availability.model_dump()
        return data.get("start_at") or data.get("startAt")
    return None


def availability_duration_minutes(availability: Any) -> Optional[int]:
    segments = None
    if isinstance(availability, dict):
        segments = availability.get("appointment_segments") or availability.get("appointmentSegments")
    else:
        segments = getattr(availability, "appointment_segments", None) or getattr(
            availability,
            "appointmentSegments",
            None,
        )
    if not segments and hasattr(availability, "model_dump"):
        data = availability.model_dump()
        segments = data.get("appointment_segments") or data.get("appointmentSegments")
    if not segments:
        return None
    total = 0
    for segment in segments:
        duration = None
        intermission = 0
        if isinstance(segment, dict):
            duration = segment.get("duration_minutes") or segment.get("durationMinutes")
            intermission = segment.get("intermission_minutes") or segment.get("intermissionMinutes") or 0
        else:
            duration = getattr(segment, "duration_minutes", None) or getattr(segment, "durationMinutes", None)
            intermission = getattr(segment, "intermission_minutes", None) or getattr(segment, "intermissionMinutes", None) or 0
        if duration:
            total += int(duration) + int(intermission)
    return total or None


def availability_team_member_ids(availability: Any) -> list[str]:
    segments = None
    if isinstance(availability, dict):
        segments = availability.get("appointment_segments") or availability.get("appointmentSegments")
    else:
        segments = getattr(availability, "appointment_segments", None) or getattr(
            availability,
            "appointmentSegments",
            None,
        )
    if not segments and hasattr(availability, "model_dump"):
        data = availability.model_dump()
        segments = data.get("appointment_segments") or data.get("appointmentSegments")
    if not segments:
        return []

    team_member_ids: list[str] = []
    for segment in segments:
        member_id = None
        if isinstance(segment, dict):
            member_id = segment.get("team_member_id") or segment.get("teamMemberId")
        else:
            member_id = getattr(segment, "team_member_id", None) or getattr(segment, "teamMemberId", None)
        if member_id:
            team_member_ids.append(member_id)
    return team_member_ids


def availability_start_dt(availability: Any, tzinfo) -> Optional[datetime]:
    start_at = availability_start_at(availability)
    if not start_at:
        return None
    start_dt = parse_datetime(start_at)
    if start_dt.tzinfo is None and tzinfo:
        start_dt = start_dt.replace(tzinfo=tzinfo)
    elif tzinfo:
        start_dt = start_dt.astimezone(tzinfo)
    return start_dt


def availability_supports_start(
    availability: Any,
    start_dt: datetime,
    duration_minutes: Optional[int],
    tzinfo,
    tolerance_minutes: int,
) -> bool:
    availability_start = availability_start_dt(availability, tzinfo)
    if not availability_start:
        return False
    duration = availability_duration_minutes(availability) or duration_minutes
    if duration:
        end_dt = availability_start + timedelta(minutes=duration)
        requested_end = start_dt + timedelta(minutes=duration)
        return availability_start <= start_dt <= end_dt and requested_end <= end_dt
    delta = abs((availability_start - start_dt).total_seconds())
    return delta <= tolerance_minutes * 60


def resolve_available_staff(context: Dict[str, Any], availabilities: list[Any]) -> list[Dict[str, Any]]:
    staff = context.get("staff") or []
    staff_map = {}
    for member in staff:
        member_id = member.get("id")
        if not member_id:
            continue
        display_name = member.get("display_name") or " ".join(
            part for part in [member.get("given_name"), member.get("family_name")] if part
        ).strip()
        staff_map[member_id] = display_name or member_id

    available_ids = set()
    for availability in availabilities:
        for member_id in availability_team_member_ids(availability):
            available_ids.add(member_id)

    available_staff: list[Dict[str, Any]] = []
    for member_id in sorted(available_ids):
        available_staff.append(
            {
                "id": member_id,
                "display_name": staff_map.get(member_id, member_id),
            }
        )
    return available_staff


def resolve_staff_ids(context: Dict[str, Any], requested: list[Any]) -> tuple[list[str], list[str]]:
    staff = context.get("staff") or []
    if not requested:
        return [], []
    staff_by_id = {}
    staff_by_name = {}
    for member in staff:
        member_id = member.get("id")
        if not member_id:
            continue
        display_name = member.get("display_name") or " ".join(
            part for part in [member.get("given_name"), member.get("family_name")] if part
        ).strip()
        if display_name:
            staff_by_name[display_name.lower()] = member_id
        staff_by_id[member_id] = member_id

    resolved: list[str] = []
    unmatched: list[str] = []
    for value in requested:
        if not value:
            continue
        candidate = None
        if isinstance(value, dict):
            candidate = value.get("id") or value.get("display_name")
        elif isinstance(value, str):
            candidate = value
        if not candidate:
            continue
        candidate = candidate.strip()
        if candidate in staff_by_id:
            resolved.append(candidate)
            continue
        staff_id = staff_by_name.get(candidate.lower())
        if staff_id:
            resolved.append(staff_id)
            continue
        unmatched.append(candidate)
    return resolved, unmatched


def staff_display_name(context: Dict[str, Any], staff_id: Optional[str]) -> Optional[str]:
    if not staff_id:
        return None
    for member in context.get("staff") or []:
        if member.get("id") == staff_id:
            display_name = member.get("display_name") or " ".join(
                part for part in [member.get("given_name"), member.get("family_name")] if part
            ).strip()
            return display_name or staff_id
    return staff_id


def availability_window_minutes(service: Optional[str], duration_minutes: Optional[int]) -> int:
    mapping = config.settings.booking_availability_window_by_service or {}
    if service and mapping:
        normalized = service.strip().lower()
        for key in sorted(mapping.keys(), key=len, reverse=True):
            if key.lower() in normalized:
                return int(mapping[key])
    if duration_minutes:
        return int(duration_minutes)
    return int(config.settings.booking_availability_window_minutes or 30)


def format_availability_response(availabilities: list[Any], tzinfo) -> Dict[str, Any]:
    slots: list[Dict[str, Any]] = []
    ranges: list[Dict[str, Any]] = []
    slot_ranges: list[tuple[datetime, datetime]] = []

    for availability in availabilities:
        start_at = availability_start_at(availability)
        if not start_at:
            continue
        normalized_start = normalize_iso(start_at)
        try:
            start_dt = datetime.fromisoformat(normalized_start)
        except ValueError:
            start_dt = None
        if start_dt and tzinfo:
            start_dt = start_dt.astimezone(tzinfo)
        duration_minutes = availability_duration_minutes(availability)
        if start_dt and duration_minutes:
            end_dt = start_dt + timedelta(minutes=duration_minutes)
            slot_ranges.append((start_dt, end_dt))

        slots.append(
            {
                "start_at": start_dt.isoformat(timespec="seconds") if start_dt else start_at,
                "date": start_dt.date().isoformat() if start_dt else start_at.split("T")[0],
                "time": start_dt.time().strftime("%H:%M") if start_dt else start_at.split("T")[-1],
            }
        )

    slot_ranges.sort(key=lambda pair: pair[0])
    if slot_ranges:
        current_start, current_end = slot_ranges[0]
        for start_dt, end_dt in slot_ranges[1:]:
            if start_dt <= current_end:
                current_end = max(current_end, end_dt)
                continue
            if start_dt == current_end:
                current_end = end_dt
                continue
            ranges.append(
                {
                    "start_at": current_start.isoformat(timespec="seconds"),
                    "end_at": current_end.isoformat(timespec="seconds"),
                    "date": current_start.date().isoformat(),
                    "start_time": current_start.strftime("%H:%M"),
                    "end_time": current_end.strftime("%H:%M"),
                }
            )
            current_start, current_end = start_dt, end_dt
        ranges.append(
            {
                "start_at": current_start.isoformat(timespec="seconds"),
                "end_at": current_end.isoformat(timespec="seconds"),
                "date": current_start.date().isoformat(),
                "start_time": current_start.strftime("%H:%M"),
                "end_time": current_end.strftime("%H:%M"),
            }
        )

    if ranges and len(ranges) <= len(slots):
        return {"mode": "range", "ranges": ranges, "slots": []}
    return {"mode": "slots", "ranges": [], "slots": slots}


def booking_segments(booking: Any) -> list[Dict[str, Any]]:
    if isinstance(booking, dict):
        segments = booking.get("appointment_segments") or booking.get("appointmentSegments") or []
    else:
        segments = getattr(booking, "appointment_segments", None) or []
    normalized = []
    for segment in segments:
        if hasattr(segment, "model_dump"):
            segment = segment.model_dump()
        normalized.append(segment)
    return normalized


def booking_version(booking: Any) -> Optional[int]:
    if isinstance(booking, dict):
        return booking.get("version")
    return getattr(booking, "version", None)


def extract_booking_segment_details(booking: Any) -> Dict[str, Any]:
    segments = booking_segments(booking)
    if not segments:
        return {}
    segment = segments[0]
    return {
        "service_variation_id": segment.get("service_variation_id") or segment.get("serviceVariationId"),
        "service_variation_version": segment.get("service_variation_version")
        or segment.get("serviceVariationVersion"),
        "duration_minutes": segment.get("duration_minutes") or segment.get("durationMinutes"),
        "team_member_id": segment.get("team_member_id") or segment.get("teamMemberId"),
    }


def relative_range(name: str, now: datetime) -> tuple[datetime, datetime]:
    name = name.strip().upper()
    if name in {"TODAY", "CURRENT_DAY", "NOW"}:
        start = start_of_day(now)
        end = end_of_day(now)
        return start, end
    if name in {"TOMORROW", "NEXT_DAY", "TMRO", "TMRW"}:
        target = now + timedelta(days=1)
        return start_of_day(target), end_of_day(target)
    if name == "YESTERDAY":
        target = now - timedelta(days=1)
        return start_of_day(target), end_of_day(target)
    if name in {"NEXT_7_DAYS"}:
        return start_of_day(now), end_of_day(now + timedelta(days=6))
    if name in {"NEXT_14_DAYS"}:
        return start_of_day(now), end_of_day(now + timedelta(days=13))
    if name in {"NEXT_30_DAYS"}:
        return start_of_day(now), end_of_day(now + timedelta(days=29))
    if name in {"NEXT_WEEK"}:
        start = start_of_day(now - timedelta(days=now.weekday()) + timedelta(days=7))
        end = end_of_day(start + timedelta(days=6))
        return start, end
    if name in {"THIS_WEEK", "CURRENT_WEEK"}:
        start = start_of_day(now - timedelta(days=now.weekday()))
        end = end_of_day(start + timedelta(days=6))
        return start, end
    if name == "LAST_WEEK":
        start = start_of_day(now - timedelta(days=now.weekday()) - timedelta(days=7))
        end = end_of_day(start + timedelta(days=6))
        return start, end
    if name in {"THIS_WEEKEND", "WEEKEND"}:
        days_until_sat = (5 - now.weekday()) % 7
        start = start_of_day(now + timedelta(days=days_until_sat))
        end = end_of_day(start + timedelta(days=1))
        return start, end
    if name == "NEXT_WEEKEND":
        days_until_next_sat = (5 - now.weekday()) % 7 + 7
        start = start_of_day(now + timedelta(days=days_until_next_sat))
        end = end_of_day(start + timedelta(days=1))
        return start, end
    if name in {"THIS_MONTH", "CURRENT_MONTH"}:
        start = start_of_day(now.replace(day=1))
        next_month = (now.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = end_of_day(next_month - timedelta(days=1))
        return start, end
    if name == "NEXT_MONTH":
        next_month = (now.replace(day=28) + timedelta(days=4)).replace(day=1)
        start = start_of_day(next_month)
        next_next = (next_month.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = end_of_day(next_next - timedelta(days=1))
        return start, end
    if name == "LAST_MONTH":
        this_month = now.replace(day=1)
        last_month_end = this_month - timedelta(days=1)
        start = start_of_day(last_month_end.replace(day=1))
        end = end_of_day(last_month_end)
        return start, end
    raise ValueError(f"Unsupported relative range: {name}")


def resolve_weekday_range(value: str, now: datetime) -> Optional[tuple[datetime, datetime]]:
    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    value_lower = value.strip().lower()
    prefix = ""
    if value_lower.startswith("next "):
        prefix = "next "
        value_lower = value_lower.replace("next ", "", 1)
    if value_lower not in weekdays:
        return None
    target_day = weekdays[value_lower]
    delta = (target_day - now.weekday()) % 7
    if prefix and delta == 0:
        delta = 7
    target = now + timedelta(days=delta)
    return start_of_day(target), end_of_day(target)


def resolve_date_range(
    start_value: str,
    end_value: Optional[str],
    tzinfo,
) -> tuple[datetime, datetime]:
    now = datetime.now(tzinfo) if tzinfo else datetime.now()
    if start_value.strip().upper() in {
        "TODAY",
        "CURRENT_DAY",
        "NOW",
        "TOMORROW",
        "NEXT_DAY",
        "TMRO",
        "TMRW",
        "YESTERDAY",
        "THIS_WEEK",
        "CURRENT_WEEK",
        "NEXT_WEEK",
        "LAST_WEEK",
        "THIS_WEEKEND",
        "WEEKEND",
        "NEXT_WEEKEND",
        "THIS_MONTH",
        "CURRENT_MONTH",
        "NEXT_MONTH",
        "LAST_MONTH",
        "NEXT_7_DAYS",
        "NEXT_14_DAYS",
        "NEXT_30_DAYS",
    }:
        return relative_range(start_value, now)
    weekday_range = resolve_weekday_range(start_value, now)
    if weekday_range:
        return weekday_range
    start_dt = parse_datetime(start_value)
    if tzinfo and start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=tzinfo)
    if end_value:
        end_dt = parse_datetime(end_value)
        if tzinfo and end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=tzinfo)
        return start_dt, end_dt
    if "T" not in start_value:
        return start_of_day(start_dt), end_of_day(start_dt)
    return start_dt, start_dt + timedelta(days=7)
