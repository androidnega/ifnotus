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
    capabilities: dict = Field(default_factory=dict)
    catalog_card: dict = Field(default_factory=dict)
    sort_order: int
    is_active: bool
    version: int = 1

    @field_validator("features", mode="before")
    @classmethod
    def _features_dict(cls, value):
        return value if isinstance(value, dict) else {}

    @field_validator("capabilities", "catalog_card", mode="before")
    @classmethod
    def _dict_fields(cls, value):
        return value if isinstance(value, dict) else {}


class ComingSoonProductSchema(SchemaBase):
    """PHASE 35 — Cloud VPS/VDS teasers; never checkout-ready on shared node."""

    matrix_key: str
    slug: str
    name: str
    kind: str = "vps"
    status: str = "coming_soon"
    blurb: str = ""
    sellable: bool = False
    requires_external_vm: bool = True


class HostingPlanListResponse(SchemaBase):
    items: list[HostingPlanSchema]
    coming_soon: list[ComingSoonProductSchema] = Field(default_factory=list)
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
    home_layout: str = "split-right"
    home_layouts: list[dict] = Field(default_factory=list)
    maintenance_mode: bool = False
    maintenance_message: str = ""
    registrar_enabled: bool = False
    nameservers: list[str] = Field(default_factory=lambda: ["ns1.ifnotus.space", "ns2.ifnotus.space"])
    student_zone: str = "ifnotus.space"
    legacy_student_zone: str = "serverlabsttu.space"
    support_hours: str = ""
    support_whatsapp: str = ""
    support_email: str = ""
    company_legal_name: str = "IFNOTUS"
    company_city: str = "Accra, Ghana"


