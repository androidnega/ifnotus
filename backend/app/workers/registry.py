"""Task handler registry."""

from typing import TypeVar

from app.workers.base import BaseTask

T = TypeVar("T", bound=BaseTask)


class TaskRegistry:
    """Registry of background task handlers."""

    def __init__(self) -> None:
        self._tasks: dict[str, BaseTask] = {}

    def register(self, task: BaseTask) -> None:
        if task.name in self._tasks:
            raise ValueError(f"Task '{task.name}' is already registered.")
        self._tasks[task.name] = task

    def get(self, name: str) -> BaseTask | None:
        return self._tasks.get(name)

    def all(self) -> dict[str, BaseTask]:
        return dict(self._tasks)

    def task_names(self) -> list[str]:
        return list(self._tasks.keys())


task_registry = TaskRegistry()
