"""IFNOTUS product-layer schemas (catalog, customers, orders, environments)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from app.schemas.common import SchemaBase


class HostingPlanSchema(SchemaBase):
    id: UUID
    slug: str
    name: str
    cpu_cores: Decimal
    ram_gb: Decimal
    storage_gb: int
    bandwidth_tb: Decimal
    ai_credits: int
    price_monthly: Decimal
    price_yearly: Decimal | None = None
    currency: str
    features: dict
    sort_order: int
    is_active: bool
    version: int = 1

    @field_validator("features", mode="before")
    @classmethod
    def _features_dict(cls, value):
        return value if isinstance(value, dict) else {}


class HostingPlanListResponse(SchemaBase):
    items: list[HostingPlanSchema]
    brand: str = "IFNOTUS"
    currency: str = "GHS"


class DomainTldPriceSchema(SchemaBase):
    extension: str
    price_yearly: Decimal
    currency: str = "GHS"


class CatalogMetaResponse(SchemaBase):
    brand: str = "IFNOTUS"
    panel_name: str = "IFNOTUS Panel"
    currency: str = "GHS"
    domain_prices: list[DomainTldPriceSchema]
    updated_at: datetime | None = None
    theme: str = "studio-light"
    themes: list[dict] = Field(default_factory=list)
    colors: dict[str, str] = Field(default_factory=dict)
    plan_colors: list[dict[str, str]] = Field(default_factory=list)
    registrar_enabled: bool = False
    nameservers: list[str] = Field(default_factory=lambda: ["ns1.ifnotus.space", "ns2.ifnotus.space"])
    student_zone: str = "serverlabsttu.space"
    legacy_student_zone: str = "ifnotus.space"
    support_hours: str = ""
    support_whatsapp: str = ""
    support_email: str = ""
    company_legal_name: str = "IFNOTUS"
    company_city: str = "Accra, Ghana"


class PublicStatusResponse(SchemaBase):
    ok: bool = True
    brand: str = "IFNOTUS"
    message: str = "IFNOTUS hosting is operating normally."
    nameservers: list[str] = Field(default_factory=list)
    support_hours: str = ""
    updated_at: datetime | None = None


class CustomerRegisterRequest(SchemaBase):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=255)
    phone: str = Field(min_length=9, max_length=32)
    company: str | None = None


class CustomerPhoneOtpRequest(SchemaBase):
    phone: str = Field(min_length=9, max_length=32)


class CustomerPhoneOtpVerifyRequest(SchemaBase):
    phone: str = Field(min_length=9, max_length=32)
    challenge_id: str = Field(min_length=8, max_length=128)
    code: str = Field(min_length=4, max_length=12)


class CustomerPhoneOtpRequestResponse(SchemaBase):
    challenge_id: str
    phone: str
    message: str
    sms_sent: bool = False
    debug_code: str | None = None


class CustomerCompleteProfileRequest(SchemaBase):
    """Legacy one-shot profile completion (still supported). Prefer PATCH /me."""

    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, min_length=2, max_length=120)
    email: EmailStr
    company: str | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class CustomerProfileUpdateRequest(SchemaBase):
    """Incremental profile patch — only send fields unlocking the next action."""

    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, min_length=2, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, min_length=9, max_length=32)
    company: str | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class CustomerPasswordChangeRequest(SchemaBase):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class TotpSetupResponse(SchemaBase):
    secret: str
    otpauth_url: str
    enabled: bool = False


class TotpConfirmRequest(SchemaBase):
    code: str = Field(min_length=6, max_length=8)


class CustomerVerifyEmailRequest(SchemaBase):
    token: str
    code: str = Field(min_length=4, max_length=12)


class CustomerResponse(SchemaBase):
    id: UUID
    email: str
    full_name: str
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    company: str | None = None
    email_verified: bool
    phone_verified: bool = False
    profile_complete: bool = False
    onboarding_stage: str = "phone_verified"
    onboarding_completed_at: datetime | None = None
    can_order: bool = False
    can_student_hostname: bool = False
    missing_for_order: list[str] = Field(default_factory=list)
    missing_for_student: list[str] = Field(default_factory=list)
    two_factor_enabled: bool
    created_at: datetime
    last_login_at: datetime | None = None
    last_login_ip: str | None = None


class CustomerRegisterResponse(SchemaBase):
    customer: CustomerResponse
    verification_token: str
    message: str = "Account created. Verify your email with the code sent (or shown in demo)."


class CreateOrderRequest(SchemaBase):
    plan_id: UUID
    domain_name: str | None = None
    domain_extension: str | None = None
    include_domain: bool = True
    domain_kind: str = "register"
    student_surname: str | None = None

    @field_validator("domain_kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        kind = (value or "register").strip().lower()
        if kind not in {"register", "transfer", "own", "student"}:
            return "register"
        return kind


class MomoInstructions(SchemaBase):
    network: str
    number: str
    account_name: str
    merchant: bool = True


class SubmitMomoRequest(SchemaBase):
    transaction_id: str = Field(min_length=6, max_length=80)


class OrderResponse(SchemaBase):
    id: UUID
    customer_id: UUID
    plan_id: UUID
    domain_name: str | None = None
    domain_extension: str | None = None
    plan_price: Decimal
    domain_price: Decimal
    total_price: Decimal
    currency: str
    payment_status: str
    provisioning_status: str
    paystack_reference: str | None = None
    invoice_number: str | None = None
    payment_method: str | None = None
    momo_transaction_id: str | None = None
    paid_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime
    order_kind: str | None = None


class InvoiceViewResponse(SchemaBase):
    order: OrderResponse
    plan_name: str | None = None
    momo: MomoInstructions
    payment_methods: list[dict] = Field(default_factory=list)
    support_hours: str | None = None
    support_whatsapp: str | None = None
    support_email: str | None = None


class CreateOrderResponse(SchemaBase):
    order: OrderResponse
    authorization_url: str | None = None
    reference: str
    demo: bool = False
    paystack_public_key: str | None = None
    payment_method: str = "momo"
    invoice_number: str | None = None
    momo: MomoInstructions | None = None


class VerifyPaymentRequest(SchemaBase):
    reference: str


class EnvironmentResponse(SchemaBase):
    id: UUID
    subscription_id: UUID
    customer_id: UUID
    status: str
    cpu_limit: Decimal
    ram_limit_gb: Decimal
    storage_limit_gb: int
    ip_address: str | None = Field(default=None, exclude=True)
    domain: str | None = None
    document_root: str | None = Field(default=None, exclude=True)
    health_status: str
    isolation_type: str = "filesystem"
    hosting_domain_id: UUID | None = None
    container_port: int | None = Field(default=None, exclude=True)
    ssl_expiry: datetime | None = None
    db_engine: str | None = None
    db_name: str | None = None
    db_username: str | None = None
    db_host: str | None = None
    db_port: int | None = None
    db_password_set: bool = False
    created_at: datetime
    capabilities: dict = Field(default_factory=dict)
    entitlements: dict = Field(default_factory=dict)
    provisioning_step: str | None = None


class EnvironmentDatabaseResponse(SchemaBase):
    environment_id: UUID
    engine: str | None = None
    name: str | None = None
    username: str | None = None
    host: str | None = None
    port: int | None = None
    password_set: bool = False
    password: str | None = None
    connection_uri: str | None = None


class EnvironmentFtpResponse(SchemaBase):
    environment_id: UUID
    enabled: bool = False
    username: str | None = None
    host: str
    wordpress_host: str = "localhost"
    port: int = 21
    home: str | None = Field(default=None, exclude=True)
    password_set: bool = False
    password: str | None = None
    connection_type: str = "FTP"
    hint: str = "Use ftp.ifnotus.space in FileZilla. If WordPress asks for a hostname, enter localhost."
    sftp_coming_note: str | None = (
        "Prefer SFTP (port 22) from the Transfer tab when available — FTP remains for WordPress prompts."
    )
    message: str | None = None


class EnvironmentSftpKeyResponse(SchemaBase):
    id: str
    name: str | None = None
    fingerprint: str | None = None
    created_at: str | None = None


class EnvironmentSftpKeyCreate(SchemaBase):
    public_key: str = Field(min_length=32, max_length=8192)
    name: str | None = Field(default=None, max_length=64)


class EnvironmentSftpResponse(SchemaBase):
    environment_id: UUID
    sftp_allowed: bool = False
    enabled: bool = False
    username: str | None = None
    host: str = "serverlabsttu.space"
    shared_ip: str | None = None
    port: int = 22
    password_auth_enabled: bool = True
    password_set: bool = False
    password: str | None = None
    connection_type: str = "SFTP"
    protocol: str = "sftp"
    shell_access: bool = False
    keys: list[EnvironmentSftpKeyResponse] = Field(default_factory=list)
    command: str | None = None
    hint: str = ""
    message: str | None = None


class EnvironmentSshResponse(SchemaBase):
    environment_id: UUID
    ssh_allowed: bool = False
    enabled: bool = False
    username: str | None = None
    host: str = "ssh.ifnotus.space"
    shared_ip: str | None = None
    port: int = 22
    password_set: bool = False
    password: str | None = None
    passwords_differ_from_ftp: bool = True
    command: str | None = None
    min_price_ghs: int = 300
    hint: str = ""
    message: str | None = None


class EnvironmentUsageResponse(SchemaBase):
    environment_id: UUID
    domain: str | None = None
    cpu_limit: Decimal
    ram_limit_gb: Decimal
    storage_limit_gb: int
    storage_used_bytes: int
    storage_used_gb: float
    storage_pct: float
    file_count: int
    isolation_type: str = "filesystem"
    soft_warning: bool = False
    hard_exceeded: bool = False
    storage_status: str = "ok"
    message: str | None = None
    note: str = "CPU/RAM are plan limits. Live disk usage is measured under your site folder."


class EnvironmentHealthResponse(SchemaBase):
    environment_id: UUID
    domain: str | None = None
    status: str
    health_status: str
    summary: str
    checks: dict = Field(default_factory=dict)
    checked_at: str | None = None
    queued: bool = False
    message: str | None = None


class StackInfoSchema(SchemaBase):
    id: str
    name: str
    description: str
    icon: str = "php"
    level: str = "yes"
    allowed: bool = True


class StackInstallRequest(SchemaBase):
    stack: str = Field(min_length=2, max_length=32)
    replace: bool = False


class StackClearRequest(SchemaBase):
    drop_database: bool = False


class StackClearResponse(SchemaBase):
    environment_id: UUID
    message: str
    result: dict = Field(default_factory=dict)
    current: dict | None = None


class StackInstallResponse(SchemaBase):
    environment_id: UUID
    stack: str
    queued: bool = False
    job_id: UUID | None = None
    message: str
    result: dict = Field(default_factory=dict)
    current: dict | None = None
    progress: dict | None = None


class StackJobStatusResponse(SchemaBase):
    environment_id: UUID
    job_id: UUID
    status: str
    stack: str | None = None
    message: str | None = None
    error: str | None = None
    progress: dict | None = None
    current: dict | None = None
    result: dict | None = None


class StackStatusResponse(SchemaBase):
    environment_id: UUID
    stacks: list[StackInfoSchema] = Field(default_factory=list)
    current: dict | None = None
    progress: dict | None = None
    active_job_id: UUID | None = None


class EnvLogEntrySchema(SchemaBase):
    source: str
    message: str


class EnvLogsResponse(SchemaBase):
    environment_id: UUID
    sources: list[str] = Field(default_factory=list)
    entries: list[EnvLogEntrySchema] = Field(default_factory=list)
    message: str | None = None


class EnvCronJobSchema(SchemaBase):
    id: str
    schedule: str
    command: str
    enabled: bool = True
    created_at: str | None = None
    last_run_at: str | None = None
    last_status: str | None = None
    last_exit_code: int | None = None
    last_output: str | None = None


class EnvCronCreateRequest(SchemaBase):
    schedule: str = Field(min_length=5, max_length=64)
    command: str = Field(min_length=1, max_length=500)
    enabled: bool = True


class EnvCronUpdateRequest(SchemaBase):
    schedule: str | None = Field(default=None, min_length=5, max_length=64)
    command: str | None = Field(default=None, min_length=1, max_length=500)
    enabled: bool | None = None


class EnvCronListResponse(SchemaBase):
    environment_id: UUID
    jobs: list[EnvCronJobSchema] = Field(default_factory=list)
    note: str = (
        "Jobs run on the server every minute when due. "
        "Commands execute inside your site folder. Use php, node, npm, curl, or ./scripts."
    )


class EnvironmentDnsRecordSchema(SchemaBase):
    id: UUID | None = None
    record_type: str
    host: str
    value: str
    ttl: int = 3600
    priority: int | None = None


class DnsChecklistItem(SchemaBase):
    id: str
    label: str
    done: bool
    detail: str = ""


class EnvironmentDnsResponse(SchemaBase):
    environment_id: UUID
    domain: str | None = None
    addon_domain: str | None = None
    custom_domain: str | None = None
    nameservers: list[str] = Field(default_factory=list)
    custom_domains: list[str] = Field(default_factory=list)
    available_domains: list[str] = Field(default_factory=list)
    custom_domains_used: int = 0
    custom_domains_limit: int = 1
    can_assign: bool = False
    recommended_ip: str = Field(default="", exclude=True)
    records: list[EnvironmentDnsRecordSchema] = Field(default_factory=list)
    namecheap_pushed: bool = False
    included_hostname: bool = False
    ns_live: bool | None = None
    resolves: bool | None = None
    ssl_status: str | None = None
    ssl_ready: bool = False
    checklist: list[DnsChecklistItem] = Field(default_factory=list)
    status_summary: str = ""
    panel_hostname: str | None = None
    panel_url: str | None = None
    message: str = (
        "Set this domain’s nameservers to ns1.ifnotus.space and ns2.ifnotus.space. "
        "Do not use a server IP address."
    )


class AttachCustomDomainRequest(SchemaBase):
    domain_name: str = Field(min_length=4, max_length=255)


class UnassignCustomDomainRequest(SchemaBase):
    domain_name: str = Field(min_length=4, max_length=255)


class EnvironmentRedirectCreateRequest(SchemaBase):
    source_path: str = Field(min_length=1, max_length=512)
    target_url: str = Field(min_length=1, max_length=1024)
    status_code: int = Field(default=301, ge=301, le=308)


class EnvironmentDnsRecordCreateRequest(SchemaBase):
    record_type: str = Field(pattern=r"^(A|AAAA|CNAME|MX|TXT)$")
    host: str = Field(default="@", max_length=255)
    value: str = Field(min_length=1, max_length=1024)
    ttl: int = Field(default=3600, ge=60, le=86400)
    priority: int | None = None


class EnvironmentGitCloneRequest(SchemaBase):
    repo_url: str = Field(min_length=8, max_length=512)
    branch: str | None = Field(default=None, max_length=128)


class EnvironmentSslResponse(SchemaBase):
    environment_id: UUID
    domain: str | None = None
    success: bool
    queued: bool = False
    job_id: UUID | None = None
    message: str
    ssl_expiry: datetime | None = None
    ssl_status: str | None = None
    expiry_source: str | None = None  # "certificate" | "estimate" | None


class EnvironmentBackupResponse(SchemaBase):
    id: UUID
    environment_id: UUID
    filename: str
    file_size: int | None = None
    checksum: str | None = None
    backup_type: str = "full"
    status: str
    verified_at: datetime | None = None
    created_at: datetime | None = None


class EnvironmentBackupRestoreResponse(SchemaBase):
    job_id: UUID
    backup_id: UUID
    environment_id: UUID
    status: str
    message: str


class CreditTopUpRequest(SchemaBase):
    credits: int = Field(ge=5, le=500)
    # priced later; default pack sizes


class CreditTopUpResponse(SchemaBase):
    reference: str
    authorization_url: str | None = None
    demo: bool = False
    credits: int
    amount: Decimal
    paystack_public_key: str | None = None
    invoice_number: str | None = None
    order_id: UUID | None = None


class CustomerFileWriteRequest(SchemaBase):
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=2_000_000)


class CustomerFileMkdirRequest(SchemaBase):
    path: str = Field(min_length=1, max_length=1024)


class SubscriptionResponse(SchemaBase):
    id: UUID
    customer_id: UUID
    plan_id: UUID
    status: str
    cpu_allocated: Decimal
    ram_allocated: Decimal
    storage_allocated: int
    bandwidth_used_gb: Decimal
    started_at: datetime | None = None
    expires_at: datetime | None = None
    auto_renew: bool
    grace_until: datetime | None = None
    last_reminder_days: int | None = None


class RenewPaymentResponse(SchemaBase):
    reference: str
    authorization_url: str | None = None
    demo: bool = False
    amount: Decimal
    currency: str = "GHS"
    subscription_id: UUID | None = None
    paystack_public_key: str | None = None
    invoice_number: str | None = None
    order_id: UUID | None = None
    applied: bool = False
    subscription: SubscriptionResponse | None = None
    message: str | None = None


class ChangePlanRequest(SchemaBase):
    plan_id: UUID


class AutoRenewRequest(SchemaBase):
    enabled: bool = True


class AiCreditAccountResponse(SchemaBase):
    customer_id: UUID
    credits_remaining: int
    total_allocated: int
    lifetime_used: int
    tokens_remaining: int | None = None
    tokens_per_credit: int | None = None


class AiOperationRequest(SchemaBase):
    operation_type: str = Field(pattern="^(build|deploy|fix|audit)$")
    permission_level: int = Field(ge=1, le=4)
    request: str = Field(min_length=3, max_length=8000)
    environment_id: UUID | None = None
    risk_classification: str = "low"


class AiOperationResponse(SchemaBase):
    id: UUID
    customer_id: UUID
    environment_id: UUID | None = None
    operation_type: str
    permission_level: int
    credits_used: int
    status: str
    request: str
    result: str | None = None
    risk_classification: str
    required_confirmation: bool
    completed_at: datetime | None = None
    created_at: datetime


class AiOperationCompleteRequest(SchemaBase):
    success: bool = True
    result: str = Field(min_length=1, max_length=20000)


class NotificationResponse(SchemaBase):
    id: UUID
    title: str
    body: str
    kind: str
    channel: str
    is_read: bool
    created_at: datetime


class CustomerDashboardResponse(SchemaBase):
    brand: str = "IFNOTUS"
    customer: CustomerResponse
    credits: AiCreditAccountResponse
    environments: list[EnvironmentResponse]
    subscriptions: list[SubscriptionResponse]
    unread_notifications: int
    usage: dict
    orders: list[OrderResponse] = Field(default_factory=list)
    momo: MomoInstructions | None = None
    plans: list[HostingPlanSchema] = Field(default_factory=list)


class CapacityNodeResponse(SchemaBase):
    node_id: str
    hostname: str
    cpu_total: int
    ram_total_gb: int
    storage_total_gb: int
    cpu_reserved_pct: int
    cpu_used: float
    ram_used: float
    storage_used: int
    cpu_free: float
    ram_free: float
    storage_free: int
    status: str


class StudentHostnameRequest(SchemaBase):
    surname: str = Field(min_length=1, max_length=80)


class StudentHostnameResponse(SchemaBase):
    surname: str
    hostname: str
    available: bool = True
    message: str
    zone: str | None = None


class DomainAvailabilityRequest(SchemaBase):
    name: str = Field(min_length=2, max_length=63)
    extension: str = Field(pattern=r"^\.(online|com|org|net)$")


class DomainAvailabilityResponse(SchemaBase):
    domain: str
    available: bool
    price_yearly: Decimal
    currency: str = "GHS"
    message: str
    provider: str = "local"


class ApplicationInstanceCreateRequest(SchemaBase):
    name: str = Field(min_length=1, max_length=120)
    stack: str = Field(min_length=1, max_length=64)
    git_url: str | None = Field(default=None, max_length=512)


class ApplicationInstanceResponse(SchemaBase):
    id: str
    environment_id: UUID
    name: str
    stack: str
    status: str = "pending"
    port: int | None = None
    message: str | None = None


class EnvironmentDatabaseV2Response(SchemaBase):
    id: str
    environment_id: UUID
    engine: str | None = None
    name: str | None = None
    username: str | None = None
    host: str | None = None
    port: int | None = None
    password_set: bool = False
    legacy: bool = False
    message: str | None = None
