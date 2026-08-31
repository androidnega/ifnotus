"""Deterministic unit tests for IFNOTUS Hostname Classification & Tenant Isolation Audit."""

import unittest

from app.services.platform.host_routing import classify_host, panel_alias_apex
from app.services.platform.panel_access import (
    control_panel_hostname,
    is_platform_hostname,
    webmail_hostname,
)


class TestFpanelHostnameAudit(unittest.TestCase):
    def test_staff_fpanel_classification(self):
        """fpanel.ifnotus.space must classify strictly as platform staff host, never customer panel."""
        kind = classify_host("fpanel.ifnotus.space")
        self.assertEqual(kind.kind, "platform")
        self.assertEqual(kind.apex, "ifnotus.space")
        self.assertTrue(is_platform_hostname("fpanel.ifnotus.space"))

        # Legacy staff alias
        kind_legacy = classify_host("cpanel.ifnotus.space")
        self.assertEqual(kind_legacy.kind, "platform")
        self.assertEqual(kind_legacy.apex, "ifnotus.space")

    def test_public_platform_classification(self):
        """ifnotus.space and www.ifnotus.space must classify as public platform."""
        for host in ["ifnotus.space", "www.ifnotus.space"]:
            kind = classify_host(host)
            self.assertEqual(kind.kind, "platform", f"Failed for {host}")
            self.assertEqual(kind.apex, "ifnotus.space")
            self.assertTrue(is_platform_hostname(host))

    def test_custom_domain_fpanel_classification(self):
        """fpanel.adastrachambers.com must resolve strictly to adastrachambers.com."""
        kind = classify_host("fpanel.adastrachambers.com")
        self.assertEqual(kind.kind, "custom_panel")
        self.assertEqual(kind.apex, "adastrachambers.com")
        self.assertEqual(panel_alias_apex("fpanel.adastrachambers.com"), "adastrachambers.com")
        self.assertEqual(control_panel_hostname("adastrachambers.com"), "fpanel.adastrachambers.com")
        self.assertEqual(webmail_hostname("adastrachambers.com"), "webmail.adastrachambers.com")
        self.assertFalse(is_platform_hostname("adastrachambers.com"))

        # Legacy cpanel shortcut
        kind_legacy = classify_host("cpanel.adastrachambers.com")
        self.assertEqual(kind_legacy.kind, "custom_panel")
        self.assertEqual(kind_legacy.apex, "adastrachambers.com")

    def test_platform_generated_customer_subdomain_fpanel(self):
        """fpanel.env-78f1b5ce.customers.ifnotus.space must resolve to env-78f1b5ce.customers.ifnotus.space."""
        env_domain = "env-78f1b5ce.customers.ifnotus.space"
        fpanel_host = f"fpanel.{env_domain}"

        # 1. Custom panel classification
        kind_panel = classify_host(fpanel_host)
        self.assertEqual(kind_panel.kind, "custom_panel")
        self.assertEqual(kind_panel.apex, env_domain)
        self.assertEqual(panel_alias_apex(fpanel_host), env_domain)

        # 2. Base environment website classification
        kind_site = classify_host(env_domain)
        self.assertEqual(kind_site.kind, "custom_site")
        self.assertEqual(kind_site.apex, env_domain)

        # 3. Panel access helpers
        self.assertEqual(control_panel_hostname(env_domain), fpanel_host)
        self.assertEqual(webmail_hostname(env_domain), f"webmail.{env_domain}")
        self.assertFalse(is_platform_hostname(env_domain))

    def test_ssl_san_includes_fpanel_and_nested_environments(self):
        """SSL certificate SAN generation must include fpanel for both custom domains and generated environments."""
        from unittest.mock import MagicMock
        from app.services.hosting.ssl import SslService

        # 1. Custom domain
        dom_custom = MagicMock()
        dom_custom.name = "adastrachambers.com"
        dom_custom.parent_domain_id = None
        sans_custom = SslService._issue_domain_names(dom_custom, None)
        self.assertIn("fpanel.adastrachambers.com", sans_custom)
        self.assertIn("cpanel.adastrachambers.com", sans_custom)
        self.assertIn("adastrachambers.com", sans_custom)

        # 2. Generated customer environment
        dom_env = MagicMock()
        dom_env.name = "env-78f1b5ce.customers.ifnotus.space"
        dom_env.parent_domain_id = None
        sans_env = SslService._issue_domain_names(dom_env, None)
        self.assertIn("env-78f1b5ce.customers.ifnotus.space", sans_env)
        self.assertIn("fpanel.env-78f1b5ce.customers.ifnotus.space", sans_env)

    def test_unknown_and_malformed_hosts(self):
        """Unknown or arbitrary hosts must not leak tenant data."""
        self.assertEqual(classify_host("").kind, "unknown")
        self.assertEqual(classify_host("invalid-no-dot").kind, "unknown")
        self.assertEqual(classify_host("localhost").kind, "unknown")
        self.assertEqual(classify_host("fpanel.invalid-apex").kind, "unknown")
