"""Deployment history reader from filesystem."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.schemas.applications import DeploymentRecordSchema
from app.services.applications.config import ApplicationDefinition


class DeploymentHistoryReader:
    """Reads deployment records from JSON files on disk."""

    async def read(self, app: ApplicationDefinition) -> list[DeploymentRecordSchema]:
        history_dir = self._resolve_history_dir(app)
        if not history_dir.exists():
            return []

        records: list[DeploymentRecordSchema] = []
        for path in sorted(history_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                records.append(
                    DeploymentRecordSchema(
                        id=data.get("id", path.stem),
                        version=data.get("version", "unknown"),
                        status=data.get("status", "unknown"),
                        environment=data.get("environment", app.environment),
                        timestamp=self._parse_timestamp(data.get("timestamp")),
                        triggered_by=data.get("triggered_by"),
                        message=data.get("message"),
                        metadata=data.get("metadata", {}),
                    )
                )
            except Exception:
                continue

        return records[:50]

    def _resolve_history_dir(self, app: ApplicationDefinition) -> Path:
        if app.deployment.history_dir:
            return Path(app.deployment.history_dir)
        return app.root_path / ".ifnotus" / "deployments"

    @staticmethod
    def _parse_timestamp(value: object) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                pass
        return datetime.now(UTC)
