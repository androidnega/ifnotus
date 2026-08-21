"""Customer registration and profile management."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, ConflictError, NotFoundError
from app.core.permissions import Role
from app.core.security import hash_password, verify_password
from app.models.platform import AiCreditAccount, Customer, PlatformAuditLog
from app.models.user import User
from app.schemas.platform import (
    CustomerCompleteProfileRequest,
    CustomerPhoneOtpRequest,
    CustomerPhoneOtpRequestResponse,
    CustomerRegisterRequest,
    CustomerResponse,
    CustomerVerifyEmailRequest,
)

PENDING_EMAIL_DOMAIN = "phone.pending.ifnotus"


class CustomerService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session
        self._pending_codes: dict[str, tuple[str, datetime]] = {}

    @staticmethod
    def normalize_phone(raw: str) -> str:
        from app.services.platform.delivery import MessageDelivery

        phone = MessageDelivery._normalize_phone(raw)
        if not phone:
            from app.core.exceptions import ValidationError

            raise ValidationError("Enter a valid mobile number.")
        return phone

    @classmethod
    def is_profile_complete(cls, customer: Customer) -> bool:
        email = (customer.email or "").lower()
        if email.endswith(f"@{PENDING_EMAIL_DOMAIN}"):
            return False
        name = (customer.full_name or "").strip().lower()
        if len(name) < 2 or name in {"customer", "new customer"}:
            return False
        phone = (customer.phone or "").strip()
        if not phone:
            return False
        # Phone OTP path marks phone_verified; legacy email signup counts once phone+email exist.
        return True

    async def request_phone_otp(self, body: CustomerPhoneOtpRequest) -> CustomerPhoneOtpRequestResponse:
        from app.services.platform import phone_otp
        from app.services.platform.delivery import MessageDelivery

        phone = self.normalize_phone(body.phone)
        challenge = await phone_otp.create_challenge(phone)
        sms_body = f"IFNOTUS code: {challenge.code}. Valid for {phone_otp.OTP_TTL_MINUTES} minutes."
        delivery = MessageDelivery(self._settings).send_sms(to=phone, body=sms_body)
        sms_sent = bool(delivery.get("ok"))
        show_debug = bool(self._settings.debug) or not sms_sent
        message = (
            "We sent a code by SMS."
            if sms_sent
            else "SMS is not configured yet — use the code shown on this page."
        )
        return CustomerPhoneOtpRequestResponse(
            challenge_id=challenge.challenge_id,
            phone=phone,
            message=message,
            sms_sent=sms_sent,
            debug_code=challenge.code if show_debug else None,
        )

    async def verify_phone_otp(
        self,
        *,
        phone: str,
        challenge_id: str,
        code: str,
        ip_address: str | None = None,
    ) -> tuple[User, Customer]:
        from app.services.platform import phone_otp

        normalized = self.normalize_phone(phone)
        challenge = await phone_otp.consume_challenge(challenge_id, code)
        if challenge.phone != normalized:
            raise AuthenticationError("Phone number does not match this code.")

        customer = await self._find_by_phone(normalized)
        if customer is None:
            customer = await self._create_from_phone(normalized)
        else:
            customer.phone = normalized
            customer.phone_verified = True

        user = await self._session.get(User, customer.user_id)
        if user is None:
            raise AuthenticationError("Account is incomplete. Contact support.")
        if not user.is_active:
            raise AuthenticationError("This account is disabled.")

        user.last_login_at = datetime.now(UTC)
        if ip_address:
            user.last_login_ip = ip_address[:45]
        await self._session.flush()
        return user, customer

    async def complete_profile(
        self, customer: Customer, user: User, body: CustomerCompleteProfileRequest
    ) -> Customer:
        email = body.email.lower().strip()
        if email.endswith(f"@{PENDING_EMAIL_DOMAIN}"):
            from app.core.exceptions import ValidationError

            raise ValidationError("Enter a real email address.")

        existing = await self._session.execute(
            select(User).where(User.email == email, User.id != user.id, User.deleted_at.is_(None))
        )
        if existing.scalar_one_or_none():
            raise ConflictError("An account with this email already exists.")

        other = await self._session.execute(
            select(Customer).where(Customer.email == email, Customer.id != customer.id)
        )
        if other.scalar_one_or_none():
            raise ConflictError("An account with this email already exists.")

        customer.full_name = body.full_name.strip()
        customer.email = email
        if body.company is not None:
            customer.company = body.company.strip() or None
        customer.email_verified = False

        user.email = email
        user.full_name = customer.full_name
        user.username = self._username_from_email(email)
        if body.password:
            user.hashed_password = hash_password(body.password)

        await self._session.flush()
        return customer

    async def _find_by_phone(self, phone: str) -> Customer | None:
        result = await self._session.execute(select(Customer).where(Customer.phone == phone))
        customer = result.scalar_one_or_none()
        if customer:
            return customer
        # Also match common Ghana local form
        if phone.startswith("+233") and len(phone) == 13:
            local = "0" + phone[4:]
            result = await self._session.execute(select(Customer).where(Customer.phone == local))
            return result.scalar_one_or_none()
        return None

    async def _create_from_phone(self, phone: str) -> Customer:
        digits = re.sub(r"\D", "", phone)[-10:] or secrets.token_hex(4)
        email = f"p{digits}@{PENDING_EMAIL_DOMAIN}"
        # Ensure uniqueness if collision
        while True:
            exists = await self._session.execute(select(User).where(User.email == email))
            if exists.scalar_one_or_none() is None:
                break
            email = f"p{digits}{secrets.token_hex(2)}@{PENDING_EMAIL_DOMAIN}"

        user = User(
            email=email,
            username=self._username_from_email(email),
            hashed_password=hash_password(secrets.token_urlsafe(24)),
            full_name="Customer",
            is_active=True,
            is_superuser=False,
            roles=[Role.CUSTOMER.value],
        )
        self._session.add(user)
        await self._session.flush()

        customer = Customer(
            user_id=user.id,
            email=email,
            full_name="Customer",
            phone=phone,
            company=None,
            email_verified=False,
            phone_verified=True,
        )
        self._session.add(customer)
        await self._session.flush()

        credits = AiCreditAccount(customer_id=customer.id, credits_remaining=0, total_allocated=0)
        self._session.add(credits)
        self._session.add(
            PlatformAuditLog(
                customer_id=customer.id,
                actor_id=user.id,
                action="customer.phone_register",
                target_type="customer",
                target_id=str(customer.id),
                result="success",
            )
        )
        await self._session.flush()
        return customer

    async def register(self, body: CustomerRegisterRequest) -> tuple[CustomerResponse, str]:
        email = body.email.lower().strip()
        existing = await self._session.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            raise ConflictError("An account with this email already exists.")

        username = self._username_from_email(email)
        user = User(
            email=email,
            username=username,
            hashed_password=hash_password(body.password),
            full_name=body.full_name.strip(),
            is_active=True,
            is_superuser=False,
            roles=[Role.CUSTOMER.value],
        )
        self._session.add(user)
        await self._session.flush()

        phone = self.normalize_phone(body.phone) if body.phone else None
        customer = Customer(
            user_id=user.id,
            email=email,
            full_name=body.full_name.strip(),
            phone=phone,
            company=body.company,
            email_verified=False,
            phone_verified=False,
        )
        self._session.add(customer)
        await self._session.flush()

        credits = AiCreditAccount(customer_id=customer.id, credits_remaining=0, total_allocated=0)
        self._session.add(credits)
        self._session.add(
            PlatformAuditLog(
                customer_id=customer.id,
                actor_id=user.id,
                action="customer.register",
                target_type="customer",
                target_id=str(customer.id),
                result="success",
            )
        )

        code = f"{secrets.randbelow(1_000_000):06d}"
        token = self._sign_verify_token(customer.id, code)
        # Dev/ops: return token so UI can verify without SMTP. SMTP send is best-effort.
        await self._try_send_verify_email(email, code)
        return self.to_response(customer), token

    async def verify_email(self, body: CustomerVerifyEmailRequest) -> CustomerResponse:
        customer_id, code = self._parse_verify_token(body.token)
        if body.code.strip() != code:
            raise AuthenticationError("Invalid verification code.")
        customer = await self.get_by_id(customer_id)
        customer.email_verified = True
        await self._session.flush()
        return self.to_response(customer)

    async def get_by_user_id(self, user_id: UUID) -> Customer | None:
        result = await self._session.execute(select(Customer).where(Customer.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_by_id(self, customer_id: UUID) -> Customer:
        result = await self._session.execute(select(Customer).where(Customer.id == customer_id))
        customer = result.scalar_one_or_none()
        if customer is None:
            raise NotFoundError("Customer not found.")
        return customer

    async def require_for_user(self, user_id: UUID) -> Customer:
        customer = await self.get_by_user_id(user_id)
        if customer is None:
            raise NotFoundError("No customer profile for this account.")
        return customer

    async def authenticate_password(
        self,
        email: str,
        password: str,
        *,
        ip_address: str | None = None,
    ) -> tuple[User, Customer]:
        identity = email.lower().strip()
        result = await self._session.execute(select(User).where(User.email == identity, User.deleted_at.is_(None)))
        user = result.scalar_one_or_none()
        if user is None or not verify_password(password, user.hashed_password):
            raise AuthenticationError("Invalid credentials.")
        if Role.CUSTOMER.value not in (user.roles or []) and not user.is_superuser:
            # Staff can still have a customer profile later; for portal login require customer role
            customer = await self.get_by_user_id(user.id)
            if customer is None:
                raise AuthenticationError("This login is for IFNOTUS customer accounts.")
        customer = await self.require_for_user(user.id)
        user.last_login_at = datetime.now(UTC)
        if ip_address:
            user.last_login_ip = ip_address[:45]
        return user, customer

    async def last_login_ip_for(self, user: User) -> str | None:
        if user.last_login_ip:
            return user.last_login_ip
        from app.models.access import AccessAttempt

        result = await self._session.execute(
            select(AccessAttempt.ip_address)
            .where(
                AccessAttempt.user_id == user.id,
                AccessAttempt.success.is_(True),
                AccessAttempt.event_type == "login_success",
            )
            .order_by(AccessAttempt.attempted_at.desc())
            .limit(1)
        )
        ip = result.scalar_one_or_none()
        if ip:
            user.last_login_ip = ip[:45]
        return ip

    @classmethod
    def to_response(cls, customer: Customer, user: User | None = None) -> CustomerResponse:
        data = CustomerResponse.model_validate(customer)
        data = data.model_copy(
            update={
                "phone_verified": bool(getattr(customer, "phone_verified", False)),
                "profile_complete": cls.is_profile_complete(customer),
            }
        )
        if user is None:
            return data
        return data.model_copy(
            update={
                "last_login_at": getattr(user, "last_login_at", None),
                "last_login_ip": getattr(user, "last_login_ip", None),
                "two_factor_enabled": bool(
                    getattr(user, "totp_enabled", False) or customer.two_factor_enabled
                ),
            }
        )

    async def update_profile(self, customer: Customer, body) -> Customer:
        if body.full_name:
            customer.full_name = body.full_name.strip()
            user = await self._session.get(User, customer.user_id)
            if user:
                user.full_name = customer.full_name
        if body.phone:
            customer.phone = body.phone.strip()
        if body.company is not None:
            customer.company = body.company.strip() or None
        await self._session.flush()
        return customer

    async def change_password(self, user: User, current_password: str, new_password: str) -> None:
        if not verify_password(current_password, user.hashed_password):
            raise AuthenticationError("Current password is incorrect.")
        user.hashed_password = hash_password(new_password)
        await self._session.flush()

    async def totp_setup(self, user: User) -> dict:
        from app.services import totp as totp_svc

        secret = totp_svc.new_secret()
        user.totp_secret = secret
        user.totp_enabled = False
        await self._session.flush()
        return {
            "secret": secret,
            "otpauth_url": totp_svc.provisioning_uri(secret=secret, email=user.email),
            "enabled": False,
        }

    async def totp_confirm(self, user: User, code: str) -> None:
        from app.services import totp as totp_svc

        if not user.totp_secret or not totp_svc.verify_code(user.totp_secret, code):
            raise AuthenticationError("That authenticator code is not valid.")
        user.totp_enabled = True
        customer = await self.get_by_user_id(user.id)
        if customer:
            customer.two_factor_enabled = True
        await self._session.flush()

    async def totp_disable(self, user: User, code: str) -> None:
        from app.services import totp as totp_svc

        if user.totp_enabled and not totp_svc.verify_code(user.totp_secret or "", code):
            raise AuthenticationError("That authenticator code is not valid.")
        user.totp_enabled = False
        user.totp_secret = None
        customer = await self.get_by_user_id(user.id)
        if customer:
            customer.two_factor_enabled = False
        await self._session.flush()

    def _username_from_email(self, email: str) -> str:
        local = re.sub(r"[^a-z0-9._-]+", "", email.split("@", 1)[0].lower())[:40] or "customer"
        suffix = secrets.token_hex(3)
        return f"{local}_{suffix}"

    def _sign_verify_token(self, customer_id: UUID, code: str) -> str:
        exp = int((datetime.now(UTC) + timedelta(hours=24)).timestamp())
        payload = f"{customer_id}:{code}:{exp}"
        sig = hmac.new(
            self._settings.secret_key.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()[:32]
        return f"{payload}:{sig}"

    def _parse_verify_token(self, token: str) -> tuple[UUID, str]:
        parts = token.split(":")
        if len(parts) != 4:
            raise AuthenticationError("Invalid verification token.")
        customer_id_s, code, exp_s, sig = parts
        payload = f"{customer_id_s}:{code}:{exp_s}"
        expected = hmac.new(
            self._settings.secret_key.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()[:32]
        if not hmac.compare_digest(expected, sig):
            raise AuthenticationError("Invalid verification token.")
        if int(exp_s) < int(datetime.now(UTC).timestamp()):
            raise AuthenticationError("Verification token expired.")
        return UUID(customer_id_s), code

    async def _try_send_verify_email(self, email: str, code: str) -> None:
        from app.services.platform.delivery import MessageDelivery

        MessageDelivery(self._settings).send_email(
            to=email,
            subject="Verify your IFNOTUS account",
            body=f"Your IFNOTUS verification code is: {code}\n\nValid for 24 hours.",
        )
