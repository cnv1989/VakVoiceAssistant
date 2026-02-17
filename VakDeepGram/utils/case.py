from __future__ import annotations

from typing import Any


def to_snake_case_key(key: str) -> str:
    out: list[str] = []
    for ch in key:
        if ch.isupper():
            if out:
                out.append("_")
            out.append(ch.lower())
        else:
            out.append(ch)
    return "".join(out)


def to_snake_case(value: Any) -> Any:
    if isinstance(value, dict):
        return {to_snake_case_key(k): to_snake_case(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_snake_case(item) for item in value]
    return value
