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


def emit_api_metrics(
    provider: str,
    api: str,
    duration_ms: float,
    success: bool,
    status_code: Optional[int] = None,
    error_type: Optional[str] = None,
) -> None:
    dims = {"provider": provider, "api": api}
    if status_code is not None:
        dims["status_code"] = str(status_code)
    if error_type:
        dims["error_type"] = error_type
    metrics = [
        {"name": f"{provider.capitalize()}ApiCallCount", "value": 1, "unit": "Count"},
        {"name": f"{provider.capitalize()}ApiLatencyMs", "value": duration_ms, "unit": "Milliseconds"},
    ]
    if not success:
        metrics.append({"name": f"{provider.capitalize()}ApiErrorCount", "value": 1, "unit": "Count"})
    emit_metrics(metrics, dims)


def emit_agent_metrics(
    endpoint: str,
    provider: str,
    duration_ms: float,
    success: bool,
    error_type: Optional[str] = None,
) -> None:
    dims = {"endpoint": endpoint, "provider": provider}
    if error_type:
        dims["error_type"] = error_type
    metrics = [
        {"name": "AgentInvokeCount", "value": 1, "unit": "Count"},
        {"name": "AgentResponseLatencyMs", "value": duration_ms, "unit": "Milliseconds"},
    ]
    if not success:
        metrics.append({"name": "AgentInvokeErrorCount", "value": 1, "unit": "Count"})
    emit_metrics(metrics, dims)


def emit_max_tokens_reached(endpoint: str, provider: str) -> None:
    emit_metrics(
        [{"name": "MaxTokensReachedCount", "value": 1, "unit": "Count"}],
        {"endpoint": endpoint, "provider": provider},
    )


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


def emit_active_connections(endpoint: str, count: int) -> None:
    emit_metrics(
        [{"name": "ActiveConnections", "value": count, "unit": "Count"}],
        {"endpoint": endpoint},
    )


def emit_deepgram_session_start(endpoint: str) -> None:
    emit_metrics(
        [{"name": "DeepgramSessionStartCount", "value": 1, "unit": "Count"}],
        {"endpoint": endpoint},
    )


def emit_deepgram_session_error(endpoint: str, error_type: Optional[str] = None) -> None:
    dims = {"endpoint": endpoint}
    if error_type:
        dims["error_type"] = error_type
    emit_metrics(
        [{"name": "DeepgramSessionErrorCount", "value": 1, "unit": "Count"}],
        dims,
    )


def emit_context_resolve_metrics(provider: str, duration_ms: float, success: bool) -> None:
    metrics = [
        {"name": "BusinessContextResolveLatencyMs", "value": duration_ms, "unit": "Milliseconds"},
        {"name": "BusinessContextResolveCount", "value": 1, "unit": "Count"},
    ]
    if not success:
        metrics.append({"name": "BusinessContextResolveErrorCount", "value": 1, "unit": "Count"})
    emit_metrics(metrics, {"provider": provider})


def emit_missing_business_number(provider: str, tool: str) -> None:
    emit_metrics(
        [{"name": "MissingBusinessNumberCount", "value": 1, "unit": "Count"}],
        {"provider": provider, "tool": tool},
    )


def emit_message_delivery(channel: str, success: bool) -> None:
    metrics = [{"name": f"{channel.capitalize()}SendCount", "value": 1, "unit": "Count"}]
    if not success:
        metrics.append({"name": f"{channel.capitalize()}SendErrorCount", "value": 1, "unit": "Count"})
    emit_metrics(metrics, {"channel": channel})
