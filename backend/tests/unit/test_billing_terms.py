"""Phase G — billing term pricing and calendar duration."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.exceptions import ValidationError
from app.services.platform.billing_terms_store import (
    ALLOWED_TERM_MONTHS,
    BillingTermsStore,
    add_calendar_months,
    quote_term_price,
)


@pytest.fixture()
def store(tmp_path: Path) -> BillingTermsStore:
    settings = SimpleNamespace(billing_terms_path=str(tmp_path / "billing_terms.json"))
    return BillingTermsStore(settings)  # type: ignore[arg-type]


def test_allowed_terms() -> None:
    assert ALLOWED_TERM_MONTHS == (1, 3, 6, 12, 24, 36)


def test_add_calendar_months_handles_month_end() -> None:
    start = datetime(2026, 1, 31, tzinfo=UTC)
    assert add_calendar_months(start, 1).date().isoformat() == "2026-02-28"
    assert add_calendar_months(start, 6).date().isoformat() == "2026-07-31"


def test_quote_with_discount() -> None:
    term = {"discount_pct": 10, "fixed_price": None}
    q = quote_term_price(Decimal("100"), 12, term)
    assert q["subtotal"] == Decimal("1200.00")
    assert q["discount_amount"] == Decimal("120.00")
    assert q["plan_total"] == Decimal("1080.00")


def test_quote_fixed_override_beats_discount() -> None:
    term = {"discount_pct": 50, "fixed_price": 900}
    q = quote_term_price(Decimal("100"), 12, term)
    assert q["plan_total"] == Decimal("900.00")
    assert q["discount_amount"] == Decimal("300.00")


def test_defaults_are_zero_discount(store: BillingTermsStore) -> None:
    terms = store.public_terms(monthly_price=50)
    assert [t["months"] for t in terms] == list(ALLOWED_TERM_MONTHS)
    assert all(float(t["discount_pct"]) == 0 for t in terms)
    assert float(terms[0]["plan_total"]) == 50.0
    assert float(next(t for t in terms if t["months"] == 6)["plan_total"]) == 300.0


def test_resolve_rejects_disabled(store: BillingTermsStore) -> None:
    store.update_config(
        {
            "terms": {
                "1": {"enabled": True, "discount_pct": 0},
                "3": {"enabled": False, "discount_pct": 0},
                "6": {"enabled": True, "discount_pct": 5},
                "12": {"enabled": True},
                "24": {"enabled": True},
                "36": {"enabled": True},
            }
        }
    )
    with pytest.raises(ValidationError):
        store.resolve_term(3, monthly_price=40)
    quote = store.resolve_term(6, monthly_price=40)
    assert quote["months"] == 6
    assert float(quote["discount_pct"]) == 5
    assert float(quote["plan_total"]) == 228.0  # 240 - 5%


def test_six_month_activation_math() -> None:
    now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    ends = add_calendar_months(now, 6)
    assert ends.date().isoformat() == "2026-09-15"
    assert (ends - now).days > 150  # not a 30-day subscription


def test_yearly_price_from_monthly_is_dynamic(store: BillingTermsStore) -> None:
    from app.services.platform.billing_terms_store import yearly_price_from_monthly

    assert yearly_price_from_monthly(store._settings, Decimal("150")) == Decimal("1800.00")
    store.update_config(
        {
            "terms": {
                "1": {"enabled": True},
                "3": {"enabled": True},
                "6": {"enabled": True},
                "12": {"enabled": True, "discount_pct": 10},
                "24": {"enabled": True},
                "36": {"enabled": True},
            }
        }
    )
    assert yearly_price_from_monthly(store._settings, Decimal("150")) == Decimal("1620.00")
