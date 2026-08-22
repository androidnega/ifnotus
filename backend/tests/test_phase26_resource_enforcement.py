"""PHASE 26 — runtime resource enforcement."""

from app.services.platform.plan_matrix import MATRIX
from app.services.platform.resource_enforcement import (
    ResourceEnforcementService,
    limits_for_plan,
    limits_to_dict,
    runtime_family,
)


class _Plan:
    def __init__(self, key: str):
        self.features = {**MATRIX[key], "matrix_key": key}
        self.ram_gb = 2


def test_runtime_family_mapping() -> None:
    assert runtime_family("fastapi") == "python"
    assert runtime_family("express") == "node"
    assert runtime_family("laravel") == "php"


def test_student_pro_limits_match_phase_spec() -> None:
    limits = limits_for_plan(_Plan("student-pro"))
    assert limits.python_apps == 1
    assert limits.node_apps == 1
    assert limits.app_memory_mb == 512
    assert limits.max_workers == 2
    assert limits.max_processes == 10


def test_starter_blocks_python_apps() -> None:
    limits = limits_for_plan(_Plan("student-starter"))
    assert limits.python_apps == 0
    assert limits.node_apps == 0
    assert limits.php_apps == 2


def test_prlimit_wrap_when_available(monkeypatch) -> None:
    from app.services.platform.resource_enforcement import AppResourceLimits

    monkeypatch.setattr("app.services.platform.resource_enforcement.shutil.which", lambda _: "/usr/bin/prlimit")
    limits = AppResourceLimits(1, 1, 2, 512, 2, 10, 5, 256)
    wrapped = ResourceEnforcementService.wrap_command("node server.js", limits)
    assert wrapped.startswith("/usr/bin/prlimit")
    assert "--as=" in wrapped
    assert "--nproc=10" in wrapped
    assert "node server.js" in wrapped


def test_supervisor_block_includes_numprocs() -> None:
    from app.services.platform.resource_enforcement import AppResourceLimits

    limits = AppResourceLimits(1, 1, 2, 512, 2, 10, 5, 256)
    block = ResourceEnforcementService.supervisor_program_block(
        program="ifnotus_test",
        user_line="user=ifn_demo\n",
        directory="/srv/apps/x",
        start_cmd="node server.js",
        limits=limits,
        log_path="/srv/apps/x/.ifnotus/app.log",
        env_lines="",
    )
    assert "numprocs=2" in block
    assert "killasgroup=true" in block


def test_limits_to_dict_roundtrip() -> None:
    from app.services.platform.resource_enforcement import AppResourceLimits

    lim = AppResourceLimits(1, 1, 3, 512, 2, 10, 5, 256)
    d = limits_to_dict(lim)
    assert d["app_memory_mb"] == 512
    assert d["max_workers"] == 2
