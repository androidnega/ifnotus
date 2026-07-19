"""Application Management Engine."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.core.config import Settings
from app.repositories.applications import ApplicationRepository
from app.schemas.applications import (
    ApplicationDeploymentsResponse,
    ApplicationDetailSchema,
    ApplicationEnvironmentResponse,
    ApplicationHealthSchema,
    ApplicationListResponse,
    ApplicationLogsResponse,
    ApplicationMetricsSchema,
    ApplicationRuntimeStatus,
    ApplicationSummarySchema,
    ApplicationType,
    GitStatusSchema,
    NginxSiteSchema,
    ServiceBindingSchema,
    SSLStatusSchema,
)
from app.schemas.health import HealthStatus
from app.services.applications.config import ApplicationDefinition
from app.services.applications.future import ApplicationModules
from app.services.applications.readers.deployments import DeploymentHistoryReader
from app.services.applications.readers.git import GitReader
from app.services.applications.readers.logs import ApplicationLogReader
from app.services.applications.readers.metrics import ApplicationMetricsReader
from app.services.applications.readers.nginx import NginxReader
from app.services.applications.readers.services import SupervisorReader, SystemdReader
from app.services.applications.readers.ssl import SSLReader
from app.services.applications.types import get_adapter
from app.schemas.inventory import AppReconciliationState
from app.services.applications.discovery_runtime import RuntimeApplicationDiscovery
from app.services.monitoring import MonitoringService


class ApplicationEngine:
    """Discovers, inspects, and manages registered applications."""

    def __init__(
        self,
        settings: Settings,
        monitoring: MonitoringService,
        modules: ApplicationModules | None = None,
    ) -> None:
        self._settings = settings
        self._repository = ApplicationRepository(settings)
        self._monitoring = monitoring
        self._modules = modules or ApplicationModules()

        self._git = GitReader()
        self._ssl = SSLReader()
        self._nginx = NginxReader()
        self._supervisor = SupervisorReader(settings)
        self._systemd = SystemdReader()
        self._deployments = DeploymentHistoryReader()
        self._logs = ApplicationLogReader()
        self._metrics = ApplicationMetricsReader(monitoring)
        self._runtime_discovery = RuntimeApplicationDiscovery(settings)

    def reload(self) -> list[ApplicationDefinition]:
        return self._repository.reload()

    async def list_applications(self) -> ApplicationListResponse:
        apps = self._repository.list_all()
        summaries: list[ApplicationSummarySchema] = []

        for app in apps:
            health = await self.get_health(app.id)
            summaries.append(
                ApplicationSummarySchema(
                    id=app.id,
                    name=app.name,
                    type=app.type,
                    environment=app.environment,
                    enabled=app.enabled,
                    status=health.runtime_status,
                    health=health.status,
                    health_score=health.score,
                    domain=app.ssl.domain or app.nginx.server_name,
                    root_path=str(app.root_path),
                    version=self._resolve_version(app),
                    registry_valid=app.registry_valid,
                    registry_errors=list(app.registry_errors),
                )
            )

        return ApplicationListResponse(
            timestamp=datetime.now(UTC),
            total=len(summaries),
            applications=summaries,
            **self._discovery_payload(),
        )

    def _discovery_payload(self) -> dict:
        inventory = self._runtime_discovery.discover()
        discovered = [a for a in inventory if not a.registered]
        on_disk = [
            a
            for a in inventory
            if a.reconciliation_state != AppReconciliationState.REGISTRY_MISSING_ROOT
        ]
        issues = [
            a
            for a in inventory
            if a.reconciliation_state
            not in (AppReconciliationState.REGISTERED, AppReconciliationState.DISCOVERED_UNREGISTERED)
        ]
        return {
            "discovered": discovered,
            "discovered_total": len(on_disk),
            "unregistered_discovered": len(discovered),
            "issues_count": len(issues),
        }

    async def get_application(self, app_id: str) -> ApplicationDetailSchema:
        app = self._repository.get(app_id)
        health = await self.get_health(app.id)
        git, nginx, ssl, supervisor, systemd = await self._gather_bindings(app)
        adapter = get_adapter(app.type)

        return ApplicationDetailSchema(
            id=app.id,
            name=app.name,
            type=app.type,
            environment=app.environment,
            enabled=app.enabled,
            status=health.runtime_status,
            health=health.status,
            health_score=health.score,
            domain=app.ssl.domain or app.nginx.server_name,
            root_path=str(app.root_path),
            version=self._resolve_version(app),
            description=app.description,
            tags=app.tags,
            paths=app.paths.model_dump(),
            runtime=app.runtime.model_dump(),
            git=git,
            ssl=ssl,
            nginx=nginx,
            supervisor=supervisor,
            systemd=systemd,
            modules=app.module_flags(),
        )

    async def get_health(self, app_id: str) -> ApplicationHealthSchema:
        app = self._repository.get(app_id)
        git, nginx, ssl, supervisor, systemd = await self._gather_bindings(app)
        metrics = await self._metrics.read(app)

        runtime_status = self._resolve_runtime_status(
            app,
            supervisor,
            systemd,
            metrics.process_count,
            nginx,
        )
        checks: dict[str, HealthStatus] = {}
        messages: list[str] = []
        score = 100

        if app.root_path.exists():
            checks["filesystem"] = HealthStatus.HEALTHY
        else:
            checks["filesystem"] = HealthStatus.UNHEALTHY
            score -= 40
            messages.append(f"Root path does not exist: {app.root_path}")

        checks["runtime"] = self._runtime_to_health(runtime_status)
        if runtime_status == ApplicationRuntimeStatus.STOPPED:
            score -= 35
            messages.append("Application process is not running.")
        elif runtime_status == ApplicationRuntimeStatus.FAILED:
            score -= 50
            messages.append("Application process has failed.")
        elif runtime_status == ApplicationRuntimeStatus.DEGRADED:
            score -= 15

        if nginx.configured:
            checks["nginx"] = (
                HealthStatus.HEALTHY if nginx.enabled else HealthStatus.DEGRADED
            )
            if not nginx.enabled:
                score -= 10
                messages.append("Nginx site is not enabled.")

        if ssl.configured and ssl.status:
            checks["ssl"] = ssl.status
            if ssl.status == HealthStatus.UNHEALTHY:
                score -= 25
                messages.append(ssl.message or "SSL certificate is invalid or expired.")
            elif ssl.status == HealthStatus.DEGRADED:
                score -= 10
                messages.append(ssl.message or "SSL certificate expires soon.")

        if git.available and git.dirty:
            checks["git"] = HealthStatus.DEGRADED
            score -= 5
            messages.append("Git working tree has uncommitted changes.")

        overall = self._score_to_health(max(0, min(100, score)))

        return ApplicationHealthSchema(
            status=overall,
            score=max(0, min(100, score)),
            runtime_status=runtime_status,
            checks=checks,
            messages=messages,
            git=git,
            ssl=ssl,
            nginx=nginx,
            supervisor=supervisor,
            systemd=systemd,
        )

    async def get_metrics(self, app_id: str) -> ApplicationMetricsSchema:
        app = self._repository.get(app_id)
        return await self._metrics.read(app)

    async def get_logs(self, app_id: str, lines: int = 100) -> ApplicationLogsResponse:
        app = self._repository.get(app_id)
        sources, entries = self._logs.read(app, lines=lines)
        return ApplicationLogsResponse(
            timestamp=datetime.now(UTC),
            application_id=app.id,
            sources=sources,
            entries=entries,
        )

    async def get_environment(self, app_id: str) -> ApplicationEnvironmentResponse:
        app = self._repository.get(app_id)
        variables: dict[str, str] = {}
        env_file = app.paths.env_file

        if env_file:
            from pathlib import Path

            path = Path(env_file)
            if path.exists():
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, _ = line.partition("=")
                    variables[key.strip()] = "***"

        return ApplicationEnvironmentResponse(
            timestamp=datetime.now(UTC),
            application_id=app.id,
            env_file=env_file,
            variables=variables,
        )

    async def get_deployments(self, app_id: str) -> ApplicationDeploymentsResponse:
        app = self._repository.get(app_id)

        if self._modules.deployment:
            records = await self._modules.deployment.list_deployments(app)
        else:
            records = await self._deployments.read(app)

        return ApplicationDeploymentsResponse(
            timestamp=datetime.now(UTC),
            application_id=app.id,
            deployments=records,
            module_enabled=app.deployment.enabled,
        )

    async def _gather_bindings(
        self, app: ApplicationDefinition
    ) -> tuple[GitStatusSchema, NginxSiteSchema, SSLStatusSchema, ServiceBindingSchema, ServiceBindingSchema]:
        git_path = app.git.repository or str(app.root_path)
        results = await asyncio.gather(
            self._git.read(git_path),
            asyncio.to_thread(
                self._nginx.read, app.nginx.site, app.nginx.server_name
            ),
            self._ssl.read(app.ssl.certificate, app.ssl.domain),
            self._supervisor.read(app.runtime.supervisor),
            self._systemd.read(app.runtime.systemd),
        )
        return results  # type: ignore[return-value]

    def _resolve_version(self, app: ApplicationDefinition) -> str | None:
        adapter = get_adapter(app.type)
        return adapter.detect_version(app) or app.version

    @staticmethod
    def _resolve_runtime_status(
        app: ApplicationDefinition,
        supervisor: ServiceBindingSchema,
        systemd: ServiceBindingSchema,
        process_count: int,
        nginx: NginxSiteSchema,
    ) -> ApplicationRuntimeStatus:
        if supervisor.configured and supervisor.status:
            return supervisor.status
        if systemd.configured and systemd.status:
            return systemd.status
        if process_count > 0:
            return ApplicationRuntimeStatus.RUNNING

        # Static sites have no dedicated app process — nginx + files mean "running".
        if app.type == ApplicationType.STATIC_SITE:
            root_ok = app.root_path.exists()
            has_index = (
                (app.root_path / "index.html").exists()
                or (app.root_path / "dist" / "index.html").exists()
            )
            nginx_ok = bool(nginx.configured and nginx.enabled)
            if root_ok and (nginx_ok or has_index):
                return ApplicationRuntimeStatus.RUNNING
            if root_ok:
                return ApplicationRuntimeStatus.DEGRADED
            return ApplicationRuntimeStatus.STOPPED

        return ApplicationRuntimeStatus.STOPPED

    @staticmethod
    def _runtime_to_health(status: ApplicationRuntimeStatus) -> HealthStatus:
        if status == ApplicationRuntimeStatus.RUNNING:
            return HealthStatus.HEALTHY
        if status in {ApplicationRuntimeStatus.DEGRADED}:
            return HealthStatus.DEGRADED
        if status in {ApplicationRuntimeStatus.STOPPED, ApplicationRuntimeStatus.FAILED}:
            return HealthStatus.UNHEALTHY
        return HealthStatus.DEGRADED

    @staticmethod
    def _score_to_health(score: int) -> HealthStatus:
        if score >= 85:
            return HealthStatus.HEALTHY
        if score >= 60:
            return HealthStatus.DEGRADED
        return HealthStatus.UNHEALTHY
