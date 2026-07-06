"""Monitoring collectors package."""

from app.services.monitoring.collectors.cpu import CPUCollector
from app.services.monitoring.collectors.disk import DiskCollector
from app.services.monitoring.collectors.memory import MemoryCollector
from app.services.monitoring.collectors.mysql import MySQLCollector
from app.services.monitoring.collectors.netdata import NetdataCollector
from app.services.monitoring.collectors.network import NetworkCollector
from app.services.monitoring.collectors.nginx import NginxCollector
from app.services.monitoring.collectors.postgresql import PostgreSQLCollector
from app.services.monitoring.collectors.processes import ProcessesCollector
from app.services.monitoring.collectors.redis_collector import RedisCollector
from app.services.monitoring.collectors.supervisor import SupervisorCollector
from app.services.monitoring.collectors.system_info import SystemInfoCollector
from app.services.monitoring.collectors.systemd import SystemdCollector

__all__ = [
    "CPUCollector",
    "MemoryCollector",
    "DiskCollector",
    "NetworkCollector",
    "ProcessesCollector",
    "SystemInfoCollector",
    "SystemdCollector",
    "SupervisorCollector",
    "NginxCollector",
    "MySQLCollector",
    "PostgreSQLCollector",
    "RedisCollector",
    "NetdataCollector",
]
