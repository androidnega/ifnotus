"""Unit tests for per-environment live CPU/RAM process attribution."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.platform.environment_monitoring import _php_pool_name, environment_live_stats


def test_php_pool_name_matches_fpm_convention() -> None:
    assert _php_pool_name("kwofie.ifnotus.space") == "ifnotus-kwofie-ifnotus-space"
    assert _php_pool_name("YalleyDadzie.Online") == "ifnotus-yalleydadzie-online"


def test_environment_live_stats_without_psutil_matches(monkeypatch) -> None:
    class _FakeProc:
        def __init__(self, *, username: str, uid: int, rss: int, cpu: float, cmdline: list[str], cwd: str = "/"):
            self._username = username
            self._uid = uid
            self._rss = rss
            self._cpu = cpu
            self._cmdline = cmdline
            self._cwd = cwd
            self._primed = False

        def uids(self):
            return SimpleNamespace(real=self._uid)

        def username(self):
            return self._username

        def cmdline(self):
            return list(self._cmdline)

        def cwd(self):
            return self._cwd

        def name(self):
            return self._cmdline[0] if self._cmdline else "proc"

        def memory_info(self):
            return SimpleNamespace(rss=self._rss)

        def cpu_percent(self, interval=None):
            if not self._primed:
                self._primed = True
                return 0.0
            return self._cpu

    pool = _FakeProc(
        username="www-data",
        uid=33,
        rss=40 * 1024 * 1024,
        cpu=12.5,
        cmdline=["php-fpm: pool ifnotus-kwofie-ifnotus-space"],
    )
    other = _FakeProc(
        username="www-data",
        uid=33,
        rss=10 * 1024 * 1024,
        cpu=1.0,
        cmdline=["php-fpm: pool www"],
    )

    class _Psutil:
        Error = Exception
        NoSuchProcess = Exception
        AccessDenied = Exception
        ZombieProcess = Exception

        @staticmethod
        def process_iter(attrs=None):
            return [pool, other]

    monkeypatch.setitem(__import__("sys").modules, "psutil", _Psutil)
    # Avoid sleeping in unit tests.
    monkeypatch.setattr(
        "app.services.platform.environment_monitoring.time.sleep",
        lambda *_a, **_k: None,
    )

    stats = environment_live_stats(
        unix_username="ifn_60a35cb5",
        unix_uid=25100,
        document_root="/srv/apps/ifnotus-customers/kwofiee3host/kwofie.ifnotus.space",
        domain="kwofie.ifnotus.space",
        sample_seconds=0.01,
    )
    assert stats["available"] is True
    assert stats["process_count"] == 1
    assert stats["memory_rss_mb"] == 40.0
    assert stats["cpu_percent"] == 12.5
    assert "pool" in str(stats.get("source") or "")
