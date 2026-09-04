"""Public IFNOTUS catalog — plans and domain TLD prices."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession, SettingsDep
from app.models.platform import HostingPlan
from app.schemas.platform import (
    CatalogMetaResponse,
    ComingSoonProductSchema,
    DomainTldPriceSchema,
    HostingPlanListResponse,
    HostingPlanSchema,
    PublicStatusResponse,
    BillingTermsPublicResponse,
    BillingTermPublicSchema,
)

router = APIRouter()


def get_catalog_domain_prices(settings: SettingsDep) -> list[DomainTldPriceSchema]:
    from app.services.platform.integrations_store import IntegrationsSettingsStore

    prices = IntegrationsSettingsStore(settings).get_domain_prices()
    return [
        DomainTldPriceSchema(extension=ext, price_yearly=val)
        for ext, val in prices.items()
    ]



def _enrich_public_plan(plan: HostingPlan, settings: SettingsDep | None = None) -> HostingPlanSchema:
    from app.services.platform.billing_terms_store import enrich_plan_yearly
    from app.services.platform.plan_matrix import (
        PUBLIC_DISPLAY_NAMES,
        capabilities_for,
        catalog_card_for,
        features_for,
    )

    feats = features_for(plan)
    key = str(feats.get("matrix_key") or "")
    display = feats.get("display_name") or PUBLIC_DISPLAY_NAMES.get(key) or plan.name
    schema = HostingPlanSchema.model_validate(plan)
    schema = schema.model_copy(
        update={
            "name": display,
            "features": feats,
            "capabilities": capabilities_for(plan),
            "catalog_card": catalog_card_for(plan),
        }
    )
    if settings is not None:
        schema = enrich_plan_yearly(schema, settings, monthly_price=plan.price_monthly)
    return schema


async def _public_catalog_items(session: AsyncSession, settings: SettingsDep) -> list[HostingPlanSchema]:
    """Shared packs only, ordered for the public storefront."""
    from app.services.platform.plan_matrix import PUBLIC_CATALOG_KEYS, features_for, listed_in_public_catalog

    result = await session.execute(
        select(HostingPlan).where(HostingPlan.is_active.is_(True)).order_by(HostingPlan.sort_order)
    )
    plans = list(result.scalars().all())

    keyed: dict[str, HostingPlan] = {}
    for plan in plans:
        if not listed_in_public_catalog(plan):
            continue
        feats = features_for(plan)
        key = str(feats.get("matrix_key") or "")
        if key and key not in keyed:
            keyed[key] = plan

    items: list[HostingPlanSchema] = []
    for key in PUBLIC_CATALOG_KEYS:
        plan = keyed.get(key)
        if plan is None:
            continue
        items.append(_enrich_public_plan(plan, settings))
    return items


def _plan_matches_slug(plan: HostingPlanSchema, slug: str) -> bool:
    needle = slug.strip().lower()
    if not needle:
        return False
    if plan.slug.lower() == needle:
        return True
    feats = plan.features or {}
    return str(feats.get("matrix_key") or "").lower() == needle


@router.get("/plans", response_model=HostingPlanListResponse)
async def list_plans(session: DbSession, settings: SettingsDep) -> HostingPlanListResponse:
    """Public storefront — shared packs only, capabilities from backend matrix."""
    from app.services.platform.plan_matrix import coming_soon_products

    items = await _public_catalog_items(session, settings)
    soon = [ComingSoonProductSchema.model_validate(row) for row in coming_soon_products()]
    return HostingPlanListResponse(items=items, coming_soon=soon)


@router.get("/plans/{slug}", response_model=HostingPlanSchema)
async def get_plan(slug: str, session: DbSession, settings: SettingsDep) -> HostingPlanSchema:
    """Single public plan by slug or matrix key."""
    for plan in await _public_catalog_items(session, settings):
        if _plan_matches_slug(plan, slug):
            return plan
    raise HTTPException(status_code=404, detail="Plan not found")


@router.get("/meta", response_model=CatalogMetaResponse)
async def catalog_meta(settings: SettingsDep) -> CatalogMetaResponse:
    from app.services.platform.registrar import DomainRegistrar
    from app.services.platform.site_theme_store import SiteThemeStore

    def field(name: str, default: str = "") -> str:
        return str(getattr(settings, name, default) or default)

    try:
        theme = SiteThemeStore(settings).status()
    except Exception:  # noqa: BLE001
        theme = {
            "theme": "studio-light",
            "themes": [],
            "colors": {},
            "plan_colors": [],
            "home_layout": "split-right",
            "home_layouts": [],
            "maintenance_mode": False,
            "maintenance_message": "",
        }
    try:
        registrar_on = DomainRegistrar(settings).enabled
    except Exception:  # noqa: BLE001
        registrar_on = False
    return CatalogMetaResponse(
        domain_prices=get_catalog_domain_prices(settings),
        theme=str(theme.get("theme") or "studio-light"),
        themes=list(theme.get("themes") or []),
        colors=dict(theme.get("colors") or {}),
        plan_colors=list(theme.get("plan_colors") or []),
        home_layout=str(theme.get("home_layout") or "split-right"),
        home_layouts=list(theme.get("home_layouts") or []),
        maintenance_mode=bool(theme.get("maintenance_mode")),
        maintenance_message=str(theme.get("maintenance_message") or ""),
        registrar_enabled=registrar_on,
        nameservers=[field("dns_ns1", "ns1.ifnotus.space"), field("dns_ns2", "ns2.ifnotus.space")],
        student_zone=field("student_zone", "ifnotus.space"),
        legacy_student_zone=field("legacy_student_zone", "serverlabsttu.space"),
        support_hours=field("support_hours", "Monday–Saturday, 08:00–20:00 GMT"),
        support_whatsapp=field("support_whatsapp"),
        support_email=field("support_email", "support@ifnotus.space"),
        company_legal_name=field("company_legal_name", "IFNOTUS"),
        company_city=field("company_city", "Accra, Ghana"),
    )


@router.get("/status", response_model=PublicStatusResponse)
async def public_status(settings: SettingsDep) -> PublicStatusResponse:
    from datetime import UTC, datetime

    from app.services.platform.site_theme_store import SiteThemeStore

    maintenance = False
    message = "IFNOTUS hosting is operating normally."
    try:
        theme = SiteThemeStore(settings).status()
        maintenance = bool(theme.get("maintenance_mode"))
        if maintenance:
            message = str(
                theme.get("maintenance_message")
                or "IFNOTUS is under scheduled maintenance. Please check back shortly."
            )
    except Exception:  # noqa: BLE001
        pass
    return PublicStatusResponse(
        ok=not maintenance,
        message=message,
        maintenance_mode=maintenance,
        nameservers=[settings.dns_ns1, settings.dns_ns2],
        support_hours=settings.support_hours,
        updated_at=datetime.now(UTC),
    )


@router.get("/billing-terms", response_model=BillingTermsPublicResponse)
async def public_billing_terms(
    settings: SettingsDep,
    monthly_price: float | None = Query(default=None, ge=0),
) -> BillingTermsPublicResponse:
    """Enabled checkout terms (+ optional priced quote for a monthly plan)."""
    from app.services.platform.billing_terms_store import ALLOWED_TERM_MONTHS, BillingTermsStore

    store = BillingTermsStore(settings)
    terms = store.public_terms(monthly_price=monthly_price if monthly_price is not None else 0)
    return BillingTermsPublicResponse(
        terms=[BillingTermPublicSchema.model_validate(t) for t in terms],
        allowed_months=list(ALLOWED_TERM_MONTHS),
    )
