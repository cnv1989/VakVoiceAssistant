# Availability / Appointments — Verification

This doc summarizes how **available appointments** (slots) are fetched and confirms that Deepgram agent and Strands use the same business logic as the Setmore provider.

## Code paths

| Path | Entry | Setmore availability source |
|------|--------|-----------------------------|
| **Deepgram agent** | `agent_functions.check_availability` → `get_available_appointment_slots()` in `business_logic.py` | `setmore_api.fetch_slots` + **canonical helpers** from `providers.setmore.helpers` |
| **Strands** | `strands_tools.check_availability` (Setmore branch) | `setmore_api.fetch_slots` + **canonical helpers** from `providers.setmore.helpers` |
| **Setmore provider** | `providers/setmore/tools.check_availability` | `setmore_api.fetch_slots` + `providers.setmore.helpers` (same module) |

## Single source of truth

All three paths now use the **same** Setmore logic:

- **Date format**: `providers.setmore.helpers.format_date` → `DD/MM/YYYY` for Setmore slots API.
- **Service match**: `providers.setmore.helpers.match_service` (exact then partial).
- **Staff resolution**: `providers.setmore.helpers.resolve_staff_key` (by id or first_name + last_name).
- **Slot parsing**: `providers.setmore.helpers.slot_to_iso` — supports:
  - `"09:00 - 09:45"` (start - end)
  - `"9:00 AM"`, `"2:00 PM"`, `"12:00 PM"` (12-hour from Setmore API)
  - `"09:00"` (24-hour)

Previously, `business_logic` and `strands_tools` had local `_setmore_slot_to_iso` implementations that only parsed `"HH:MM"` via a simple split; they **failed** on Setmore’s 12-hour strings (e.g. `"9:00 AM"`), which could result in empty slots for the agent and Strands. That duplication has been removed; both now call into `providers.setmore.helpers`.

## Shared API call

All paths build the same payload and call the same API:

- `staff_key`, `service_key`, `selected_date`, optional `timezone`
- `setmore_api.fetch_slots(access_token, payload, refresh_token=...)`

So Deepgram agent, Strands, and the Setmore provider tool all get appointments from the same business logic and the same Setmore API.

## Tests

- `scripts.tests.test_booking_url_builder` — URL building (no API).
- `scripts.tests.test_available_appointments_next_week` — Resolves context and calls `setmore_api.fetch_slots` per day; uses `providers.setmore.helpers.slot_to_iso` for slot display.
- `scripts.tests.test_setmore_apis --test fetch-slots` — Direct Setmore slots API test.
