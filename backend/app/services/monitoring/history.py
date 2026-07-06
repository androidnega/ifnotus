"""Rolling metrics history for dashboard charts."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class HistoryPoint:
    """Single metrics history sample."""

    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    network_recv_per_sec: float
    network_sent_per_sec: float


@dataclass
class MetricsHistory:
    """In-memory ring buffer of recent metric samples."""

    max_points: int = 60
    points: deque[HistoryPoint] = field(default_factory=deque)

    def __post_init__(self) -> None:
        self.points = deque(maxlen=self.max_points)

    def append(
        self,
        *,
        cpu_percent: float,
        memory_percent: float,
        network_recv_per_sec: float,
        network_sent_per_sec: float,
    ) -> None:
        self.points.append(
            HistoryPoint(
                timestamp=datetime.now(UTC),
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                network_recv_per_sec=network_recv_per_sec,
                network_sent_per_sec=network_sent_per_sec,
            )
        )

    def is_empty(self) -> bool:
        return len(self.points) == 0

    def categories(self) -> list[str]:
        return [p.timestamp.strftime("%H:%M") for p in self.points]

    def cpu_series(self) -> list[float]:
        return [round(p.cpu_percent, 1) for p in self.points]

    def memory_series(self) -> list[float]:
        return [round(p.memory_percent, 1) for p in self.points]

    def network_series(self) -> list[float]:
        recv_mbps = [round(p.network_recv_per_sec * 8 / 1_000_000, 2) for p in self.points]
        sent_mbps = [round(p.network_sent_per_sec * 8 / 1_000_000, 2) for p in self.points]
        return recv_mbps, sent_mbps
