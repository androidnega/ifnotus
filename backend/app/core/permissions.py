"""Role-based access control primitives."""

from enum import StrEnum


class Permission(StrEnum):
    """Platform permissions — extend as domains are implemented."""

    # System
    SYSTEM_READ = "system:read"
    SYSTEM_ADMIN = "system:admin"

    # Infrastructure
    SERVERS_READ = "servers:read"
    SERVERS_WRITE = "servers:write"
    SERVERS_DELETE = "servers:delete"

    # Deployments
    DEPLOYMENTS_READ = "deployments:read"
    DEPLOYMENTS_WRITE = "deployments:write"
    DEPLOYMENTS_EXECUTE = "deployments:execute"

    # Applications
    APPS_READ = "apps:read"
    APPS_WRITE = "apps:write"

    # Email
    EMAIL_READ = "email:read"
    EMAIL_WRITE = "email:write"

    # Hosting
    DOMAINS_READ = "domains:read"
    DOMAINS_WRITE = "domains:write"
    SSL_READ = "ssl:read"
    SSL_WRITE = "ssl:write"
    FILES_READ = "files:read"
    FILES_WRITE = "files:write"
    MAIL_READ = "mail:read"
    MAIL_WRITE = "mail:write"
    TERMINAL_EXECUTE = "terminal:execute"
    DATABASES_READ = "databases:read"
    DATABASES_WRITE = "databases:write"

    # Monitoring
    MONITORING_READ = "monitoring:read"

    # Users
    USERS_READ = "users:read"
    USERS_WRITE = "users:write"

    # Support tickets
    SUPPORT_READ = "support:read"
    SUPPORT_WRITE = "support:write"

    CUSTOMERS_MANAGE = "customers:manage"

    # Product platform (customers / plans / orders)
    PLATFORM_READ = "platform:read"
    PLATFORM_WRITE = "platform:write"
    # Tenant environment remediation (suspend, health, stacks, repair) — not plan CRUD
    PLATFORM_OPS = "platform:ops"


class Role(StrEnum):
    """Built-in platform roles."""

    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"
    CUSTOMER_CARE = "customer_care"
    CUSTOMER = "customer"


# Each staff role has a unique primary job:
# - superadmin: staff accounts, terminal, privilege switch, terminate, everything
# - admin: product/business (plans, billing confirm, customers) + env remediation; no host shell/files
# - operator: hands-on hosting (files/mail/dns/db) + env remediation; no plans/billing
# - customer_care: MoMo confirm + support tickets only
# - viewer: read-only across panel
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.SUPERADMIN: frozenset(Permission),
    Role.ADMIN: frozenset(
        {
            Permission.SYSTEM_READ,
            Permission.SERVERS_READ,
            Permission.SERVERS_DELETE,
            Permission.APPS_READ,
            Permission.APPS_WRITE,
            Permission.EMAIL_READ,
            Permission.MONITORING_READ,
            Permission.DOMAINS_READ,
            Permission.SSL_READ,
            Permission.FILES_READ,
            Permission.MAIL_READ,
            Permission.DATABASES_READ,
            Permission.USERS_READ,
            Permission.SUPPORT_READ,
            Permission.SUPPORT_WRITE,
            Permission.CUSTOMERS_MANAGE,
            Permission.PLATFORM_READ,
            Permission.PLATFORM_WRITE,
            Permission.PLATFORM_OPS,
        }
    ),
    Role.OPERATOR: frozenset(
        {
            Permission.SYSTEM_READ,
            Permission.SERVERS_READ,
            Permission.SERVERS_WRITE,
            Permission.DEPLOYMENTS_READ,
            Permission.DEPLOYMENTS_WRITE,
            Permission.DEPLOYMENTS_EXECUTE,
            Permission.APPS_READ,
            Permission.APPS_WRITE,
            Permission.MONITORING_READ,
            Permission.DOMAINS_READ,
            Permission.DOMAINS_WRITE,
            Permission.SSL_READ,
            Permission.SSL_WRITE,
            Permission.FILES_READ,
            Permission.FILES_WRITE,
            Permission.MAIL_READ,
            Permission.MAIL_WRITE,
            Permission.EMAIL_READ,
            Permission.EMAIL_WRITE,
            Permission.DATABASES_READ,
            Permission.DATABASES_WRITE,
            Permission.SUPPORT_READ,
            Permission.SUPPORT_WRITE,
            Permission.PLATFORM_READ,
            Permission.PLATFORM_OPS,
        }
    ),
    Role.VIEWER: frozenset(
        {
            Permission.SYSTEM_READ,
            Permission.SERVERS_READ,
            Permission.DEPLOYMENTS_READ,
            Permission.APPS_READ,
            Permission.EMAIL_READ,
            Permission.MONITORING_READ,
            Permission.DOMAINS_READ,
            Permission.SSL_READ,
            Permission.FILES_READ,
            Permission.MAIL_READ,
            Permission.DATABASES_READ,
            Permission.SUPPORT_READ,
            Permission.PLATFORM_READ,
        }
    ),
    Role.CUSTOMER_CARE: frozenset(
        {
            Permission.SYSTEM_READ,
            Permission.PLATFORM_READ,
            Permission.CUSTOMERS_MANAGE,
            Permission.SUPPORT_READ,
            Permission.SUPPORT_WRITE,
        }
    ),
    # Customer panel — portal APIs only. Host-wide staff routes are blocked.
    Role.CUSTOMER: frozenset(),
}

STAFF_ROLE_VALUES = frozenset(
    {
        Role.SUPERADMIN.value,
        Role.ADMIN.value,
        Role.OPERATOR.value,
        Role.VIEWER.value,
        Role.CUSTOMER_CARE.value,
    }
)

# Roles a superadmin may temporarily "work as" (never customer / superadmin).
PRIVILEGE_SWITCH_ROLES = frozenset(
    {
        Role.ADMIN.value,
        Role.OPERATOR.value,
        Role.VIEWER.value,
        Role.CUSTOMER_CARE.value,
    }
)

# Roles that may be assigned when creating/updating staff accounts.
CREATABLE_STAFF_ROLES = frozenset(
    {
        Role.ADMIN.value,
        Role.OPERATOR.value,
        Role.VIEWER.value,
        Role.CUSTOMER_CARE.value,
    }
)

# Human-readable unique job per role (API / settings copy).
ROLE_SUMMARIES: dict[str, str] = {
    Role.SUPERADMIN.value: "Full control — staff accounts, terminal, privilege switch, terminate sites",
    Role.ADMIN.value: "Business admin — plans, orders, customers, env remediation (no host shell/files)",
    Role.OPERATOR.value: "Hosting operator — domains, mail, files, databases, env remediation (no billing/plans)",
    Role.CUSTOMER_CARE.value: "Customer care — MoMo confirm, support tickets (no env or hosting edits)",
    Role.VIEWER.value: "Viewer — read-only across the staff panel",
}


def role_has_permission(role: Role, permission: Permission) -> bool:
    """Check if a role grants the given permission."""
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def roles_have_permission(roles: list[Role], permission: Permission) -> bool:
    """Check if any of the given roles grants the permission."""
    return any(role_has_permission(role, permission) for role in roles)


def permissions_for_roles(roles: list[Role], *, is_superuser: bool = False) -> list[str]:
    """Flatten role grants into a sorted permission list."""
    if is_superuser:
        return sorted(p.value for p in Permission)
    granted: set[str] = set()
    for role in roles:
        for perm in ROLE_PERMISSIONS.get(role, frozenset()):
            granted.add(perm.value)
    return sorted(granted)
