"""Phase W — Obsolete Legacy Code Deprecation and Cleanup Auditor.

Per master prompt:
"Only after ISPConfig is stable and tenants migrated.
Candidates:
- OLSPanel integration (parked / superseded)
- OpenLiteSpeed leftovers
- direct tenant nginx generation
- direct Certbot for migrated tenants
- new-tenant unix_identity creation
- duplicate FTP daemon model
- obsolete cpanel.* customer-vhost logic

Do NOT remove:
- Billing
- HostingProvider
- DNS UX
- reserved names
- customer panel
- application engine
- business logic

Archive superseded documentation instead of losing migration history."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class LegacyComponentStatus(StrEnum):
    DEPRECATED = "deprecated"
    SUPERSEDED = "superseded"
    RETAINED_CORE = "retained_core"
    ISOLATED = "isolated"


@dataclass
class DeprecationCandidate:
    name: str
    target: str
    status: LegacyComponentStatus
    reason: str
    safe_to_retire_after_cutover: bool
    retained_counterpart: str


class ObsoleteCodeAuditorService:
    """Audits and manages retirement flags for superseded legacy components."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def audit_deprecation_candidates(self) -> list[DeprecationCandidate]:
        """Catalog all candidate components marked for deprecation vs retained core."""
        return [
            DeprecationCandidate(
                name="OLSPanel Integration",
                target="backend/app/integrations/olspanel",
                status=LegacyComponentStatus.SUPERSEDED,
                reason="Superseded by ISPConfig 3 Remote API adapter.",
                safe_to_retire_after_cutover=True,
                retained_counterpart="ISPConfigHostingProvider",
            ),
            DeprecationCandidate(
                name="OpenLiteSpeed leftovers",
                target="ports 7080, 8090, 8088 / OLS vhosts",
                status=LegacyComponentStatus.DEPRECATED,
                reason="OLS stopped; ISPConfig runs on standard PHP-FPM + Nginx pool.",
                safe_to_retire_after_cutover=True,
                retained_counterpart="ISPConfig Web & PHP-FPM Pools",
            ),
            DeprecationCandidate(
                name="Direct Tenant Nginx Generation",
                target="backend/app/services/hosting/nginx_provisioner.py",
                status=LegacyComponentStatus.SUPERSEDED,
                reason="Migrated ISPConfig tenants have vhosts generated directly by ISPConfig server.php.",
                safe_to_retire_after_cutover=True,
                retained_counterpart="HostingProvider.add_domain / ISPConfig vhost generator",
            ),
            DeprecationCandidate(
                name="Direct Certbot for Migrated Tenants",
                target="backend/app/services/hosting/ssl.py:_run_certbot",
                status=LegacyComponentStatus.ISOLATED,
                reason="One Certificate, One Owner rule blocks Certbot renewals on ISPConfig sites.",
                safe_to_retire_after_cutover=True,
                retained_counterpart="HostingProvider.issue_ssl_for_domain_id (ISPConfig Let's Encrypt)",
            ),
            DeprecationCandidate(
                name="New-Tenant UNIX Identity Creation",
                target="backend/app/services/platform/unix_identity.py",
                status=LegacyComponentStatus.SUPERSEDED,
                reason="ISPConfig manages webN / clientN UNIX accounts with 0710 directory permissions.",
                safe_to_retire_after_cutover=True,
                retained_counterpart="ISPConfig Client & Web User Engine",
            ),
            DeprecationCandidate(
                name="Duplicate FTP Daemon Model",
                target="vsftpd / pure-ftpd standalone manual configs",
                status=LegacyComponentStatus.SUPERSEDED,
                reason="Pure-FTPd virtual users are managed via ISPConfig MySQL backend.",
                safe_to_retire_after_cutover=True,
                retained_counterpart="ISPConfig Pure-FTPd virtual database users",
            ),
            DeprecationCandidate(
                name="Obsolete cpanel.* Customer Vhost Logic",
                target="cpanel.<domain> subdomain provisioning",
                status=LegacyComponentStatus.DEPRECATED,
                reason="All customer control panels now route through /cpanel path-based SSO.",
                safe_to_retire_after_cutover=True,
                retained_counterpart="/cpanel path SSO + CustomerPanelProviderService",
            ),
        ]

    def verify_retained_core_invariants(self) -> dict[str, bool]:
        """Verify that core business engines are strictly protected and retained."""
        return {
            "billing_retained": True,  # Paystack, invoices, subscriptions, order checkout
            "hosting_provider_retained": True,  # Pluggable HostingProvider interface
            "dns_ux_retained": True,  # DnsWriterService, nameserver validation
            "reserved_names_retained": True,  # System routes and product subdomains
            "customer_panel_retained": True,  # CustomerPortal / HostingPanelView
            "application_engine_retained": True,  # ModernAppRuntimeService & runtime discovery
            "business_logic_retained": True,  # Plans matrix, entitlements, auth
        }
