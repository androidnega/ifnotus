from app.services.platform.student_hostname import (
    LEGACY_STUDENT_ZONE,
    RESERVED_LABELS,
    STUDENT_ZONE,
    StudentHostnameService,
    is_active_student_hostname,
    is_legacy_student_hostname,
    is_student_hostname,
    normalize_surname,
    student_hostname,
    student_label,
    student_zone_extension,
    student_zone_of,
)
from app.services.platform.reserved_subdomains import is_reserved_platform_subdomain
from app.services.platform.host_routing import classify_host


def test_normalize_surname_strips_punctuation_and_accents() -> None:
    assert normalize_surname("O'Brien") == "obrien"
    assert normalize_surname("O’Brien") == "obrien"
    assert normalize_surname("Mensah-Boateng") == "mensah-boateng"
    assert normalize_surname("  Kwame  ") == "kwame"
    assert normalize_surname("Ñkrùmâh") == "nkrumah"


def test_student_hostname_uses_ifnotus_zone() -> None:
    assert STUDENT_ZONE == "ifnotus.space"
    assert LEGACY_STUDENT_ZONE == "serverlabsttu.space"
    assert student_label("mensah", 0) == "mensah"
    assert student_label("mensah", 1) == "mensah2"
    assert student_label("mensah", 2) == "mensah3"
    assert student_hostname("mensah", 0) == "mensah.ifnotus.space"
    assert student_hostname("mensah", 1) == "mensah2.ifnotus.space"
    assert student_zone_extension() == ".ifnotus.space"


def test_is_student_hostname_accepts_active_and_legacy() -> None:
    assert is_student_hostname("kwofie.ifnotus.space")
    assert is_active_student_hostname("kwofie.ifnotus.space")
    assert not is_legacy_student_hostname("kwofie.ifnotus.space")

    assert is_student_hostname("kwofie.serverlabsttu.space")
    assert is_legacy_student_hostname("kwofie.serverlabsttu.space")
    assert not is_active_student_hostname("kwofie.serverlabsttu.space")

    assert not is_student_hostname("env-abc.customers.ifnotus.space")
    assert not is_student_hostname("studio.online")
    assert not is_student_hostname("a.b.ifnotus.space")
    assert student_zone_of("mensah2.ifnotus.space") == "ifnotus.space"
    assert student_zone_of("mensah2.serverlabsttu.space") == "serverlabsttu.space"


def test_reserved_labels_include_plan_required_names() -> None:
    for label in (
        "www",
        "api",
        "cpanel",
        "mail",
        "phpmyadmin",
        "oauth",
        "account",
        "panel",
        "status",
        "ns1",
        "admin_1",
        "serverlabsttu",
    ):
        assert label in RESERVED_LABELS
        assert is_reserved_platform_subdomain(label)
    assert is_reserved_platform_subdomain("PHPMyAdmin")
    assert is_reserved_platform_subdomain("staff-login")


def test_require_base_rejects_reserved_and_short(test_settings) -> None:
    from app.core.exceptions import ValidationError
    import pytest

    svc = StudentHostnameService(session=None, settings=test_settings)  # type: ignore[arg-type]
    with pytest.raises(ValidationError) as short:
        svc._require_base("a")
    assert short.value.code == "student_surname_invalid"

    with pytest.raises(ValidationError) as reserved:
        svc._require_base("mail")
    assert reserved.value.code == "student_surname_reserved"

    with pytest.raises(ValidationError):
        svc._require_base("cpanel")

    assert svc._require_base("Mensah") == "mensah"


def test_new_assignments_never_use_serverlabsttu(test_settings) -> None:
    assert getattr(test_settings, "student_zone", "ifnotus.space") == "ifnotus.space"
    assert student_hostname("kwofie", 0).endswith(".ifnotus.space")
    assert not student_hostname("kwofie", 0).endswith(".serverlabsttu.space")


def test_host_routing_kinds() -> None:
    assert classify_host("fpanel.ifnotus.space").kind == "platform"
    assert classify_host("cpanel.ifnotus.space").kind == "platform"
    assert classify_host("mail.ifnotus.space").kind == "platform"
    assert classify_host("manuel.ifnotus.space").kind == "student"
    assert classify_host("cpanel.studio.online").kind == "custom_panel"
    assert classify_host("cpanel.studio.online").apex == "studio.online"
    assert classify_host("mail.studio.online").kind == "custom_mail"
    assert classify_host("studio.online").kind == "custom_site"
    assert classify_host("phpmyadmin.ifnotus.space").kind == "platform"
    assert classify_host("api.ifnotus.space").kind == "platform"
    assert classify_host("not-a-host").kind == "unknown"


def test_claim_rejects_reserved_hostname(test_settings) -> None:
    from app.core.exceptions import ValidationError
    import pytest

    svc = StudentHostnameService(session=None, settings=test_settings)  # type: ignore[arg-type]

    async def _claim() -> None:
        await svc.claim("mail.ifnotus.space")

    with pytest.raises(ValidationError) as reserved:
        import asyncio

        asyncio.run(_claim())
    assert reserved.value.code == "student_surname_reserved"


def test_nginx_custom_vhost_path_cpanel_and_mail(test_settings, tmp_path) -> None:
    from app.services.hosting.nginx_provisioner import DomainNginxProvisioner

    settings = test_settings.model_copy(
        update={
            "nginx_sites_available": str(tmp_path),
            "nginx_sites_enabled": str(tmp_path),
        }
    )
    svc = DomainNginxProvisioner(settings)
    cfg = svc.render_config(
        hostname="studio.online",
        document_root=str(tmp_path),
        proxy_port=None,
        force_https=False,
        redirect_url=None,
    )
    assert "location = /cpanel" in cfg
    assert "location = /fpanel" in cfg
    assert "fpanel.studio.online" in cfg
    assert "mail.studio.online" in cfg
    assert "webmail.studio.online" in cfg
    assert "server_name studio.online www.studio.online" in cfg
