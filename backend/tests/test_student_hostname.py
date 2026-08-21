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


def test_normalize_surname_strips_punctuation_and_accents() -> None:
    assert normalize_surname("O'Brien") == "obrien"
    assert normalize_surname("O’Brien") == "obrien"
    assert normalize_surname("Mensah-Boateng") == "mensahboateng"
    assert normalize_surname("  Kwame  ") == "kwame"
    assert normalize_surname("Ñkrùmâh") == "nkrumah"


def test_student_hostname_uses_serverlabsttu_zone() -> None:
    assert STUDENT_ZONE == "serverlabsttu.space"
    assert LEGACY_STUDENT_ZONE == "ifnotus.space"
    assert student_label("mensah", 0) == "mensah"
    assert student_label("mensah", 1) == "mensah1"
    assert student_label("mensah", 2) == "mensah2"
    assert student_hostname("mensah", 0) == "mensah.serverlabsttu.space"
    assert student_hostname("mensah", 1) == "mensah1.serverlabsttu.space"
    assert student_hostname("mensah", 2) == "mensah2.serverlabsttu.space"
    assert student_zone_extension() == ".serverlabsttu.space"


def test_is_student_hostname_accepts_active_and_legacy() -> None:
    assert is_student_hostname("kwofie.serverlabsttu.space")
    assert is_active_student_hostname("kwofie.serverlabsttu.space")
    assert not is_legacy_student_hostname("kwofie.serverlabsttu.space")

    assert is_student_hostname("kwofie.ifnotus.space")
    assert is_legacy_student_hostname("kwofie.ifnotus.space")
    assert not is_active_student_hostname("kwofie.ifnotus.space")

    assert not is_student_hostname("env-abc.customers.ifnotus.space")
    assert not is_student_hostname("studio.online")
    assert not is_student_hostname("a.b.serverlabsttu.space")
    assert student_zone_of("mensah2.serverlabsttu.space") == "serverlabsttu.space"
    assert student_zone_of("mensah2.ifnotus.space") == "ifnotus.space"


def test_reserved_labels_include_plan_required_names() -> None:
    for label in (
        "www",
        "api",
        "account",
        "panel",
        "mail",
        "status",
        "ns1",
        "ns2",
        "ftp",
        "ssh",
        "admin",
        "support",
        "serverlabsttu",
    ):
        assert label in RESERVED_LABELS


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

    assert svc._require_base("Mensah") == "mensah"


def test_allocate_method_exists() -> None:
    assert callable(getattr(StudentHostnameService, "allocate", None))


def test_new_assignments_never_use_ifnotus_space_zone(test_settings) -> None:
    assert getattr(test_settings, "student_zone", "serverlabsttu.space") == "serverlabsttu.space"
    assert not student_hostname("kwofie", 0).endswith(".ifnotus.space")
    assert student_hostname("kwofie", 0).endswith(".serverlabsttu.space")
