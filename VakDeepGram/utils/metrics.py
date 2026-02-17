from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("vak.metrics")


def emit_metrics(
    metrics: List[Dict[str, Any]],
    dimensions: Optional[Dict[str, str]] = None,
    namespace: str = "VakDeepGram",
) -> None:
    """Emit metrics using CloudWatch Embedded Metric Format (EMF)."""
    dims = dimensions or {}
    metric_defs = []
    payload: Dict[str, Any] = {}

    for metric in metrics:
        name = metric["name"]
        unit = metric.get("unit", "Count")
        value = metric["value"]
        payload[name] = value
        metric_defs.append({"Name": name, "Unit": unit})

    payload.update(dims)
    payload["_aws"] = {
        "Timestamp": int(time.time() * 1000),
        "CloudWatchMetrics": [
            {
                "Namespace": namespace,
                "Dimensions": [list(dims.keys())] if dims else [[]],
                "Metrics": metric_defs,
            }
        ],
    }
    logger.info(json.dumps(payload))


def emit_tool_metrics(
    tool_name: str,
    provider: str,
    duration_ms: float,
    success: bool,
    error_type: Optional[str] = None,
) -> None:
    dims = {
        "provider": provider,
        "tool": tool_name,
    }
    metrics = [
        {"name": "ToolCallCount", "value": 1, "unit": "Count"},
        {"name": "ToolCallLatencyMs", "value": duration_ms, "unit": "Milliseconds"},
    ]
    if not success:
        metrics.append({"name": "ToolCallErrorCount", "value": 1, "unit": "Count"})
        if error_type:
            dims["error_type"] = error_type
    emit_metrics(metrics, dims)


def emit_forward_call_metrics(success: bool) -> None:
    metrics = [{"name": "ForwardedCallCount", "value": 1, "unit": "Count"}]
    if not success:
        metrics.append({"name": "ForwardedCallErrorCount", "value": 1, "unit": "Count"})
    emit_metrics(metrics, {"endpoint": "twilio"})


def emit_call_duration(endpoint: str, duration_ms: float) -> None:
    emit_metrics(
        [{"name": "CallDurationMs", "value": duration_ms, "unit": "Milliseconds"}],
        {"endpoint": endpoint},
    )


def emit_user_message_count(endpoint: str, session_id: str, count: int) -> None:
    emit_metrics(
        [{"name": "UserMessagesPerSession", "value": count, "unit": "Count"}],
        {"endpoint": endpoint},
    )
