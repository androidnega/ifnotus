"""Staff-facing schemas for product console (customers / plans / orders)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from app.schemas.common import SchemaBase
from app.schemas.platform import CustomerResponse, HostingPlanSchema


class StaffCustomerListItem(SchemaBase):
    id: UUID
    email: str
    full_name: str
    phone: str | None = None
    company: str | None = None
    email_verified: bool
    created_at: datetime
    environment_count: int = 0
    subscription_count: int = 0
    credits_remaining: int = 0
    hosting_status: str = "none"
    """none | live | suspended | setting_up | awaiting_payment"""
    primary_domain: str | None = None
    awaiting_payment_count: int = 0


class StaffDeleteCustomerRequest(SchemaBase):
    confirm_email: str = Field(..., min_length=3, max_length=320)


class StaffCustomerUpdateRequest(SchemaBase):
    """Staff edit of tenant contact details (login phone / email)."""

    email: str | None = Field(default=None, min_length=3, max_length=320)
    phone: str | None = Field(default=None, min_length=9, max_length=32)
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, min_length=2, max_length=120)
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    phone_verified: bool | None = None
    email_verified: bool | None = None


class StaffCustomerCreateRequest(SchemaBase):
    """Staff direct onboarding of a new customer."""

    email: str = Field(min_length=3, max_length=320)
    full_name: str = Field(min_length=2, max_length=255)
    password: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    company: str | None = Field(default=None, max_length=255)
    plan_id: str | None = Field(default=None)
    domain: str | None = Field(default=None)


class StaffSubscriptionItem(SchemaBase):
    id: UUID
    plan_id: UUID
    plan_name: str | None = None
    status: str
    cpu_allocated: Decimal
    ram_allocated: Decimal
    storage_allocated: int
    expires_at: datetime | None = None
    auto_renew: bool
    grace_until: datetime | None = None


class StaffEnvironmentItem(SchemaBase):
    id: UUID
    subscription_id: UUID
    domain: str | None = None
    hosting_name: str | None = None
    status: str
    health_status: str
    isolation_type: str
    cpu_limit: Decimal
    ram_limit_gb: Decimal
    storage_limit_gb: int
    document_root: str | None = None
    db_engine: str | None = None
    db_name: str | None = None
    created_at: datetime | None = None
    container_id: str | None = None
    ftp_username: str | None = None
    stack: dict | None = None
    stack_progress: dict | None = None


class StaffAuditItem(SchemaBase):
    id: UUID
    occurred_at: datetime
    action: str
    target_type: str | None = None
    target_id: str | None = None
    result: str
    metadata: dict = Field(default_factory=dict)


class StaffOrderItem(SchemaBase):
    id: UUID
    customer_id: UUID
    customer_email: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    plan_id: UUID
    plan_name: str | None = None
    domain_name: str | None = None
    domain_extension: str | None = None
    plan_price: Decimal | None = None
    domain_price: Decimal | None = None
    total_price: Decimal
    currency: str
    payment_status: str
    provisioning_status: str
    order_kind: str | None = None
    paystack_reference: str | None = None
    invoice_number: str | None = None
    payment_method: str | None = None
    momo_transaction_id: str | None = None
    payment_amount_received: Decimal | None = None
    payment_notes: str | None = None
    payment_confirmed_at: datetime | None = None
    paid_at: datetime | None = None
    created_at: datetime


class StaffAccountingDayPoint(SchemaBase):
    date: str
    collected: float = 0
    complimentary: float = 0
    count: int = 0


class StaffAccountingLedgerItem(SchemaBase):
    id: UUID
    invoice_number: str | None = None
    customer_id: UUID
    customer_name: str | None = None
    customer_email: str | None = None
    plan_name: str | None = None
    order_kind: str = "hosting"
    currency: str = "GHS"
    invoiced: float
    collected: float | None = None
    complimentary: float | None = None
    entry_type: str = "unknown"
    payment_status: str
    payment_method: str | None = None
    momo_transaction_id: str | None = None
    payment_notes: str | None = None
    paid_at: datetime | None = None
    payment_confirmed_at: datetime | None = None
    created_at: datetime


class StaffAccountingSummaryResponse(SchemaBase):
    period: dict
    currency: str = "GHS"
    totals: dict
    by_kind: dict[str, float] = Field(default_factory=dict)
    by_channel: dict[str, float] = Field(default_factory=dict)
    by_day: list[StaffAccountingDayPoint] = Field(default_factory=list)
    recent_paid: list[StaffAccountingLedgerItem] = Field(default_factory=list)
    pipeline: dict = Field(default_factory=dict)


class StaffOpsInboxItem(SchemaBase):
    id: str
    kind: str
    title: str
    message: str
    severity: str = "warning"
    timestamp: datetime
    href: str = "/platform/orders"
    order_id: UUID | None = None
    invoice_number: str | None = None


class StaffOpsInboxResponse(SchemaBase):
    awaiting_payment_confirm: int = 0
    recently_paid: int = 0
    open_support_tickets: int = 0
    items: list[StaffOpsInboxItem] = Field(default_factory=list)


class StaffConfirmPaymentRequest(SchemaBase):
    notes: str | None = None
    amount_received: Decimal | None = None
    domain_name: str | None = None
    payment_method: str | None = None



class StaffProvisionHostingRequest(SchemaBase):
    plan_id: UUID
    domain_name: str | None = None
    domain_extension: str | None = None


class StaffUpdateSubdomainRequest(SchemaBase):
    domain: str = Field(min_length=3, max_length=255)


class StaffUserCreateRequest(SchemaBase):
    email: str
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=255)
    role: str = "operator"


class StaffUserUpdateRequest(SchemaBase):
    is_active: bool | None = None
    role: str | None = None
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class StaffUserItem(SchemaBase):
    id: UUID
    email: str
    username: str
    full_name: str | None = None
    roles: list[str] = Field(default_factory=list)
    is_active: bool = True
    is_superuser: bool = False
    created_at: datetime | None = None
    last_login_at: datetime | None = None
    last_login_ip: str | None = None


class StaffCustomerDetailResponse(SchemaBase):
    customer: CustomerResponse
    credits_remaining: int = 0
    subscriptions: list[StaffSubscriptionItem] = Field(default_factory=list)
    environments: list[StaffEnvironmentItem] = Field(default_factory=list)
    orders: list[StaffOrderItem] = Field(default_factory=list)
    audit: list[StaffAuditItem] = Field(default_factory=list)


class StaffGrantCreditsRequest(SchemaBase):
    credits: int = Field(ge=1, le=100_000)
    note: str | None = Field(default=None, max_length=400)


class StaffGrantCreditsResponse(SchemaBase):
    customer_id: UUID
    credits_granted: int
    credits_remaining: int
    total_allocated: int
    tokens_remaining: int
    message: str


class HostingPlanUpsertRequest(SchemaBase):
    slug: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=2, max_length=128)
    cpu_cores: Decimal | None = Field(default=None, ge=Decimal("0.1"), le=64)
    ram_gb: Decimal | None = Field(default=None, ge=Decimal("0.0625"), le=512)  # 64 MB minimum
    storage_gb: int | None = Field(default=None, ge=1, le=10000)
    bandwidth_tb: Decimal | None = Field(default=None, ge=0)
    ai_credits: int | None = Field(default=None, ge=0)
    price_monthly: Decimal = Field(ge=0)
    price_yearly: Decimal | None = None
    currency: str = Field(default="GHS", max_length=8)
    features: dict = Field(default_factory=dict)
    sort_order: int = 0
    is_active: bool = True
    size_from_price: bool = True


class HostingPlanPatchRequest(SchemaBase):
    slug: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, min_length=2, max_length=128)
    cpu_cores: Decimal | None = Field(default=None, ge=Decimal("0.1"), le=64)
    ram_gb: Decimal | None = Field(default=None, ge=Decimal("0.0625"), le=512)
    storage_gb: int | None = Field(default=None, ge=1, le=10000)
    bandwidth_tb: Decimal | None = Field(default=None, ge=0)
    ai_credits: int | None = Field(default=None, ge=0)
    price_monthly: Decimal | None = Field(default=None, ge=0)
    price_yearly: Decimal | None = None
    currency: str | None = Field(default=None, max_length=8)
    features: dict | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    size_from_price: bool | None = None


class SiteThemeOption(SchemaBase):
    id: str
    name: str
    description: str
    home_scroll: bool = False
    colors: dict[str, str] = Field(default_factory=dict)


class SiteThemeStatusResponse(SchemaBase):
    theme: str
    themes: list[SiteThemeOption]
    colors: dict[str, str] = Field(default_factory=dict)
    plan_colors: list[dict[str, str]] = Field(default_factory=list)
    home_layout: str = "split-right"
    home_layouts: list[dict[str, str]] = Field(default_factory=list)
    maintenance_mode: bool = False
    maintenance_message: str = ""
    updated_at: str | None = None


class SiteThemeUpdateRequest(SchemaBase):
    theme: str = Field(min_length=2, max_length=64)
    colors: dict[str, str] | None = None
    plan_colors: dict[str, str] | None = None
    home_layout: str | None = None
    maintenance_mode: bool | None = None
    maintenance_message: str | None = None


__all__ = [
    "HostingPlanPatchRequest",
    "HostingPlanSchema",
    "HostingPlanUpsertRequest",
    "SiteThemeOption",
    "SiteThemeStatusResponse",
    "SiteThemeUpdateRequest",
    "StaffAccountingDayPoint",
    "StaffAccountingLedgerItem",
    "StaffAccountingSummaryResponse",
    "StaffAuditItem",
    "StaffCustomerDetailResponse",
    "StaffCustomerListItem",
    "StaffDeleteCustomerRequest",
    "StaffEnvironmentItem",
    "StaffOrderItem",
    "StaffOpsInboxItem",
    "StaffOpsInboxResponse",
    "StaffSubscriptionItem",
]
