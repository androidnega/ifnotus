"""Worker task base classes."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class TaskStatus(StrEnum):
    """Task execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class TaskContext:
    """Execution context passed to task handlers."""

    task_id: UUID = field(default_factory=uuid4)
    enqueued_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    attempt: int = 1
    max_attempts: int = 3
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskResult:
    """Result of task execution."""

    status: TaskStatus
    data: dict[str, Any] | None = None
    error: str | None = None
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class BaseTask(ABC):
    """Abstract base for background tasks."""

    name: str
    queue: str = "default"
    max_attempts: int = 3

    @abstractmethod
    async def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        """Execute the task with the given payload."""
        ...
