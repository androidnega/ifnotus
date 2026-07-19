"""Systemd and managed service classification for the VPS control panel."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import Settings
from app.repositories.applications import ApplicationRepository
from app.schemas.monitoring import ManagedService, ServiceCategory
from app.services.applications.discovery_runtime import RuntimeApplicationDiscovery

NOISE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^cloud-init",
        r"^plymouth",
        r"^modprobe@",
        r"^grub",
        r"^apt-daily",
        r"^apt-news",
        r"^dpkg-db-backup",
        r"^rescue$",
        r"^emergency$",
        r"^console-",
        r"^getty@",
        r"^serial-getty@",
        r"^systemd-",
        r"^initrd",
        r"^snapd\.",
        r"^user@",
        r"^session-",
        r"^dbus-",
        r"^networkd-",
        r"^udev",
        r"^keyboard-setup",
        r"^setvtrgb",
        r"^kmod-static",
        r"^finalrd",
        r"^unattended-upgrades",
        r"^motd-news",
        r"^e2scrub",
        r"^fstrim",
        r"^man-db",
        r"^update-notifier",
        r"^packagekit",
        r"^polkit",
        r"^accounts-daemon",
        r"^irqbalance",
        r"^multipathd",
        r"^lvm2-",
        r"^dm-event",
        r"^blk-availability",
        r"^open-iscsi",
        r"^iscsid",
        r"^udisks2",
        r"^thermald",
        r"^power-profiles",
        r"^fwupd",
        r"^apparmor",
        r"^ufw\.service$",
        r"^ufw$",
        r"^zfs-",
        r"^rbdmap",
        r"^ovsdb-",
        r"^openvswitch",
        r"^nftables",
        r"^iptables",
        r"^ip6tables",
        r"^ipset",
        r"^kbd$",
        r"^iscsi-",
        r"^ua-",
        r"^ubuntu-advantage",
        r"^sysstat",
        r"^systemd-vconsole",
        r"^systemd-oomd",
        r"^phpsessionclean",
    )
)

KNOWN_SERVICES: dict[str, tuple[ServiceCategory, bool]] = {
    "nginx": (ServiceCategory.WEB, True),
    "apache2": (ServiceCategory.WEB, True),
    "httpd": (ServiceCategory.WEB, True),
    "fail2ban": (ServiceCategory.SECURITY, True),
    "netdata": (ServiceCategory.MONITORING, True),
    "cron": (ServiceCategory.SYSTEM, True),
    "crond": (ServiceCategory.SYSTEM, True),
    "rsyslog": (ServiceCategory.SYSTEM, True),
    "redis": (ServiceCategory.CACHE, True),
    "redis-server": (ServiceCategory.CACHE, True),
    "mysql": (ServiceCategory.DATABASE, True),
    "mysqld": (ServiceCategory.DATABASE, True),
    "mariadb": (ServiceCategory.DATABASE, True),
    "postgresql": (ServiceCategory.DATABASE, True),
    "ifnotus-api": (ServiceCategory.APPLICATION, True),
    "ifnotus-worker": (ServiceCategory.QUEUE, True),
    "supervisor": (ServiceCategory.APPLICATION, True),
}

PREFIX_RULES: tuple[tuple[str, ServiceCategory, bool], ...] = (
    ("php-fpm", ServiceCategory.WEB, True),
    ("php8", ServiceCategory.WEB, True),
    ("php7", ServiceCategory.WEB, True),
    ("php", ServiceCategory.WEB, True),
    ("postgresql@", ServiceCategory.DATABASE, True),
    ("mysql@", ServiceCategory.DATABASE, True),
    ("mariadb@", ServiceCategory.DATABASE, True),
    ("gunicorn", ServiceCategory.APPLICATION, True),
    ("uvicorn", ServiceCategory.APPLICATION, True),
    ("celery", ServiceCategory.QUEUE, True),
    ("rq-worker", ServiceCategory.QUEUE, True),
    ("sidekiq", ServiceCategory.QUEUE, True),
    ("horizon", ServiceCategory.QUEUE, True),
    ("supervisor", ServiceCategory.APPLICATION, True),
)

PORT_HINTS: dict[str, list[int]] = {
    "nginx": [80, 443],
    "apache2": [80, 443],
    "httpd": [80, 443],
    "postgresql": [5432],
    "mysql": [3306],
    "mariadb": [3306],
    "redis": [6379],
    "redis-server": [6379],
    "netdata": [19999],
    "fail2ban": [],
}


@dataclass(frozen=True)
class AppBinding:
    unit: str
    app_id: str
    app_name: str
    managed: bool


class ServiceClassifier:
    """Classify raw managed services into VPS-relevant operational groups."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._apps = ApplicationRepository(settings)
        self._runtime = RuntimeApplicationDiscovery(settings)

    def classify(self, services: list[ManagedService]) -> list[ManagedService]:
        bindings = self._app_bindings()
        classified: list[ManagedService] = []
        seen: set[str] = set()

        for svc in services:
            key = f"{svc.source}:{svc.name.lower()}"
            if key in seen:
                continue
            seen.add(key)
            classified.append(self._classify_one(svc, bindings))

        return self._dedupe_families(
            sorted(classified, key=lambda s: (not s.relevant, s.category.value, s.display_name or s.name))
        )

    def filter_services(
        self,
        services: list[ManagedService],
        *,
        mode: str = "relevant",
        category: str | None = None,
    ) -> list[ManagedService]:
        items = services
        if mode != "all":
            items = [s for s in items if s.relevant]
        if category and category != "all":
            try:
                cat = ServiceCategory(category)
                items = [s for s in items if s.category == cat]
            except ValueError:
                pass
        # Drop inactive oneshot/timer noise even if somehow marked relevant
        items = [s for s in items if not self._is_inactive_oneshot(s)]
        return items

    @staticmethod
    def _is_inactive_oneshot(svc: ManagedService) -> bool:
        unit = (svc.unit_name or svc.name or "").lower()
        if unit in {"phpsessionclean", "logrotate", "man-db", "apt-daily", "apt-daily-upgrade"}:
            return svc.status.value in {"stopped", "unknown", "failed"}
        return False

    @classmethod
    def _service_family(cls, svc: ManagedService) -> str:
        unit = cls._normalize_unit(svc.unit_name or svc.name)
        source = (svc.source or "").lower()
        if unit.startswith("postgresql") or source == "postgresql":
            return "postgresql"
        if unit in {"redis", "redis-server"} or source == "redis":
            return "redis"
        if unit == "nginx" or source == "nginx":
            return "nginx"
        if unit in {"mysql", "mysqld", "mariadb"} or source == "mysql":
            return "mysql"
        if unit == "netdata" or source == "netdata":
            return "netdata"
        return f"{source}:{unit}"

    @classmethod
    def _dedupe_families(cls, services: list[ManagedService]) -> list[ManagedService]:
        """Collapse redis/redis-server, nginx duplicates, postgresql meta vs cluster."""
        best: dict[str, ManagedService] = {}
        for svc in services:
            family = cls._service_family(svc)
            current = best.get(family)
            if current is None or cls._service_rank(svc) > cls._service_rank(current):
                best[family] = svc
        return list(best.values())

    @staticmethod
    def _service_rank(svc: ManagedService) -> tuple:
        unit = (svc.unit_name or svc.name or "").lower()
        status = svc.status.value if hasattr(svc.status, "value") else str(svc.status)
        return (
            1 if status == "running" else 0,
            1 if svc.relevant else 0,
            1 if "@" in unit else 0,  # prefer postgresql@16-main over postgresql
            1 if svc.source == "systemd" else 0,
            len(unit),
        )

    def _app_bindings(self) -> dict[str, AppBinding]:
        bindings: dict[str, AppBinding] = {}
        for app in self._apps.list_all():
            unit = app.runtime.systemd
            if unit:
                normalized = self._normalize_unit(unit)
                bindings[normalized] = AppBinding(
                    unit=normalized,
                    app_id=app.id,
                    app_name=app.name,
                    managed=True,
                )
            unit = app.runtime.supervisor
            if unit:
                bindings[unit.lower()] = AppBinding(
                    unit=unit.lower(),
                    app_id=app.id,
                    app_name=app.name,
                    managed=True,
                )

        for item in self._runtime.discover():
            if item.systemd_unit:
                normalized = self._normalize_unit(item.systemd_unit)
                if normalized not in bindings:
                    bindings[normalized] = AppBinding(
                        unit=normalized,
                        app_id=item.registered_id or item.id,
                        app_name=item.name,
                        managed=item.registered,
                    )
            for variant in self._slug_variants(item.id, item.name):
                if variant not in bindings:
                    bindings[variant] = AppBinding(
                        unit=variant,
                        app_id=item.registered_id or item.id,
                        app_name=item.name,
                        managed=item.registered,
                    )
        return bindings

    @staticmethod
    def _slug_variants(app_id: str, name: str) -> set[str]:
        variants = {app_id.lower(), app_id.lower().replace("-", "_")}
        for raw in (name, app_id):
            variants.add(re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-"))
            variants.add(re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_"))
        return {v for v in variants if v}

    def _classify_one(self, svc: ManagedService, bindings: dict[str, AppBinding]) -> ManagedService:
        unit = self._normalize_unit(svc.unit_name or svc.name)
        display = svc.display_name or self._display_name(unit, svc.description)

        binding = bindings.get(unit) or bindings.get(svc.name.lower())
        if binding:
            category = ServiceCategory.APPLICATION
            if "worker" in unit or "celery" in unit or "queue" in unit:
                category = ServiceCategory.QUEUE
            return svc.model_copy(
                update={
                    "unit_name": unit,
                    "display_name": binding.app_name,
                    "category": category,
                    "relevant": True,
                    "managed_by_ifnotus": binding.managed,
                    "app_id": binding.app_id,
                    "ports": self._infer_ports(unit, svc.source),
                    "description": svc.description or f"Linked application: {binding.app_name}",
                }
            )

        if svc.source in {"nginx", "postgresql", "redis", "mysql", "netdata"}:
            category, relevant = self._known_category(svc.source)
            return svc.model_copy(
                update={
                    "unit_name": unit,
                    "display_name": display,
                    "category": category,
                    "relevant": True,
                    "ports": self._infer_ports(svc.source, svc.source),
                }
            )

        if svc.source == "supervisor":
            return svc.model_copy(
                update={
                    "unit_name": unit,
                    "display_name": display,
                    "category": ServiceCategory.APPLICATION,
                    "relevant": True,
                    "ports": [],
                }
            )

        known = KNOWN_SERVICES.get(unit)
        if known:
            category, relevant = known
            return svc.model_copy(
                update={
                    "unit_name": unit,
                    "display_name": display,
                    "category": category,
                    "relevant": relevant,
                    "ports": self._infer_ports(unit, svc.source),
                }
            )

        for prefix, category, relevant in PREFIX_RULES:
            if unit.startswith(prefix):
                return svc.model_copy(
                    update={
                        "unit_name": unit,
                        "display_name": display,
                        "category": category,
                        "relevant": relevant,
                        "ports": self._infer_ports(unit, svc.source),
                    }
                )

        if self._is_noise(unit):
            return svc.model_copy(
                update={
                    "unit_name": unit,
                    "display_name": display,
                    "category": ServiceCategory.SYSTEM,
                    "relevant": False,
                }
            )

        if svc.status.value == "running" and svc.source == "systemd":
            return svc.model_copy(
                update={
                    "unit_name": unit,
                    "display_name": display,
                    "category": ServiceCategory.SYSTEM,
                    "relevant": False,
                }
            )

        return svc.model_copy(
            update={
                "unit_name": unit,
                "display_name": display,
                "category": ServiceCategory.SYSTEM,
                "relevant": False,
            }
        )

    @staticmethod
    def _normalize_unit(name: str) -> str:
        value = name.strip().lower()
        if value.endswith(".service"):
            return value[:-8]
        return value

    @staticmethod
    def _display_name(unit: str, description: str | None) -> str:
        if unit in KNOWN_SERVICES:
            return unit.replace("-", " ").replace("_", " ").title()
        if description and len(description) < 48 and not description.startswith("/"):
            return description.strip()
        return unit.replace("-", " ").replace("_", " ").title()

    @staticmethod
    def _known_category(name: str) -> tuple[ServiceCategory, bool]:
        return KNOWN_SERVICES.get(name, (ServiceCategory.SYSTEM, True))

    @staticmethod
    def _is_noise(unit: str) -> bool:
        return any(pattern.search(unit) for pattern in NOISE_PATTERNS)

    @staticmethod
    def _infer_ports(unit: str, source: str) -> list[int]:
        if unit in PORT_HINTS:
            return PORT_HINTS[unit]
        if source in PORT_HINTS:
            return PORT_HINTS[source]
        if unit.startswith("postgresql"):
            return [5432]
        if unit.startswith("mysql") or unit.startswith("mariadb"):
            return [3306]
        if unit.startswith("php-fpm") or unit == "nginx":
            return [80, 443]
        return []
