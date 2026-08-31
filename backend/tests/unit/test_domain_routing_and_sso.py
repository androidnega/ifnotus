"""Unit tests for IFNOTUS Domain Access, Routing Standard, SSO, DNS, and SSL."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import Settings
from app.models.user import User
from app.models.platform import Customer, CustomerEnvironment
from app.services.hosting.nginx_provisioner import DomainNginxProvisioner
from app.services.hosting.ssl import SslService
from app.services.platform.authoritative_dns import AuthoritativeDnsService
from app.services.platform.panel_access import (
    control_panel_hostname,
    site_cpanel_shortcut_url,
    site_cpanel_url,
    site_mail_url,
    site_webmail_url,
    webmail_hostname,
)
from app.services.platform.sso import HostingSsoService


class TestDomainRoutingAndSso(unittest.TestCase):
    def test_canonical_cpanel_and_webmail_hostnames(self):
        # 1. Custom primary domain
        domain = "yalleydadzie.online"
        self.assertEqual(control_panel_hostname(domain), "fpanel.yalleydadzie.online")
        self.assertEqual(webmail_hostname(domain), "webmail.yalleydadzie.online")
        self.assertEqual(site_cpanel_url(domain), "https://fpanel.yalleydadzie.online/")
        self.assertEqual(site_cpanel_url(domain, tab="files"), "https://fpanel.yalleydadzie.online/files")
        self.assertEqual(site_cpanel_shortcut_url(domain), "https://yalleydadzie.online/fpanel")
        self.assertEqual(site_webmail_url(domain), "https://webmail.yalleydadzie.online")
        self.assertEqual(site_mail_url(domain), "https://webmail.yalleydadzie.online")

        # 2. Additional custom domains (e.g. adastrachambers.com)
        domain2 = "adastrachambers.com"
        self.assertEqual(control_panel_hostname(domain2), "fpanel.adastrachambers.com")
        self.assertEqual(webmail_hostname(domain2), "webmail.adastrachambers.com")
        self.assertEqual(site_cpanel_url(domain2), "https://fpanel.adastrachambers.com/")
        self.assertEqual(site_webmail_url(domain2), "https://webmail.adastrachambers.com")
        self.assertEqual(site_mail_url(domain2), "https://webmail.adastrachambers.com")

        # 3. Subdomains do not generate fpanel.<subdomain>
        subdomain = "blog.yalleydadzie.online"
        self.assertEqual(control_panel_hostname(subdomain), "fpanel.yalleydadzie.online")
        self.assertEqual(webmail_hostname(subdomain), "webmail.yalleydadzie.online")

    def test_ssl_issue_domain_names(self):
        domain_mock = MagicMock()
        domain_mock.name = "yalleydadzie.online"
        domain_mock.parent_domain_id = None

        names = SslService._issue_domain_names(domain_mock, parent=None)
        self.assertIn("yalleydadzie.online", names)
        self.assertIn("www.yalleydadzie.online", names)
        self.assertIn("fpanel.yalleydadzie.online", names)
        self.assertIn("webmail.yalleydadzie.online", names)
        self.assertIn("mail.yalleydadzie.online", names)


class TestAsyncDomainRouting(unittest.IsolatedAsyncioTestCase):
    async def test_sso_handoff_lifecycle(self):
        settings = Settings(secret_key="test" * 10)
        session = AsyncMock()

        user_id = uuid.uuid4()
        cust_id = uuid.uuid4()
        env_id = uuid.uuid4()

        user = User(id=user_id, email="test@example.com", is_active=True)
        customer = Customer(id=cust_id, user_id=user_id, full_name="Test Customer")
        env = CustomerEnvironment(
            id=env_id,
            customer_id=cust_id,
            domain="yalleydadzie.online",
            hosting_name="cust_yalleydadzie",
            status="active",
        )

        sso_service = HostingSsoService(settings, session)

        session.get.side_effect = lambda model, pk: env if model == CustomerEnvironment and pk == env_id else (
            user if model == User and pk == user_id else None
        )

        async def mock_require_for_user(self, uid):
            return customer

        with patch("app.services.platform.customers.CustomerService.require_for_user", mock_require_for_user):
            # 1. Create handoff token
            handoff = await sso_service.create_handoff(user, environment_id=env_id, tab="files")
            self.assertEqual(handoff["target_host"], "fpanel.yalleydadzie.online")
            self.assertTrue(handoff["token"])
            self.assertIn("fpanel.yalleydadzie.online/sso?token=", handoff["handoff_url"])
            self.assertIn("tab=files", handoff["handoff_url"])

            # 2. Consume handoff token
            consume_result = await sso_service.consume_handoff(
                handoff["token"],
                requested_host="cpanel.yalleydadzie.online",
            )
            self.assertTrue(consume_result["access_token"])
            self.assertTrue(consume_result["refresh_token"])
            self.assertEqual(consume_result["domain"], "yalleydadzie.online")
            self.assertEqual(consume_result["environment_id"], env_id)

            # 3. Single-use enforcement: consuming again should fail
            with self.assertRaises(Exception):
                await sso_service.consume_handoff(
                    handoff["token"],
                    requested_host="cpanel.yalleydadzie.online",
                )
