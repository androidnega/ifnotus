"""Map IFNOTUS HostingPlan ids/slugs → OLSPanel pkg_id.

Billing and plan catalog stay in IFNOTUS. OLSPanel packages are synced/mapped here.
Format of OLSPANEL_PACKAGE_MAP (JSON object):
  {"starter": 1, "student": 2, "<plan-uuid>": 3}
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.core.config import Settings
from app.core.exceptions import AppException, ValidationError


def _parse_map(raw: str | None, *, label: str = "PACKAGE_MAP") -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AppException(f"Invalid {label} JSON: {exc}", code="config_error") from exc
    if not isinstance(data, dict):
        raise AppException(f"{label} must be a JSON object.", code="config_error")
    return data


def resolve_olspanel_pkg_id(
    settings: Settings,
    package_ref: str | int | UUID | None,
    *,
    plan_slug: str | None = None,
) -> int:
    """Resolve OLSPanel numeric pkg_id from IFNOTUS plan id/slug or direct int."""
    if isinstance(package_ref, int):
        return package_ref
    if isinstance(package_ref, UUID):
        package_ref = str(package_ref)

    mapping = _parse_map(settings.olspanel_package_map, label="OLSPANEL_PACKAGE_MAP")
    default = settings.olspanel_default_pkg_id

    candidates: list[str] = []
    if plan_slug:
        candidates.append(str(plan_slug).strip().lower())
    if package_ref is not None:
        candidates.append(str(package_ref).strip())
        candidates.append(str(package_ref).strip().lower())

    for key in candidates:
        if key in mapping:
            try:
                return int(mapping[key])
            except (TypeError, ValueError) as exc:
                raise AppException(
                    f"OLSPanel package map value for {key!r} is not an int.",
                    code="config_error",
                ) from exc

    if default is not None:
        return int(default)

    raise ValidationError(
        "No OLSPanel package mapping for this IFNOTUS plan. "
        "Set OLSPANEL_PACKAGE_MAP or OLSPANEL_DEFAULT_PKG_ID.",
    )


def resolve_ispconfig_template_id(
    settings: Settings,
    package_ref: str | int | UUID | None,
    *,
    plan_slug: str | None = None,
) -> int:
    """Resolve ISPConfig client template_id from IFNOTUS plan id/slug or direct int."""
    if isinstance(package_ref, int):
        return package_ref
    if isinstance(package_ref, UUID):
        package_ref = str(package_ref)

    mapping = _parse_map(settings.ispconfig_template_map, label="ISPCONFIG_TEMPLATE_MAP")
    default = settings.ispconfig_default_template_id

    candidates: list[str] = []
    if plan_slug:
        candidates.append(str(plan_slug).strip().lower())
    if package_ref is not None:
        candidates.append(str(package_ref).strip())
        candidates.append(str(package_ref).strip().lower())

    for key in candidates:
        if key in mapping:
            try:
                return int(mapping[key])
            except (TypeError, ValueError) as exc:
                raise AppException(
                    f"ISPConfig template map value for {key!r} is not an int.",
                    code="config_error",
                ) from exc

    if default is not None:
        return int(default)

    raise ValidationError(
        "No ISPConfig template mapping for this IFNOTUS plan. "
        "Set ISPCONFIG_TEMPLATE_MAP or ISPCONFIG_DEFAULT_TEMPLATE_ID.",
    )
