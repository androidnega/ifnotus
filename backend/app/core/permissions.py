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

    # Monitoring
    MONITORING_READ = "monitoring:read"

    # Users
    USERS_READ = "users:read"
    USERS_WRITE = "users:write"


class Role(StrEnum):
    """Built-in platform roles."""

    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.SUPERADMIN: frozenset(Permission),
    Role.ADMIN: frozenset(
        p
        for p in Permission
        if p not in {Permission.SYSTEM_ADMIN, Permission.USERS_WRITE, Permission.TERMINAL_EXECUTE}
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
        }
    ),
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
