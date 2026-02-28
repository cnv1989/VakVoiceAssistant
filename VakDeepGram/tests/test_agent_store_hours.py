import pytest

from vakdeepgram.agent_functions import get_store_hours
from vakdeepgram.connection_store import set_connection_context, clear_connection_context


@pytest.mark.asyncio
async def test_agent_get_store_hours_returns_human_summary():
    connection_id = "test-hours-conn"
    set_connection_context(
        connection_id,
        {
            "provider": "setmore",
            "location": {
                "business_hours": {
                    "by_day": [
                        {"day_code": "MON", "day": "Monday", "open": "09:00", "close": "18:00", "closed": False},
                        {"day_code": "TUE", "day": "Tuesday", "open": "09:00", "close": "18:00", "closed": False},
                        {"day_code": "WED", "day": "Wednesday", "open": "09:00", "close": "18:00", "closed": False},
                        {"day_code": "THU", "day": "Thursday", "open": "09:00", "close": "18:00", "closed": False},
                        {"day_code": "FRI", "day": "Friday", "open": "09:00", "close": "18:00", "closed": False},
                        {"day_code": "SAT", "day": "Saturday", "open": "09:00", "close": "18:00", "closed": False},
                        {"day_code": "SUN", "day": "Sunday", "open": None, "close": None, "closed": True},
                    ]
                }
            },
        },
    )
    try:
        result = await get_store_hours({"connection_id": connection_id})
        assert result["success"] is True
        assert "human_summary" in result
        assert isinstance(result["human_summary"], str)
        assert len(result["by_day"]) == 7
    finally:
        clear_connection_context(connection_id)

