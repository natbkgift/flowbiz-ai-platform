"""Observability scaffolding (metrics/traces/alerts) for platform."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from sys import stdout
from time import time

from platform_app.config import PlatformSettings


@dataclass
class RequestEvent:
    route: str
    status_code: int
    duration_ms: float
    timestamp: float = field(default_factory=time)


@dataclass
class ObservabilityBundle:
    metrics_mode: str
    tracing_mode: str
    alerts_mode: str
    recent_events: list[RequestEvent] = field(default_factory=list)

    def record(self, route: str, status_code: int, duration_ms: float) -> None:
        self.recent_events.append(
            RequestEvent(route=route, status_code=status_code, duration_ms=duration_ms)
        )
        if len(self.recent_events) > 200:
            del self.recent_events[0]


class JsonLogFormatter(logging.Formatter):
    """Minimal JSON formatter that keeps request bodies and secrets out of logs."""

    extra_fields = (
        "request_id",
        "correlation_id",
        "http_method",
        "http_path",
        "status_code",
        "duration_ms",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field_name in self.extra_fields:
            if hasattr(record, field_name):
                payload[field_name] = getattr(record, field_name)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def configure_structured_logging(settings: PlatformSettings) -> None:
    logger = logging.getLogger("platform_app")
    logger.handlers.clear()
    handler = logging.StreamHandler(stdout)
    handler.setFormatter(JsonLogFormatter())
    logger.addHandler(handler)
    logger.setLevel(settings.log_level.upper())
    logger.propagate = False


def init_observability(settings: PlatformSettings) -> ObservabilityBundle:
    return ObservabilityBundle(
        metrics_mode=settings.metrics_mode,
        tracing_mode=settings.tracing_mode,
        alerts_mode=settings.alerts_mode,
    )
