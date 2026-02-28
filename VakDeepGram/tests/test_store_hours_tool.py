from vakdeepgram.store_tools import get_store_hours_from_context


def test_get_store_hours_from_setmore_structured_context():
    ctx = {
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
            },
            "business_hours_text": "We are open Monday through Saturday from 09:00 to 18:00, and closed Sunday.",
        },
    }
    result = get_store_hours_from_context({"business_context": ctx})
    assert result["success"] is True
    assert len(result["by_day"]) == 7
    assert result["by_day"][-1]["day"] == "Sunday"
    assert result["by_day"][-1]["closed"] is True
    assert "closed Sunday" in result["human_summary"]


def test_get_store_hours_from_square_periods_context():
    ctx = {
        "provider": "square",
        "location": {
            "business_hours": {
                "periods": [
                    {"day_of_week": "MON", "start_local_time": "09:00", "end_local_time": "17:00"},
                    {"day_of_week": "TUE", "start_local_time": "09:00", "end_local_time": "17:00"},
                ]
            }
        },
    }
    result = get_store_hours_from_context({"business_context": ctx})
    assert result["success"] is True
    assert len(result["by_day"]) == 7
    monday = next(row for row in result["by_day"] if row["day_code"] == "MON")
    sunday = next(row for row in result["by_day"] if row["day_code"] == "SUN")
    assert monday["closed"] is False
    assert sunday["closed"] is True
