"""Monitoring API response schemas."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from app.schemas.common import SchemaBase
from app.schemas.health import HealthStatus
from app.schemas.inventory import VpsInventorySummarySchema


class CollectorStatus(StrEnum):
    """Collector operational status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNAVAILABLE = "unavailable"


class ServiceState(StrEnum):
    """Managed service runtime state."""

    RUNNING = "running"
    STOPPED = "stopped"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"
    FAILED = "failed"


class AlertSeverity(StrEnum):
    """Alert severity level."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class CollectorHealthSchema(SchemaBase):
    """Health check result for a single collector."""

    name: str
    status: CollectorStatus
    latency_ms: float
    message: str | None = None
    last_collected_at: datetime | None = None
    available: bool = True


class CPUData(SchemaBase):
    """CPU utilization metrics."""

    percent: float
    per_cpu: list[float]
    count_logical: int
    count_physical: int | None = None
    load_average: list[float] = Field(default_factory=list)
    ctx_switches: int | None = None
    interrupts: int | None = None


class MemoryData(SchemaBase):
    """Memory utilization metrics."""

    total_bytes: int
    available_bytes: int
    used_bytes: int
    percent: float
    swap_total_bytes: int
    swap_used_bytes: int
    swap_percent: float


class DiskPartition(SchemaBase):
    """Disk partition usage."""

    device: str
    mountpoint: str
    fstype: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float


class DiskData(SchemaBase):
    """Disk metrics."""

    partitions: list[DiskPartition]
    primary_percent: float


class NetworkInterface(SchemaBase):
    """Per-interface network statistics."""

    name: str
    is_up: bool
    speed_mbps: int | None = None
    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int
    errin: int
    errout: int


class NetworkData(SchemaBase):
    """Network throughput metrics."""

    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int
    bytes_sent_per_sec: float
    bytes_recv_per_sec: float
    interfaces: list[NetworkInterface]


class ProcessInfo(SchemaBase):
    """Running process snapshot."""

    pid: int
    name: str
    username: str | None = None
    status: str
    cpu_percent: float | None = None
    memory_percent: float | None = None
    memory_rss_bytes: int | None = None
    create_time: datetime | None = None
    cmdline: str | None = None


class SystemInfoData(SchemaBase):
    """Host system information."""

    hostname: str
    platform: str
    platform_release: str
    platform_version: str
    architecture: str
    boot_time: datetime
    uptime_seconds: float
    python_version: str


class ManagedService(SchemaBase):
    """Service managed by systemd, supervisor, or detected locally."""

    id: str
    name: str
    status: ServiceState
    description: str | None = None
    source: str
    pid: int | None = None
    uptime_seconds: float | None = None
    memory_bytes: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class DatabaseStats(SchemaBase):
    """Database connection and health stats."""

    connected: bool
    version: str | None = None
    uptime_seconds: float | None = None
    connections: int | None = None
    memory_bytes: int | None = None
    ops_per_sec: float | None = None
    replication_lag_bytes: int | None = None
    message: str | None = None


class NetdataInfo(SchemaBase):
    """Netdata agent information."""

    connected: bool
    version: str | None = None
    hosts: int | None = None
    alarms: int | None = None
    message: str | None = None


class LogEntry(SchemaBase):
    """Log line from a monitored log file."""

    source: str
    timestamp: datetime | None = None
    level: str | None = None
    message: str
    line_number: int | None = None


class AlertSchema(SchemaBase):
    """Platform-generated alert from live thresholds."""

    id: str
    title: str
    message: str
    severity: AlertSeverity
    source: str
    timestamp: datetime
    metric: str | None = None
    value: float | None = None
    threshold: float | None = None
    acknowledged: bool = False


class ChartSeries(SchemaBase):
    """Time-series chart data."""

    name: str
    data: list[float]
    color: str


class ChartData(SchemaBase):
    """Chart with categories and series."""

    categories: list[str]
    series: list[ChartSeries]


class StatCardSchema(SchemaBase):
    """Dashboard statistic card."""

    id: str
    label: str
    value: str | float | int
    unit: str | None = None
    trend: str | None = None
    trend_value: str | None = None
    status: HealthStatus | None = None


class ServerNodeSchema(SchemaBase):
    """Server health node for dashboard."""

    id: str
    name: str
    status: HealthStatus
    score: int
    cpu: float
    memory: float
    disk: float


class ApplicationSchema(SchemaBase):
    """Detected application from live processes."""

    id: str
    name: str
    status: ServiceState
    version: str | None = None
    environment: str | None = None
    pid: int | None = None
    memory_bytes: int | None = None


class ActivitySchema(SchemaBase):
    """Recent platform activity."""

    id: str
    title: str
    description: str | None = None
    timestamp: datetime
    type: str
    status: str | None = None


class ListeningPortSchema(SchemaBase):
    """A bound network port."""

    port: int
    address: str
    family: str
    protocol: str
    pid: int | None = None
    process_name: str | None = None
    status: str


class PortsDataSchema(SchemaBase):
    """Collected port data."""

    ports: list[ListeningPortSchema]
    total: int


class PortsResponse(SchemaBase):
    """Listening ports on the host."""

    timestamp: datetime
    ports: list[ListeningPortSchema]
    total: int
    expected_ports: list[int] = Field(default_factory=list)
    missing_ports: list[int] = Field(default_factory=list)
    collectors: list[CollectorHealthSchema]


class ServerOverviewResponse(SchemaBase):
    """High-level server overview."""

    timestamp: datetime
    hostname: str
    status: HealthStatus
    health_score: int
    uptime_seconds: float
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    load_average: list[float]
    network_bytes_recv_per_sec: float
    network_bytes_sent_per_sec: float
    process_count: int
    listening_ports: int = 0
    missing_expected_ports: list[int] = Field(default_factory=list)
    collectors: list[CollectorHealthSchema]


class ServerResourcesResponse(SchemaBase):
    """Detailed resource utilization."""

    timestamp: datetime
    cpu: CPUData
    memory: MemoryData
    disk: DiskData
    collectors: list[CollectorHealthSchema]


class ServerNetworkResponse(SchemaBase):
    """Network utilization details."""

    timestamp: datetime
    network: NetworkData
    collectors: list[CollectorHealthSchema]


class ServicesResponse(SchemaBase):
    """All managed and detected services."""

    timestamp: datetime
    services: list[ManagedService]
    collectors: list[CollectorHealthSchema]


class ProcessesResponse(SchemaBase):
    """Running processes."""

    timestamp: datetime
    total: int
    processes: list[ProcessInfo]
    collectors: list[CollectorHealthSchema]


class LogsResponse(SchemaBase):
    """Recent log entries."""

    timestamp: datetime
    entries: list[LogEntry]
    sources: list[str]


class AlertsResponse(SchemaBase):
    """Active alerts from live thresholds."""

    timestamp: datetime
    alerts: list[AlertSchema]
    total: int


class DashboardResponse(SchemaBase):
    """Unified dashboard payload for the control plane UI."""

    timestamp: datetime
    health_score: int
    status: HealthStatus
    hostname: str
    environment: str
    version: str
    stats: list[StatCardSchema]
    servers: list[ServerNodeSchema]
    services: list[ManagedService]
    applications: list[ApplicationSchema]
    alerts: list[AlertSchema]
    activities: list[ActivitySchema]
    charts: dict[str, ChartData]
    load_average: list[float]
    network_throughput: dict[str, str]
    collectors: list[CollectorHealthSchema]
    inventory: VpsInventorySummarySchema | None = None


# Legacy compatibility for /monitoring/metrics
class SystemMetrics(SchemaBase):
    """High-level system metrics."""

    timestamp: datetime
    uptime_seconds: float | None = None
    cpu_percent: float | None = None
    memory_percent: float | None = None
    disk_percent: float | None = None
