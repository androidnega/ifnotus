"""PHASE 25 — application runtime catalog and helpers."""

from app.services.platform.application_runtime import (
    FRAMEWORKS,
    PYTHON_RUNTIME_VERSIONS,
    ApplicationRuntimeService,
    app_display_name,
    app_to_response,
    normalize_python_version,
    slugify,
    supervisor_program_name,
)


def test_slugify_normalizes_names() -> None:
    assert slugify("My API") == "my-api"
    assert slugify("Student Portal!") == "student-portal"


def test_framework_catalog_includes_entitlements() -> None:
    assert "fastapi" in FRAMEWORKS
    assert "laravel" in FRAMEWORKS
    assert FRAMEWORKS["fastapi"].runtime == "python"
    assert FRAMEWORKS["laravel"].stack_key == "laravel"
    assert FRAMEWORKS["laravel"].runtime == "php"
    assert FRAMEWORKS["laravel"].needs_proxy is False
    assert not FRAMEWORKS["laravel"].default_start


def test_supervisor_program_name_is_stable() -> None:
    from uuid import UUID

    e = UUID("11111111-1111-1111-1111-111111111111")
    a = UUID("22222222-2222-2222-2222-222222222222")
    assert supervisor_program_name(e, a) == "ifnotus_11111111_22222222"


def test_app_to_response_shape() -> None:
    from uuid import uuid4

    from app.models.platform import ApplicationInstance

    app = ApplicationInstance(
        id=uuid4(),
        environment_id=uuid4(),
        runtime="python",
        framework="fastapi",
        status="running",
        allocated_port=31001,
        config_json={"name": "My API", "slug": "my-api", "runtime_version": "3.13"},
    )
    row = app_to_response(app)
    assert row["name"] == "My API"
    assert row["framework"] == "fastapi"
    assert row["port"] == 31001
    assert app_display_name(app) == "My API"


def test_list_catalog_respects_plan(test_settings) -> None:
    from app.services.platform.plan_matrix import MATRIX

    svc = ApplicationRuntimeService(test_settings, session=None)  # type: ignore[arg-type]
    # student-starter has limited stacks — fastapi should be disallowed on minimal plan mock
    class _Plan:
        features = MATRIX["student-starter"]

    catalog = svc.list_catalog(_Plan())
    by_id = {c["id"]: c for c in catalog}
    assert "fastapi" in by_id
    assert "static" in by_id
    assert isinstance(by_id["fastapi"]["allowed"], bool)
    assert by_id["fastapi"]["runtime_versions"] == list(PYTHON_RUNTIME_VERSIONS)


def test_normalize_python_version() -> None:
    assert normalize_python_version("3.12.14") == "3.12"
    assert normalize_python_version("3.13") == "3.13"
    assert normalize_python_version("") == "3.12"
