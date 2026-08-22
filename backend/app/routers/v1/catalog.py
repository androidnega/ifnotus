"""Public IFNOTUS catalog — plans and domain TLD prices."""

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DbSession, SettingsDep
from app.models.platform import HostingPlan
from app.schemas.platform import (
    CatalogMetaResponse,
    ComingSoonProductSchema,
    DomainTldPriceSchema,
    HostingPlanListResponse,
    HostingPlanSchema,
    PublicStatusResponse,
)

router = APIRouter()

DOMAIN_PRICES = [
    DomainTldPriceSchema(extension=".online", price_yearly=50),
    DomainTldPriceSchema(extension=".com", price_yearly=250),
    DomainTldPriceSchema(extension=".org", price_yearly=180),
    DomainTldPriceSchema(extension=".net", price_yearly=200),
]


@router.get("/plans", response_model=HostingPlanListResponse)
async def list_plans(session: DbSession) -> HostingPlanListResponse:
    """Public storefront — shared packs only, capabilities from backend matrix."""
    result = await session.execute(
        select(HostingPlan).where(HostingPlan.is_active.is_(True)).order_by(HostingPlan.sort_order)
    )
    plans = list(result.scalars().all())
    from app.services.platform.plan_matrix import (
        PUBLIC_CATALOG_KEYS,
        PUBLIC_DISPLAY_NAMES,
        capabilities_for,
        catalog_card_for,
        coming_soon_products,
        features_for,
        listed_in_public_catalog,
    )

    keyed: dict[str, HostingPlan] = {}
    for p in plans:
        if not listed_in_public_catalog(p):
            continue
        feats = features_for(p)
        key = str(feats.get("matrix_key") or "")
        # Prefer first match per matrix key (avoid duplicates)
        if key and key not in keyed:
            keyed[key] = p

    items = []
    for key in PUBLIC_CATALOG_KEYS:
        p = keyed.get(key)
        if p is None:
            continue
        feats = features_for(p)
        display = feats.get("display_name") or PUBLIC_DISPLAY_NAMES.get(key) or p.name
        schema = HostingPlanSchema.model_validate(p)
        items.append(
            schema.model_copy(
                update={
                    "name": display,
                    "features": feats,
                    "capabilities": capabilities_for(p),
                    "catalog_card": catalog_card_for(p),
                }
            )
        )
    soon = [ComingSoonProductSchema.model_validate(row) for row in coming_soon_products()]
    return HostingPlanListResponse(items=items, coming_soon=soon)


@router.get("/meta", response_model=CatalogMetaResponse)
async def catalog_meta(settings: SettingsDep) -> CatalogMetaResponse:
    from app.services.platform.registrar import DomainRegistrar
    from app.services.platform.site_theme_store import SiteThemeStore

    def field(name: str, default: str = "") -> str:
        return str(getattr(settings, name, default) or default)

    try:
        theme = SiteThemeStore(settings).status()
    except Exception:  # noqa: BLE001
        theme = {"theme": "studio-light", "themes": [], "colors": {}, "plan_colors": []}
    try:
        registrar_on = DomainRegistrar(settings).enabled
    except Exception:  # noqa: BLE001
        registrar_on = False
    return CatalogMetaResponse(
        domain_prices=DOMAIN_PRICES,
        theme=str(theme.get("theme") or "studio-light"),
        themes=list(theme.get("themes") or []),
        colors=dict(theme.get("colors") or {}),
        plan_colors=list(theme.get("plan_colors") or []),
        registrar_enabled=registrar_on,
        nameservers=[field("dns_ns1", "ns1.ifnotus.space"), field("dns_ns2", "ns2.ifnotus.space")],
        student_zone=field("student_zone", "serverlabsttu.space"),
        legacy_student_zone=field("legacy_student_zone", "ifnotus.space"),
        support_hours=field("support_hours", "Monday–Saturday, 08:00–20:00 GMT"),
        support_whatsapp=field("support_whatsapp"),
        support_email=field("support_email", "support@ifnotus.space"),
        company_legal_name=field("company_legal_name", "IFNOTUS"),
        company_city=field("company_city", "Accra, Ghana"),
    )


@router.get("/status", response_model=PublicStatusResponse)
async def public_status(settings: SettingsDep) -> PublicStatusResponse:
    from datetime import UTC, datetime

    return PublicStatusResponse(
        ok=True,
        message="IFNOTUS hosting is operating normally.",
        nameservers=[settings.dns_ns1, settings.dns_ns2],
        support_hours=settings.support_hours,
        updated_at=datetime.now(UTC),
    )
