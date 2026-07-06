"""Monitoring engine service — aggregates all collectors."""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from redis.asyncio import Redis

from app.core.config import Settings
from app.schemas.health import HealthStatus
from app.schemas.monitoring import (
    AlertSchema,
    AlertSeverity,
    AlertsResponse,
    ApplicationSchema,
    ActivitySchema,
    ChartData,
    ChartSeries,
    CPUData,
    DashboardResponse,
    DiskData,
    LogEntry,
    LogsResponse,
    ManagedService,
    MemoryData,
    NetworkData,
    ProcessesResponse,
    PortsResponse,
    ServerNetworkResponse,
    ServerOverviewResponse,
    ServerResourcesResponse,
    ServerNodeSchema,
    ServiceState,
    ServicesResponse,
    StatCardSchema,
    SystemMetrics,
)
from app.repositories.applications import ApplicationRepository
from app.services.applications.readers.deployments import DeploymentHistoryReader
from app.services.monitoring.history import MetricsHistory
from app.services.monitoring.registry import CollectorRegistry


def _format_bytes_per_sec(rate: float) -> str:
    if rate >= 1_000_000:
        return f"{rate * 8 / 1_000_000:.1f} Mbps"
    if rate >= 1_000:
        return f"{rate / 1_000:.1f} KB/s"
    return f"{rate:.0f} B/s"