class PublicStatusResponse(SchemaBase):
    ok: bool = True
    brand: str = "IFNOTUS"
    message: str = "IFNOTUS hosting is operating normally."
    maintenance_mode: bool = False
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
    has_password: bool = True
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
    billing_term_months: int = 1
    coupon_code: str | None = None

    @field_validator("domain_kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        kind = (value or "register").strip().lower()
        if kind not in {"register", "transfer", "own", "student"}:
            return "register"
        return kind

    @field_validator("billing_term_months")
    @classmethod
    def _term(cls, value: int) -> int:
        try:
            months = int(value or 1)
        except (TypeError, ValueError):
            months = 1
        if months not in {1, 3, 6, 12, 24, 36}:
            raise ValueError("billing_term_months must be 1, 3, 6, 12, 24, or 36")
        return months


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
    plan_id: UUID | None = None
    domain_name: str | None = None
    domain_extension: str | None = None
    plan_price: Decimal | None = None
    domain_price: Decimal | None = None
    total_price: Decimal = Decimal("0.00")
    currency: str = "GHS"
    payment_status: str = "pending"
    provisioning_status: str = "pending"
    paystack_reference: str | None = None
    invoice_number: str | None = None
    payment_method: str | None = None
    momo_transaction_id: str | None = None
    payment_amount_received: Decimal | None = None
    payment_notes: str | None = None
    payment_confirmed_at: datetime | None = None
    payment_confirmed_by: UUID | None = None
    paid_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime
    order_kind: str | None = None
    billing_term_months: int = 1
    meta_json: dict = Field(default_factory=dict)


class InvoiceViewResponse(SchemaBase):
    order: OrderResponse
    plan_name: str | None = None
    momo: MomoInstructions
    payment_methods: list[dict] = Field(default_factory=list)
    support_hours: str | None = None
    support_whatsapp: str | None = None
    support_email: str | None = None
    # Bill-to (filled for staff receipt + customer invoice when available)
    customer_name: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    # Document kind for UI: pending/submitted → invoice; paid → receipt
    document_kind: str = "invoice"


class CreateDomainOrderRequest(SchemaBase):
    domain_name: str
    domain_extension: str
    environment_id: UUID | None = None


class CustomerDomainItemResponse(SchemaBase):
    id: UUID
    domain_name: str
    status: str
    is_active: bool
    registrar: str | None = None
    registration_date: datetime | None = None
    expiry_date: datetime | None = None
    auto_renew: bool = True
    environment_id: UUID | None = None
    environment_domain: str | None = None
    propagation_notice: str = (
        "New domain registrations and DNS updates take 24 to 48 hours to fully propagate worldwide across all networks."
    )


class CustomerDomainListResponse(SchemaBase):
    items: list[CustomerDomainItemResponse]
    propagation_notice: str = (
        "New domain registrations and DNS updates take 24 to 48 hours to fully propagate worldwide across all networks."
    )


class EnvironmentDomainEntry(SchemaBase):
    id: str
    domain_name: str
    domain_type: str = "primary"
    document_root: str = "/public_html"
    full_document_root: str = ""
    redirects_to: str | None = None
    force_https: bool = False
    is_primary: bool = False
    ssl_active: bool = False
    can_delete: bool = True
    created_at: datetime | None = None


class EnvironmentDomainListResponse(SchemaBase):
    primary_domain: str
    unix_username: str
    home_dir: str
    default_doc_root: str = "/public_html"
    package_supported: bool = True
    custom_domains_limit: int | None = None
    custom_domains_count: int = 0
    items: list[EnvironmentDomainEntry]


class CreateEnvironmentDomainRequest(SchemaBase):
    domain_name: str = Field(min_length=3, max_length=255)
    domain_type: str = Field(default="registered", max_length=32)
    share_document_root: bool = False
    document_root: str | None = Field(default=None, max_length=512)
    force_https: bool = True


class UpdateEnvironmentDomainRequest(SchemaBase):
    document_root: str | None = Field(default=None, max_length=512)
    force_https: bool | None = None
    redirects_to: str | None = Field(default=None, max_length=1024)



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
    hosting_name: str | None = None
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
    # PHASE 20/21 — identity visible for smoke verification (not a secret)
    unix_username: str | None = None
    unix_uid: int | None = None
    unix_gid: int | None = None


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
    sftp_coming_note: str | None = None
    separate_from_ssh_sftp: bool = True
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
    host: str = "ifnotus.space"
    shared_ip: str | None = None
    port: int = 22
    password_auth_enabled: bool = True
    password_set: bool = False
    password: str | None = None
    connection_type: str = "SFTP"
    protocol: str = "sftp"
    shell_access: bool = False
    shares_password_with_ssh: bool = True
    keys: list[EnvironmentSftpKeyResponse] = Field(default_factory=list)
    command: str | None = None
    hint: str = ""
    message: str | None = None
    beta_note: str | None = None


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
    shares_password_with_sftp: bool = True
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
    high_warning: bool = False
    critical_warning: bool = False
    hard_exceeded: bool = False
    storage_status: str = "ok"
    storage_tier: str = "ok"
    components: dict = Field(default_factory=dict)
    os_quota: dict = Field(default_factory=dict)
    host: dict = Field(default_factory=dict)
    # Live samples (Phase E) — best-effort from cgroup slice / unix user.
    # cpu_usage_percent is relative to the plan vCPU quota when measurable.
    cpu_usage_percent: float | None = None
    cpu_usage_vcpu: float | None = None
    memory_usage_mb: float | None = None
    memory_limit_mb: float | None = None
    memory_pct: float | None = None
    process_count: int | None = None
    process_limit: int | None = None
    resources_enforced: bool = False
    resource_slice: str | None = None
    metrics_source: str | None = None
    metrics_updated_at: str | None = None
    resource_statuses: dict = Field(default_factory=dict)
    message: str | None = None
    note: str = (
        "Live disk is measured under your site folder. CPU/RAM samples come from your "
        "environment resource slice when available. Status labels show whether each limit "
        "is allocated, reported, enforced, or monitored."
    )


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


class EnvironmentMonitoringResponse(SchemaBase):
    environment_id: UUID
    domain: str | None = None
    level: str = "limited"
    checked_at: str | None = None
    disk: dict = Field(default_factory=dict)
    health_status: str = "unknown"
    site_status: str = "unknown"
    ssl: dict = Field(default_factory=dict)
    backups: dict = Field(default_factory=dict)
    applications: dict = Field(default_factory=dict)
    mail: dict = Field(default_factory=dict)
    processes: dict | None = None
    memory: dict | None = None
    cpu: dict | None = None
    databases: dict | None = None
    note: str | None = None


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
    max_jobs: int = 10
    min_interval_minutes: int = 5
    jobs_used: int = 0
    runs_as: str | None = None
    note: str = (
        "Jobs run on the server when due. Commands execute as your hosting user "
        "inside your site folder. Schedules must respect your package interval."
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
    recommended_ip: str = ""
    records: list[EnvironmentDnsRecordSchema] = Field(default_factory=list)
    namecheap_pushed: bool = False
    included_hostname: bool = False
    ns_live: bool | None = None
    resolves: bool | None = None
    dns_live: bool = False
    dns_mode: str | None = None
    a_records_live: bool = False
    cpanel_live: bool = False
    ssl_status: str | None = None
    ssl_ready: bool = False
    checklist: list[DnsChecklistItem] = Field(default_factory=list)
    status_summary: str = ""
    panel_hostname: str | None = None
    panel_url: str | None = None
    mail_hostname: str | None = None
    message: str = (
        "Connect your domain with IFNOTUS nameservers or A records at your registrar — either works."
    )
    dns_writer: str = "legacy_bind"
    single_writer: bool = True
    managed_dns: bool = True
    external_dns_supported: bool = True
    ns_redundancy: dict = Field(default_factory=dict)


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
    storage_provider: str = "local"
    storage_key: str | None = None
    offsite_status: str = "pending"
    retention_until: datetime | None = None


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


class CustomerFileMoveRequest(SchemaBase):
    source: str = Field(min_length=1, max_length=1024)
    destination: str = Field(min_length=1, max_length=1024)


class CustomerFileCopyRequest(SchemaBase):
    source: str = Field(min_length=1, max_length=1024)
    destination: str = Field(min_length=1, max_length=1024)


class CustomerFileExtractRequest(SchemaBase):
    path: str = Field(min_length=1, max_length=1024)
    destination: str | None = Field(default=None, max_length=1024)
    extract_here: bool = False


class CustomerFileCompressRequest(SchemaBase):
    paths: list[str] = Field(min_length=1, max_length=200)
    archive_name: str | None = Field(default=None, max_length=255)
    destination_dir: str | None = Field(default=None, max_length=1024)


class CustomerTrashEntrySchema(SchemaBase):
    trash_id: str
    original_path: str
    display_name: str
    item_type: str = "file"
    size_bytes: int | None = None
    deleted_at: datetime
    deleted_by: str | None = None


class CustomerTrashListResponse(SchemaBase):
    entries: list[CustomerTrashEntrySchema] = Field(default_factory=list)
    total_size_bytes: int = 0
    count: int = 0


class CustomerTrashRestoreRequest(SchemaBase):
    trash_id: str
    conflict_mode: str = "copy"  # "copy", "replace", "cancel"


class CustomerTrashMoveRequest(SchemaBase):
    paths: list[str] = Field(min_length=1, max_length=200)



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
    billing_term_months: int = 1
    grace_until: datetime | None = None
    last_reminder_days: int | None = None


class RenewSubscriptionRequest(SchemaBase):
    billing_term_months: int | None = None


class BillingTermPublicSchema(SchemaBase):
    months: int
    enabled: bool = True
    label: str
    recommended: bool = False
    discount_pct: float = 0
    fixed_price: float | None = None
    min_monthly_price: float | None = None
    monthly_price: float | None = None
    subtotal: float | None = None
    discount_amount: float | None = None
    plan_total: float | None = None
    savings_pct: float | None = None


class BillingTermsPublicResponse(SchemaBase):
    terms: list[BillingTermPublicSchema] = Field(default_factory=list)
    allowed_months: list[int] = Field(default_factory=lambda: [1, 3, 6, 12, 24, 36])


class BillingTermsAdminResponse(SchemaBase):
    terms: dict = Field(default_factory=dict)
    updated_at: str | None = None


class BillingTermsAdminUpdateRequest(SchemaBase):
    terms: dict


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


class HostingPanelThemePurchaseRequest(SchemaBase):
    theme_id: str = Field(min_length=2, max_length=64)


class HostingPanelThemeActivateRequest(SchemaBase):
    theme_id: str = Field(min_length=2, max_length=64)


class HostingPanelThemeStatusResponse(SchemaBase):
    environment_id: str
    active: str
    owned: list[str] = Field(default_factory=list)
    price_ghs: str = "2.00"
    theme: dict = Field(default_factory=dict)
    catalog: list[dict] = Field(default_factory=list)


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
    display_name: str | None = None
    cpu_total: int
    ram_total_gb: int
    storage_total_gb: int
    cpu_reserved_pct: int
    ram_reserved_pct: int | None = None
    storage_reserved_pct: int | None = None
    cpu_used: float
    ram_used: float
    storage_used: int
    cpu_free: float
    ram_free: float
    storage_free: int
    cpu_committed: float | None = None
    ram_committed_gb: float | None = None
    storage_committed_gb: int | None = None
    cpu_available: float | None = None
    ram_available_gb: float | None = None
    storage_available_gb: int | None = None
    cpu_reserve: int | None = None
    ram_reserve_gb: int | None = None
    storage_reserve_gb: int | None = None
    status: str


class StaffCapacityDashboardResponse(SchemaBase):
    display_name: str = "Shared Node 01"
    hostname: str = "ifnotus-1"
    checked_at: str | None = None
    live: dict = Field(default_factory=dict)
    policy: dict = Field(default_factory=dict)
    counts: dict = Field(default_factory=dict)
    ops: dict = Field(default_factory=dict)
    host_pressure: dict = Field(default_factory=dict)
    nodes: list[CapacityNodeResponse] = Field(default_factory=list)
    selling_paused: bool = False
    note: str = (
        "Committed capacity is plan allocations after system reserve. "
        "Actual usage is live host metrics — not advertised package RAM totals."
    )


class StudentHostnameRequest(SchemaBase):
    surname: str = Field(min_length=1, max_length=80)


class StudentHostnameResponse(SchemaBase):
    surname: str
    hostname: str
    available: bool = True
    message: str
    zone: str | None = None


class PanelAliasResolveResponse(SchemaBase):
    host: str
    kind: str
    environment_id: UUID
    domain: str
    status: str


class HostingSsoHandoffRequest(SchemaBase):
    environment_id: UUID | None = None
    domain: str | None = None
    tab: str | None = None


class HostingSsoHandoffResponse(SchemaBase):
    handoff_url: str
    token: str
    target_host: str
    environment_id: UUID
    domain: str
    expires_in: int = 120


class HostingSsoConsumeRequest(SchemaBase):
    token: str
    host: str | None = None


class HostingSsoConsumeResponse(SchemaBase):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    environment_id: UUID
    domain: str
    username: str | None = None


class PanelStatusResponse(SchemaBase):
    username: str
    domain: str | None = None
    password_set: bool
    environment_id: str | None = None


class PanelPasswordCreateRequest(SchemaBase):
    username: str = Field(min_length=2, max_length=128)
    password: str = Field(min_length=8, max_length=128)


class PanelLoginRequest(SchemaBase):
    username: str = Field(min_length=2, max_length=128)
    password: str = Field(min_length=8, max_length=128)
    device_fingerprint: str | None = Field(default=None, max_length=128)


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
    framework: str = Field(min_length=1, max_length=64)
    git_url: str | None = Field(default=None, max_length=512)
    runtime_version: str | None = Field(default=None, max_length=32)
    build_command: str | None = Field(default=None, max_length=512)
    start_command: str | None = Field(default=None, max_length=512)
    env_vars: dict[str, str] = Field(default_factory=dict)


class ApplicationCatalogEntry(SchemaBase):
    id: str
    runtime: str
    label: str
    stack_key: str
    stack_label: str
    runtime_version: str
    default_build: str
    default_start: str
    allowed: bool


class ApplicationInstanceResponse(SchemaBase):
    id: str
    environment_id: UUID
    name: str
    runtime: str
    framework: str | None = None
    framework_label: str | None = None
    runtime_version: str | None = None
    status: str = "pending"
    port: int | None = None
    git_url: str | None = None
    slug: str | None = None
    build_command: str | None = None
    start_command: str | None = None
    memory_limit_mb: int | None = None
    worker_limit: int | None = None
    resource_limits: dict | None = None
    message: str | None = None


class EnvironmentDatabaseV2Response(SchemaBase):
    id: str
    environment_id: UUID
    engine: str | None = None
    logical_name: str | None = None
    name: str | None = None
    username: str | None = None
    host: str | None = None
    port: int | None = None
    password_set: bool = False
    legacy: bool = False
    status: str | None = "active"
    size_mb: float | None = None
    storage_limit_mb: int | None = None
    remote_access_mode: str | None = None
    message: str | None = None


class EnvironmentDatabaseCreateRequest(SchemaBase):
    engine: str = Field(default="mysql", min_length=3, max_length=24)
    logical_name: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=64)
    username: str | None = Field(default=None, max_length=64)
    password: str | None = Field(default=None, max_length=128)


class EnvironmentDatabaseImportRequest(SchemaBase):
    sql: str = Field(min_length=1)


class EnvironmentDatabaseImportResponse(SchemaBase):
    success: bool = True
    message: str
    database: str
    engine: str
    statements_executed: int | None = None
    imported_bytes: int | None = None


class EnvironmentDatabaseRevealResponse(SchemaBase):
    id: str
    engine: str | None = None
    name: str | None = None
    username: str | None = None
    host: str | None = None
    port: int | None = None
    password: str | None = None
    connection_uri: str | None = None


class PhpMyAdminOpenResponse(SchemaBase):
    url: str
    engine: str = "mysql"
    database: str | None = None
    expires_in: int = 120


class HostingPasswordSetRequest(SchemaBase):
    password: str = Field(min_length=8, max_length=128)


class HostingPasswordSetResponse(SchemaBase):
    success: bool = True
    message: str
    username: str


class SubscriptionCancelRequest(SchemaBase):
    reason: str = Field(default="Customer requested cancellation", max_length=500)


class SubscriptionCancelResponse(SchemaBase):
    success: bool = True
    message: str
    subscription_id: UUID
