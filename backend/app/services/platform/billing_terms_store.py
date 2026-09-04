"""Configurable hosting billing terms (Phase G).

Superadmin-managed JSON — discounts are NOT hardcoded business rules.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.exceptions import AppException, ValidationError

ALLOWED_TERM_MONTHS = (1, 3, 6, 12, 24, 36)

# Defaults: all terms enabled, zero discount (admin may configure later).
_DEFAULT_TERMS: dict[str, dict[str, Any]] = {
    "1": {
        "months": 1,
        "enabled": True,
        "discount_pct": 0,
        "fixed_price": None,
        "label": "1 month",
        "recommended": False,
        "min_monthly_price": None,
    },
    "3": {
        "months": 3,
        "enabled": True,
        "discount_pct": 0,
        "fixed_price": None,
        "label": "3 months",
        "recommended": False,
        "min_monthly_price": None,
    },
    "6": {
        "months": 6,
        "enabled": True,
        "discount_pct": 0,
        "fixed_price": None,
        "label": "6 months",
        "recommended": True,
        "min_monthly_price": None,
    },
    "12": {
        "months": 12,
        "enabled": True,
        "discount_pct": 0,
        "fixed_price": None,
        "label": "12 months",
        "recommended": False,
        "min_monthly_price": None,
    },
    "24": {
        "months": 24,
        "enabled": True,
        "discount_pct": 0,
        "fixed_price": None,
        "label": "24 months",
        "recommended": False,
        "min_monthly_price": None,
    },
    "36": {
        "months": 36,
        "enabled": True,
        "discount_pct": 0,
        "fixed_price": None,
        "label": "36 months",
        "recommended": False,
        "min_monthly_price": None,
    },
}


def _money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def add_calendar_months(dt: datetime, months: int) -> datetime:
    """Add whole calendar months (handles month-end safely)."""
    import calendar

    months = int(months)
    if months < 0:
        raise ValueError("months must be >= 0")
    if months == 0:
        return dt
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def term_duration_days(months: int) -> int:
    """Approx day count for renewals that still use timedelta(days=…)."""
    months = max(1, int(months))
    # Average Gregorian month length keeps tick/renew math simple.
    return int(round(months * 30.436875))


class BillingTermsStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        path = getattr(settings, "billing_terms_path", None) or ".ifnotus/settings/billing_terms.json"
        self._path = Path(path).resolve()

    def _read_raw(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_raw(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            **data,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self._path)

    def get_config(self) -> dict[str, Any]:
        raw = self._read_raw()
        terms_in = raw.get("terms") if isinstance(raw.get("terms"), dict) else {}
        terms: dict[str, dict[str, Any]] = {}
        for months in ALLOWED_TERM_MONTHS:
            key = str(months)
            base = deepcopy(_DEFAULT_TERMS[key])
            override = terms_in.get(key) if isinstance(terms_in.get(key), dict) else {}
            merged = {**base, **override, "months": months}
            merged["enabled"] = bool(merged.get("enabled", True))
            try:
                merged["discount_pct"] = max(0.0, min(90.0, float(merged.get("discount_pct") or 0)))
            except (TypeError, ValueError):
                merged["discount_pct"] = 0.0
            fixed = merged.get("fixed_price")
            if fixed is None or fixed == "":
                merged["fixed_price"] = None
            else:
                try:
                    merged["fixed_price"] = float(_money(fixed))
                except Exception:  # noqa: BLE001
                    merged["fixed_price"] = None
            merged["label"] = str(merged.get("label") or f"{months} month{'s' if months != 1 else ''}")
            merged["recommended"] = bool(merged.get("recommended"))
            min_p = merged.get("min_monthly_price")
            if min_p is None or min_p == "":
                merged["min_monthly_price"] = None
            else:
                try:
                    merged["min_monthly_price"] = float(_money(min_p))
                except Exception:  # noqa: BLE001
                    merged["min_monthly_price"] = None
            terms[key] = merged
        return {
            "terms": terms,
            "updated_at": raw.get("updated_at"),
        }

    def public_terms(self, *, monthly_price: Decimal | float | int | None = None) -> list[dict[str, Any]]:
        """Enabled terms with computed price for a monthly plan amount."""
        cfg = self.get_config()
        monthly = _money(monthly_price or 0)
        out: list[dict[str, Any]] = []
        for months in ALLOWED_TERM_MONTHS:
            term = cfg["terms"][str(months)]
            if not term.get("enabled"):
                continue
            min_p = term.get("min_monthly_price")
            if min_p is not None and monthly < _money(min_p):
                continue
            quote = quote_term_price(monthly, months, term)
            out.append(
                {
                    **term,
                    "monthly_price": float(monthly),
                    "subtotal": float(quote["subtotal"]),
                    "discount_amount": float(quote["discount_amount"]),
                    "plan_total": float(quote["plan_total"]),
                    "savings_pct": float(quote["discount_pct"]),
                }
            )
        return out

    def update_config(self, body: dict[str, Any]) -> dict[str, Any]:
        incoming = body.get("terms") if isinstance(body, dict) else None
        if not isinstance(incoming, dict):
            raise ValidationError("terms object is required", code="billing_terms_invalid")
        next_terms: dict[str, Any] = {}
        for months in ALLOWED_TERM_MONTHS:
            key = str(months)
            src = incoming.get(key) if isinstance(incoming.get(key), dict) else {}
            base = deepcopy(_DEFAULT_TERMS[key])
            row = {**base, **src, "months": months}
            row["enabled"] = bool(row.get("enabled", True))
            try:
                row["discount_pct"] = max(0.0, min(90.0, float(row.get("discount_pct") or 0)))
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"Invalid discount for {months}-month term", code="bad_discount") from exc
            fixed = row.get("fixed_price")
            if fixed is None or fixed == "":
                row["fixed_price"] = None
            else:
                row["fixed_price"] = float(_money(fixed))
            row["label"] = str(row.get("label") or base["label"])[:64]
            row["recommended"] = bool(row.get("recommended"))
            min_p = row.get("min_monthly_price")
            if min_p is None or min_p == "":
                row["min_monthly_price"] = None
            else:
                row["min_monthly_price"] = float(_money(min_p))
            next_terms[key] = row
        if not any(t.get("enabled") for t in next_terms.values()):
            raise AppException("At least one billing term must stay enabled.", code="no_terms_enabled")
        self._write_raw({"terms": next_terms})
        return self.get_config()

    def resolve_term(
        self,
        months: int | None,
        *,
        monthly_price: Decimal | float | int,
        require_enabled: bool = True,
    ) -> dict[str, Any]:
        wanted = int(months or 1)
        if wanted not in ALLOWED_TERM_MONTHS:
            raise ValidationError(
                f"Billing term must be one of {', '.join(str(m) for m in ALLOWED_TERM_MONTHS)} months.",
                code="invalid_billing_term",
            )
        cfg = self.get_config()
        term = cfg["terms"][str(wanted)]
        monthly = _money(monthly_price)
        if require_enabled and not term.get("enabled"):
            raise ValidationError(
                f"The {wanted}-month term is not available right now.",
                code="term_disabled",
            )
        min_p = term.get("min_monthly_price")
        if min_p is not None and monthly < _money(min_p):
            raise ValidationError(
                f"The {wanted}-month term requires a higher package.",
                code="term_plan_ineligible",
            )
        quote = quote_term_price(monthly, wanted, term)
        return {
            "months": wanted,
            "label": term.get("label") or f"{wanted} months",
            "discount_pct": float(quote["discount_pct"]),
            "fixed_price": term.get("fixed_price"),
            "recommended": bool(term.get("recommended")),
            **quote,
        }


def quote_term_price(monthly_price: Decimal, months: int, term: dict[str, Any]) -> dict[str, Decimal]:
    monthly = _money(monthly_price)
    months = int(months)
    subtotal = _money(monthly * months)
    discount_pct = Decimal(str(term.get("discount_pct") or 0))
    fixed = term.get("fixed_price")
    if fixed is not None:
        plan_total = _money(fixed)
        discount_amount = _money(max(Decimal("0"), subtotal - plan_total))
        # Effective discount for display.
        discount_pct = (
            _money((discount_amount / subtotal) * 100) if subtotal > 0 else Decimal("0")
        )
    else:
        discount_amount = _money(subtotal * (discount_pct / Decimal("100")))
        plan_total = _money(subtotal - discount_amount)
    return {
        "monthly_price": monthly,
        "subtotal": subtotal,
        "discount_pct": discount_pct,
        "discount_amount": discount_amount,
        "plan_total": plan_total,
    }


def yearly_price_from_monthly(
    settings: Settings,
    monthly_price: Decimal | float | int | str | None,
) -> Decimal:
    """12-month total from live billing terms (never a hardcoded catalog yearly)."""
    return BillingTermsStore(settings).resolve_term(
        12,
        monthly_price=monthly_price or 0,
        require_enabled=False,
    )["plan_total"]


def enrich_plan_yearly(
    schema: Any,
    settings: Settings,
    *,
    monthly_price: Decimal | float | int | str | None = None,
) -> Any:
    """Overwrite HostingPlanSchema.price_yearly with the term-derived amount."""
    monthly = monthly_price
    if monthly is None:
        monthly = getattr(schema, "price_monthly", None)
    yearly = yearly_price_from_monthly(settings, monthly)
    if hasattr(schema, "model_copy"):
        return schema.model_copy(update={"price_yearly": yearly})
    return schema