def _format_uptime(seconds: float) -> str:
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    mins = int((seconds % 3600) // 60)
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


class MonitoringService:
    """Aggregates collectors into unified monitoring responses."""

    def __init__(self, settings: Settings, redis: Redis | None = None) -> None:
        self._settings = settings
        self._registry = CollectorRegistry(settings, redis)
        self._history = MetricsHistory(max_points=settings.monitoring_history_points)
        self._app_repository = ApplicationRepository(settings)
        self._deployment_reader = DeploymentHistoryReader()

    async def _core_metrics(self) -> tuple[CPUData, MemoryData, DiskData, NetworkData, object]:
        cpu, memory, disk, network, system_info = await asyncio.gather(
            self._registry.collect("cpu"),
            self._registry.collect("memory"),
            self._registry.collect("disk"),
            self._registry.collect("network"),
            self._registry.collect("system_info"),
        )
        self._history.append(
            cpu_percent=cpu.percent,
            memory_percent=memory.percent,
            network_recv_per_sec=network.bytes_recv_per_sec,
            network_sent_per_sec=network.bytes_sent_per_sec,
        )
        return cpu, memory, disk, network, system_info

    def _compute_health_score(
        self,
        cpu: float,
        memory: float,
        disk: float,
        collectors: list,
    ) -> int:
        resource_score = 100 - max(
            (cpu / self._settings.monitoring_cpu_alert_threshold) * 30,
            (memory / self._settings.monitoring_memory_alert_threshold) * 30,
            (disk / self._settings.monitoring_disk_alert_threshold) * 25,
        )
        unhealthy = sum(1 for c in collectors if c.status.value in {"unhealthy", "unavailable"})
        collector_penalty = min(unhealthy * 5, 30)
        return max(0, min(100, int(resource_score - collector_penalty)))

    def _overall_status(self, score: int) -> HealthStatus:
        if score >= 85:
            return HealthStatus.HEALTHY
        if score >= 60:
            return HealthStatus.DEGRADED
        return HealthStatus.UNHEALTHY

    async def get_system_metrics(self) -> SystemMetrics:
        """Legacy metrics endpoint backed by live collectors."""
        cpu, memory, disk, _, system_info = await self._core_metrics()
        return SystemMetrics(
            timestamp=datetime.now(UTC),
            uptime_seconds=system_info.uptime_seconds,
            cpu_percent=cpu.percent,
            memory_percent=memory.percent,
            disk_percent=disk.primary_percent,
        )

    async def get_integration_status(self) -> dict:
        """Return live integration status from collectors."""
        collectors = await self._registry.health_checks()
        status_map = {c.name: c for c in collectors}
        def _status(name: str) -> str:
            c = status_map.get(name)
            return c.status.value if c else "unknown"

        return {
            "netdata": {
                "configured": self._settings.netdata_url is not None,
                "status": _status("netdata"),
            },
            "nginx": {
                "configured": True,
                "status": _status("nginx"),
            },
            "github": {"configured": True},
            "supervisor": {
                "configured": Path(self._settings.supervisor_socket).exists(),
                "status": _status("supervisor"),
            },
            "systemd": {
                "configured": True,
                "status": _status("systemd"),
            },
            "postgresql": {
                "configured": True,
                "status": _status("postgresql"),
            },
            "redis": {
                "configured": True,
                "status": _status("redis"),
            },
            "mysql": {
                "configured": self._settings.mysql_url is not None,
                "status": _status("mysql"),
            },
        }

    async def get_server_overview(self) -> ServerOverviewResponse:
        cpu, memory, disk, network, system_info = await self._core_metrics()
        processes = await self._registry.collect("processes")
        ports_data = await self._registry.collect("ports")
        collectors = await self._registry.health_checks()
        score = self._compute_health_score(cpu.percent, memory.percent, disk.primary_percent, collectors)
        missing_ports = self._missing_expected_ports(ports_data.ports)

        return ServerOverviewResponse(
            timestamp=datetime.now(UTC),
            hostname=system_info.hostname,
            status=self._overall_status(score),
            health_score=score,
            uptime_seconds=system_info.uptime_seconds,
            cpu_percent=cpu.percent,
            memory_percent=memory.percent,
            disk_percent=disk.primary_percent,
            load_average=cpu.load_average,
            network_bytes_recv_per_sec=network.bytes_recv_per_sec,
            network_bytes_sent_per_sec=network.bytes_sent_per_sec,
            process_count=len(processes),
            listening_ports=ports_data.total,
            missing_expected_ports=missing_ports,
            collectors=collectors,
        )

    async def get_server_ports(self) -> PortsResponse:
        ports_data = await self._registry.collect("ports")
        collectors = await self._registry.health_checks()
        missing = self._missing_expected_ports(ports_data.ports)
        return PortsResponse(
            timestamp=datetime.now(UTC),
            ports=ports_data.ports,
            total=ports_data.total,
            expected_ports=self._settings.monitoring_expected_ports,
            missing_ports=missing,
            collectors=collectors,
        )

    def _missing_expected_ports(self, ports: list) -> list[int]:
        listening = {p.port for p in ports}
        return [p for p in self._settings.monitoring_expected_ports if p not in listening]

    async def get_server_resources(self) -> ServerResourcesResponse:
        cpu, memory, disk, _, _ = await self._core_metrics()
        collectors = await self._registry.health_checks()
        return ServerResourcesResponse(
            timestamp=datetime.now(UTC),
            cpu=cpu,
            memory=memory,
            disk=disk,
            collectors=collectors,
        )

    async def get_server_network(self) -> ServerNetworkResponse:
        _, _, _, network, _ = await self._core_metrics()
        collectors = await self._registry.health_checks()
        return ServerNetworkResponse(
            timestamp=datetime.now(UTC),
            network=network,
            collectors=collectors,
        )

    async def get_services(self) -> ServicesResponse:
        collectors_health = await self._registry.health_checks()
        results = await asyncio.gather(
            self._safe_collect_services("systemd"),
            self._safe_collect_services("supervisor"),
            self._safe_collect_single("nginx"),
            self._safe_collect_db_service("postgresql"),
            self._safe_collect_db_service("redis"),
            self._safe_collect_db_service("mysql"),
            self._safe_collect_netdata(),
            return_exceptions=False,
        )

        services: list[ManagedService] = []
        for batch in results:
            if isinstance(batch, list):
                services.extend(batch)
            elif batch is not None:
                services.append(batch)

        return ServicesResponse(
            timestamp=datetime.now(UTC),
            services=services,
            collectors=collectors_health,
        )

    async def _safe_collect_services(self, name: str) -> list[ManagedService]:
        try:
            return await self._registry.collect(name)
        except Exception:
            return []

    async def _safe_collect_single(self, name: str) -> ManagedService | None:
        try:
            return await self._registry.collect(name)
        except Exception:
            return None

    async def _safe_collect_db_service(self, name: str) -> ManagedService | None:
        try:
            stats = await self._registry.collect(name)
            status = ServiceState.RUNNING if stats.connected else ServiceState.FAILED
            return ManagedService(
                id=name,
                name=name,
                status=status,
                description=stats.version,
                source=name,
                extra={
                    "connections": stats.connections,
                    "memory_bytes": stats.memory_bytes,
                    "uptime_seconds": stats.uptime_seconds,
                },
            )
        except Exception:
            return None

    async def _safe_collect_netdata(self) -> ManagedService | None:
        try:
            info = await self._registry.collect("netdata")
            return ManagedService(
                id="netdata",
                name="netdata",
                status=ServiceState.RUNNING if info.connected else ServiceState.STOPPED,
                description=info.version,
                source="netdata",
                extra={"alarms": info.alarms, "hosts": info.hosts},
            )
        except Exception:
            return None

    async def get_processes(self, limit: int = 50) -> ProcessesResponse:
        processes = await self._registry.collect("processes")
        collectors = await self._registry.health_checks()
        return ProcessesResponse(
            timestamp=datetime.now(UTC),
            total=len(processes),
            processes=processes[:limit],
            collectors=collectors,
        )

    async def get_process_list(self, limit: int = 200) -> list:
        """Return raw process list for internal consumers."""
        processes = await self._registry.collect("processes")
        return processes[:limit]

    async def get_logs(self, lines: int = 100) -> LogsResponse:
        entries = await asyncio.to_thread(self._read_logs_sync, lines)
        return LogsResponse(
            timestamp=datetime.now(UTC),
            entries=entries,
            sources=self._settings.monitoring_log_paths,
        )

    def _read_logs_sync(self, lines: int) -> list[LogEntry]:
        entries: list[LogEntry] = []
        for path_str in self._settings.monitoring_log_paths:
            path = Path(path_str)
            if not path.exists() or not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, line in enumerate(content[-lines:]):
                if not line.strip():
                    continue
                level = self._detect_log_level(line)
                entries.append(
                    LogEntry(
                        source=path.name,
                        message=line.strip()[:2000],
                        level=level,
                        line_number=len(content) - lines + i if len(content) > lines else i + 1,
                    )
                )
        return entries[-lines:]

    @staticmethod
    def _detect_log_level(line: str) -> str | None:
        upper = line.upper()
        for level in ("CRITICAL", "ERROR", "WARNING", "WARN", "INFO", "DEBUG"):
            if level in upper:
                return level.lower()
        return None

    async def get_alerts(self) -> AlertsResponse:
        cpu, memory, disk, network, _ = await self._core_metrics()
        collectors = await self._registry.health_checks()
        ports_data = await self._registry.collect("ports")
        missing_ports = self._missing_expected_ports(ports_data.ports)
        alerts = self._generate_alerts(cpu, memory, disk, collectors, missing_ports, ports_data.ports)
        return AlertsResponse(
            timestamp=datetime.now(UTC),
            alerts=alerts,
            total=len(alerts),
        )

    def _generate_alerts(self, cpu, memory, disk, collectors, missing_ports=None, ports=None) -> list[AlertSchema]:
        now = datetime.now(UTC)
        alerts: list[AlertSchema] = []
        missing_ports = missing_ports or []
        ports = ports or []

        port_labels = {8000: "IFNOTUS API", 5173: "Frontend", 5432: "PostgreSQL", 6379: "Redis"}
        for port in missing_ports:
            label = port_labels.get(port, f"Service on port {port}")
            alerts.append(
                AlertSchema(
                    id=self._alert_id(f"port-missing-{port}"),
                    title=f"{label} not listening",
                    message=f"Expected port {port} is not bound — {label} may be down or misconfigured.",
                    severity=AlertSeverity.CRITICAL if port in {8000, 5432} else AlertSeverity.WARNING,
                    source="ports",
                    timestamp=now,
                    metric="listening_port",
                    value=float(port),
                )
            )

        if cpu.percent >= self._settings.monitoring_cpu_alert_threshold:
            alerts.append(
                AlertSchema(
                    id=self._alert_id("cpu-high"),
                    title="High CPU usage",
                    message=f"CPU usage at {cpu.percent}% exceeds {self._settings.monitoring_cpu_alert_threshold}% threshold.",
                    severity=AlertSeverity.CRITICAL if cpu.percent >= 95 else AlertSeverity.WARNING,
                    source="cpu",
                    timestamp=now,
                    metric="cpu_percent",
                    value=cpu.percent,
                    threshold=self._settings.monitoring_cpu_alert_threshold,
                )
            )

        if memory.percent >= self._settings.monitoring_memory_alert_threshold:
            alerts.append(
                AlertSchema(
                    id=self._alert_id("memory-high"),
                    title="High memory usage",
                    message=f"Memory usage at {memory.percent}% exceeds {self._settings.monitoring_memory_alert_threshold}% threshold.",
                    severity=AlertSeverity.CRITICAL if memory.percent >= 95 else AlertSeverity.WARNING,
                    source="memory",
                    timestamp=now,
                    metric="memory_percent",
                    value=memory.percent,
                    threshold=self._settings.monitoring_memory_alert_threshold,
                )
            )

        if disk.primary_percent >= self._settings.monitoring_disk_alert_threshold:
            alerts.append(
                AlertSchema(
                    id=self._alert_id("disk-high"),
                    title="High disk usage",
                    message=f"Disk usage at {disk.primary_percent}% exceeds {self._settings.monitoring_disk_alert_threshold}% threshold.",
                    severity=AlertSeverity.WARNING,
                    source="disk",
                    timestamp=now,
                    metric="disk_percent",
                    value=disk.primary_percent,
                    threshold=self._settings.monitoring_disk_alert_threshold,
                )
            )

        for collector in collectors:
            if collector.status.value == "unhealthy":
                alerts.append(
                    AlertSchema(
                        id=self._alert_id(f"collector-{collector.name}"),
                        title=f"Collector {collector.name} unhealthy",
                        message=collector.message or f"Collector {collector.name} failed health check.",
                        severity=AlertSeverity.CRITICAL,
                        source=collector.name,
                        timestamp=now,
                    )
                )
            elif collector.status.value == "degraded":
                alerts.append(
                    AlertSchema(
                        id=self._alert_id(f"collector-{collector.name}-degraded"),
                        title=f"Collector {collector.name} degraded",
                        message=collector.message or f"Collector {collector.name} is degraded.",
                        severity=AlertSeverity.WARNING,
                        source=collector.name,
                        timestamp=now,
                    )
                )

        return alerts

    @staticmethod
    def _alert_id(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    async def get_dashboard(self) -> DashboardResponse:
        overview = await self.get_server_overview()
        services_resp = await self.get_services()
        alerts_resp = await self.get_alerts()
        processes = await self._registry.collect("processes")

        stats = [
            StatCardSchema(id="health-score", label="Health Score", value=overview.health_score, unit="/100", status=overview.status),
            StatCardSchema(id="cpu", label="CPU Usage", value=overview.cpu_percent, unit="%", trend="up" if overview.cpu_percent > 70 else "neutral"),
            StatCardSchema(id="memory", label="RAM Usage", value=overview.memory_percent, unit="%", trend="up" if overview.memory_percent > 75 else "down"),
            StatCardSchema(id="disk", label="Disk Usage", value=overview.disk_percent, unit="%"),
            StatCardSchema(id="network-in", label="Network In", value=_format_bytes_per_sec(overview.network_bytes_recv_per_sec), unit=""),
            StatCardSchema(id="network-out", label="Network Out", value=_format_bytes_per_sec(overview.network_bytes_sent_per_sec), unit=""),
            StatCardSchema(id="load", label="Load Average", value=str(overview.load_average[0]) if overview.load_average else "0", unit="1m"),
            StatCardSchema(id="uptime", label="Uptime", value=_format_uptime(overview.uptime_seconds)),
        ]

        servers = [
            ServerNodeSchema(
                id="local",
                name=overview.hostname,
                status=overview.status,
                score=overview.health_score,
                cpu=overview.cpu_percent,
                memory=overview.memory_percent,
                disk=overview.disk_percent,
            )
        ]

        applications = await self._registered_applications(processes, services_resp.services)
        activities = await self._build_activities(alerts_resp.alerts, services_resp.services)
        charts = self._build_charts()

        return DashboardResponse(
            timestamp=datetime.now(UTC),
            health_score=overview.health_score,
            status=overview.status,
            hostname=overview.hostname,
            environment=self._settings.environment.value,
            version=self._settings.app_version,
            stats=stats,
            servers=servers,
            services=services_resp.services,
            applications=applications,
            alerts=alerts_resp.alerts,
            activities=activities,
            charts=charts,
            load_average=overview.load_average,
            network_throughput={
                "in": _format_bytes_per_sec(overview.network_bytes_recv_per_sec),
                "out": _format_bytes_per_sec(overview.network_bytes_sent_per_sec),
            },
            collectors=overview.collectors,
        )

    async def _registered_applications(
        self,
        processes,
        services: list[ManagedService],
    ) -> list[ApplicationSchema]:
        """Map YAML-registered applications to live runtime status."""
        service_by_name = {svc.name.lower(): svc for svc in services}
        apps: list[ApplicationSchema] = []

        for definition in self._app_repository.list_all():
            if not definition.enabled:
                continue

            pid, memory_bytes, status = self._resolve_app_runtime(definition, processes, service_by_name)
            apps.append(
                ApplicationSchema(
                    id=definition.id,
                    name=definition.name,
                    status=status,
                    version=definition.version,
                    environment=definition.environment,
                    pid=pid,
                    memory_bytes=memory_bytes,
                )
            )

        return apps

    def _resolve_app_runtime(
        self,
        definition,
        processes,
        service_by_name: dict[str, ManagedService],
    ) -> tuple[int | None, int | None, ServiceState]:
        """Resolve PID and status from process patterns or managed services."""
        for binding in (definition.runtime.supervisor, definition.runtime.systemd):
            if not binding:
                continue
            svc = service_by_name.get(binding.lower())
            if svc:
                return svc.pid, svc.memory_bytes, svc.status

        pattern = definition.runtime.process_match
        if pattern:
            try:
                regex = re.compile(pattern, re.IGNORECASE)
            except re.error:
                regex = None
            if regex:
                for proc in processes:
                    haystack = f"{proc.name} {proc.cmdline or ''}"
                    if regex.search(haystack):
                        return proc.pid, proc.memory_rss_bytes, ServiceState.RUNNING
                return None, None, ServiceState.STOPPED

        return None, None, ServiceState.UNKNOWN

    async def _build_activities(
        self,
        alerts,
        services: list[ManagedService],
    ) -> list[ActivitySchema]:
        activities: list[ActivitySchema] = []
        for alert in alerts[:5]:
            activities.append(
                ActivitySchema(
                    id=f"act-{alert.id}",
                    title=alert.title,
                    description=alert.message,
                    timestamp=alert.timestamp,
                    type="alert",
                    status=alert.severity.value,
                )
            )
        for svc in services:
            if svc.status in {ServiceState.FAILED, ServiceState.DEGRADED, ServiceState.STOPPED}:
                activities.append(
                    ActivitySchema(
                        id=f"act-svc-{svc.id}",
                        title=f"Service {svc.name} {svc.status.value}",
                        description=svc.description,
                        timestamp=datetime.now(UTC),
                        type="service",
                        status=svc.status.value,
                    )
                )

        for definition in self._app_repository.list_all():
            if not definition.enabled:
                continue
            deployments = await self._deployment_reader.read(definition)
            for dep in deployments[:3]:
                activities.append(
                    ActivitySchema(
                        id=f"act-dep-{definition.id}-{dep.id}",
                        title=f"Deployment {definition.name} {dep.version}",
                        description=dep.message or f"{dep.status} on {dep.environment}",
                        timestamp=dep.timestamp,
                        type="deployment",
                        status=dep.status,
                    )
                )

        activities.sort(key=lambda a: a.timestamp, reverse=True)
        return activities[:15]

    def _build_charts(self) -> dict[str, ChartData]:
        if self._history.is_empty():
            return {
                "cpu": ChartData(categories=[], series=[ChartSeries(name="CPU %", data=[], color="#0ea5e9")]),
                "memory": ChartData(categories=[], series=[ChartSeries(name="Memory %", data=[], color="#8b5cf6")]),
                "network": ChartData(categories=[], series=[ChartSeries(name="Throughput Mbps", data=[], color="#10b981")]),
            }

        recv, sent = self._history.network_series()
        return {
            "cpu": ChartData(
                categories=self._history.categories(),
                series=[ChartSeries(name="CPU %", data=self._history.cpu_series(), color="#0ea5e9")],
            ),
            "memory": ChartData(
                categories=self._history.categories(),
                series=[ChartSeries(name="Memory %", data=self._history.memory_series(), color="#8b5cf6")],
            ),
            "network": ChartData(
                categories=self._history.categories(),
                series=[
                    ChartSeries(name="Recv Mbps", data=recv, color="#10b981"),
                    ChartSeries(name="Sent Mbps", data=sent, color="#06b6d4"),
                ],
            ),
        }
