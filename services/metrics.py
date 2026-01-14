"""
Lightweight metrics helpers.

Currently emits metrics as structured logs so they can be scraped by
CloudWatch Logs Insights or forwarded to a metrics backend. This keeps
costs low while allowing later integration with CloudWatch Metrics or
other backends without changing call sites.
"""

import logging
from typing import Dict, Any, Optional

from config.settings import settings

metric_logger = logging.getLogger("metrics")


def _emit_metric(payload: Dict[str, Any]) -> None:
    """Emit a metric payload if metrics are enabled."""
    if not settings.enable_metrics:
        return
    # Ensure namespace and type are present
    payload.setdefault("namespace", settings.metrics_namespace)
    payload.setdefault("type", "metric")
    metric_logger.info(payload)


def record_count(name: str, value: int = 1, dimensions: Optional[Dict[str, str]] = None) -> None:
    """Record a simple count metric."""
    _emit_metric(
        {
            "name": name,
            "value": value,
            "unit": "Count",
            "dimensions": dimensions or {},
        }
    )


def record_latency(name: str, milliseconds: int, dimensions: Optional[Dict[str, str]] = None) -> None:
    """Record a latency metric in milliseconds."""
    _emit_metric(
        {
            "name": name,
            "value": milliseconds,
            "unit": "Milliseconds",
            "dimensions": dimensions or {},
        }
    )

