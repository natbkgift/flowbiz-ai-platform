"""Observability scaffolding (metrics/traces/alerts) for platform."""

from __future__ import annotations

from dataclasses import dataclass, field
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


def init_observability(settings: PlatformSettings) -> ObservabilityBundle:
    return ObservabilityBundle(
        metrics_mode=settings.metrics_mode,
        tracing_mode=settings.tracing_mode,
        alerts_mode=settings.alerts_mode,
    )

