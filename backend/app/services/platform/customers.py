"""Customer registration and profile management."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, ConflictError, NotFoundError
from app.core.permissions import Role
from app.core.security import hash_password, verify_password
from app.models.platform import AiCreditAccount, Customer, CustomerEnvironment, PlatformAuditLog
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

# Progressive onboarding stages (do not use one global blocker for everything).
STAGE_PHONE = "phone_verified"
STAGE_FIRST = "first_name"
STAGE_LAST = "last_name"
STAGE_EMAIL = "email"
STAGE_DONE = "done"


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

    async def _email_for_phone(self, phone: str) -> str | None:
        """Return a real customer email for OTP mirroring, if one exists."""
        try:
            result = await self._session.execute(
                select(Customer).where(Customer.phone == phone).limit(1)
            )
            customer = result.scalar_one_or_none()
        except Exception:  # noqa: BLE001
            return None
        if customer is None or not customer.email:
            return None
        email = customer.email.strip().lower()
        if not email or email.endswith(f"@{PENDING_EMAIL_DOMAIN}"):
            return None
        return customer.email.strip()

    @staticmethod
    def _is_pending_email(email: str | None) -> bool:
        return (email or "").lower().endswith(f"@{PENDING_EMAIL_DOMAIN}")

    @staticmethod
    def _clean_name(value: str | None) -> str | None:
        text = (value or "").strip()
        if not text:
            return None
        if text.lower() in {"customer", "new customer"}:
            return None
        return text

    @classmethod
    def display_name(cls, customer: Customer) -> str:
        first = cls._clean_name(getattr(customer, "first_name", None))
        last = cls._clean_name(getattr(customer, "last_name", None))
        if first and last:
            return f"{first} {last}"
        if first:
            return first
        if last:
            return last
        full = cls._clean_name(customer.full_name)
        return full or "Customer"

    @classmethod
    def sync_full_name(cls, customer: Customer) -> None:
        customer.full_name = cls.display_name(customer)

    @classmethod
    def has_usable_first_name(cls, customer: Customer) -> bool:
        return bool(cls.resolved_first_name(customer))

    @classmethod
    def resolved_first_name(cls, customer: Customer) -> str | None:
        first = cls._clean_name(getattr(customer, "first_name", None))
        if first:
            return first
        full = cls._clean_name(customer.full_name)
        if not full:
            return None
        return full.split()[0]

    @classmethod
    def resolved_last_name(cls, customer: Customer) -> str | None:
        last = cls._clean_name(getattr(customer, "last_name", None))
        if last and len(last) >= 2:
            return last
        full = cls._clean_name(customer.full_name)
        if not full or " " not in full:
            return None
        rest = full.split(" ", 1)[1].strip()
        return rest if len(rest) >= 2 else None

    @classmethod
    def has_real_email(cls, customer: Customer) -> bool:
        return bool(customer.email) and not cls._is_pending_email(customer.email)

    @classmethod
    def can_student_hostname(cls, customer: Customer) -> bool:
        return bool(cls.resolved_last_name(customer))

    @classmethod
    def can_order(cls, customer: Customer) -> bool:
        phone = (customer.phone or "").strip()
        return bool(
            phone
            and cls.has_real_email(customer)
            and cls.resolved_first_name(customer)
            and cls.resolved_last_name(customer)
        )

    @classmethod
    def missing_for_order(cls, customer: Customer) -> list[str]:
        missing: list[str] = []
        if not cls.resolved_first_name(customer):
            missing.append("first_name")
        if not cls.resolved_last_name(customer):
            missing.append("last_name")
        if not cls.has_real_email(customer):
            missing.append("email")
        if not (customer.phone or "").strip():
            missing.append("phone")
        return missing

    @classmethod
    def missing_for_student(cls, customer: Customer) -> list[str]:
        return [] if cls.can_student_hostname(customer) else ["last_name"]

    @classmethod
    def compute_onboarding_stage(cls, customer: Customer) -> str:
        if cls.can_order(customer):
            return STAGE_DONE
        if cls.has_real_email(customer):
            return STAGE_EMAIL
        if cls.resolved_last_name(customer):
            return STAGE_LAST
        if cls.resolved_first_name(customer):
            return STAGE_FIRST
        return STAGE_PHONE

    @classmethod
    def is_profile_complete(cls, customer: Customer) -> bool:
        """Backward-compatible alias: profile is complete when checkout is allowed."""
        return cls.can_order(customer)

    def refresh_onboarding(self, customer: Customer) -> None:
        stage = self.compute_onboarding_stage(customer)
        customer.onboarding_stage = stage
        if stage == STAGE_DONE and customer.onboarding_completed_at is None:
            customer.onboarding_completed_at = datetime.now(UTC)
        if stage != STAGE_DONE:
            customer.onboarding_completed_at = None

    async def request_phone_otp(self, body: CustomerPhoneOtpRequest) -> CustomerPhoneOtpRequestResponse:
        from app.core.exceptions import AppException, ValidationError
        from app.services.platform import phone_otp

        phone = self.normalize_phone(body.phone)
        # Resend / request cooldown by phone (and production fails closed without Redis).
        try:
            await phone_otp.assert_can_request(phone, settings=self._settings)
        except ValidationError:
            raise
        except AppException:
            raise

        challenge = await phone_otp.create_challenge(phone, settings=self._settings)
        from app.core.dev_mode import dev_show_otp_code
        from app.core.logging import get_logger
        from app.services.platform import email_templates
        from app.services.platform.delivery import MessageDelivery
        import asyncio

        logger = get_logger(__name__)
        show_debug = dev_show_otp_code(self._settings)
        sms_debug = bool(getattr(self._settings, "sms_debug_mode", False))
        existing = await self._find_by_phone(phone)
        known_account = existing is not None
        sms_body = (
            f"Your code is {challenge.code}. Valid for {phone_otp.OTP_TTL_MINUTES} minutes."
        )
        title, text, html = email_templates.security_code(
            title="Your IFNOTUS sign-in code",
            code=challenge.code,
            minutes=phone_otp.OTP_TTL_MINUTES,
            context="Use this code to continue signing in to IFNOTUS.",
            recipient_hint=f"Sent for {phone}.",
        )
        email_target = await self._email_for_phone(phone)
        delivery = MessageDelivery(self._settings)

        if sms_debug:
            # Debug mode: skip provider send so signup/login works without SMS.
            return CustomerPhoneOtpRequestResponse(
                challenge_id=challenge.challenge_id,
                phone=phone,
                message="SMS debug mode — enter the code shown on this page.",
                sms_sent=False,
                debug_code=challenge.code if show_debug else None,
            )

        # New numbers (not in DB): show the code on-screen — do not claim SMS was sent.
        if not known_account:
            logger.info("otp_on_screen_for_new_phone", phone=phone)
            return CustomerPhoneOtpRequestResponse(
                challenge_id=challenge.challenge_id,
                phone=phone,
                message=(
                    "This number is not linked to an account yet. "
                    "Enter the code shown below to continue."
                ),
                sms_sent=False,
                debug_code=challenge.code,
            )

        # Known account: deliver OTP by SMS (and email mirror when available).
        sms_sent = False
        if delivery.sms_enabled:
            try:
                result = await asyncio.to_thread(delivery.send_sms, to=phone, body=sms_body)
                sms_sent = bool(result.get("ok"))
                if sms_sent:
                    logger.info(
                        "otp_sms_ok",
                        phone=phone,
                        provider=result.get("provider"),
                        status_code=result.get("status_code"),
                        response=(result.get("response") or "")[:240],
                    )
                else:
                    logger.warning("otp_sms_failed", phone=phone, result=result)
            except Exception as exc:  # noqa: BLE001
                logger.warning("otp_sms_error", phone=phone, error=str(exc))

        email_queued = bool(email_target and delivery.email_enabled)

        def _deliver_email() -> None:
            if not (email_queued and email_target):
                return
            try:
                mail = delivery.send_email(
                    to=email_target, subject=title, body=text, html=html
                )
                if not mail.get("ok"):
                    logger.warning("otp_email_bg_failed", to=email_target, result=mail)
            except Exception as exc:  # noqa: BLE001
                logger.warning("otp_email_bg_error", to=email_target, error=str(exc))

        if email_queued:
            try:
                loop = asyncio.get_running_loop()
                loop.run_in_executor(None, _deliver_email)
            except RuntimeError:
                _deliver_email()

        if sms_sent and email_queued:
            message = "We sent a code by SMS and email. Use the newest message only."
        elif sms_sent:
            message = "We sent a code by SMS. Use the newest message only."
        elif email_queued:
            message = "We sent a code by email."
        elif show_debug:
            message = "SMS is not configured yet — use the code shown on this page."
        else:
            message = (
                "We could not deliver the SMS right now. Wait a minute and try again, "
                "or contact support if it keeps failing."
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
        """Legacy one-shot endpoint — still works; prefers first/last when provided."""
        from app.core.exceptions import ValidationError

        first = (body.first_name or "").strip() or None
        last = (body.last_name or "").strip() or None
        if body.full_name and not (first and last):
            parts = body.full_name.strip().split(None, 1)
            first = first or (parts[0] if parts else None)
            last = last or (parts[1] if len(parts) > 1 else None)
        if not first or not last:
            raise ValidationError("Enter your first and family name.")
        patch = type(
            "Patch",
            (),
            {
                "first_name": first,
                "last_name": last,
                "full_name": None,
                "email": body.email,
                "phone": None,
                "company": body.company,
                "password": body.password,
            },
        )()
        return await self.update_profile(customer, patch, user=user)

    async def update_profile(
        self, customer: Customer, body, *, user: User | None = None
    ) -> Customer:
        from app.core.exceptions import ValidationError

        row = user or await self._session.get(User, customer.user_id)
        if row is None:
            raise ValidationError("Account not found.")

        if getattr(body, "first_name", None) is not None:
            cleaned = self._clean_name(body.first_name) or (body.first_name or "").strip()
            if cleaned and cleaned.lower() not in {"customer", "new customer"}:
                customer.first_name = cleaned[:120]
        if getattr(body, "last_name", None) is not None:
            cleaned = (body.last_name or "").strip()
            if len(cleaned) < 2:
                raise ValidationError("Enter your family name (at least 2 letters).")
            customer.last_name = cleaned[:120]
        if getattr(body, "full_name", None):
            parts = body.full_name.strip().split(None, 1)
            if parts:
                customer.first_name = parts[0][:120]
            if len(parts) > 1:
                customer.last_name = parts[1][:120]
            elif not customer.last_name:
                # Keep single token as first name only (soft).
                pass

        email = getattr(body, "email", None)
        if email:
            email = str(email).lower().strip()
            if email.endswith(f"@{PENDING_EMAIL_DOMAIN}"):
                raise ValidationError("Enter a real email address.")
            existing = await self._session.execute(
                select(User).where(User.email == email, User.id != row.id, User.deleted_at.is_(None))
            )
            if existing.scalar_one_or_none():
                raise ConflictError("An account with this email already exists.")
            other = await self._session.execute(
                select(Customer).where(Customer.email == email, Customer.id != customer.id)
            )
            if other.scalar_one_or_none():
                raise ConflictError("An account with this email already exists.")
            customer.email = email
            customer.email_verified = False
            row.email = email
            row.username = self._username_from_email(email)

        if getattr(body, "phone", None):
            customer.phone = self.normalize_phone(body.phone)

        if getattr(body, "company", None) is not None:
            customer.company = (body.company or "").strip() or None

        if getattr(body, "password", None):
            row.hashed_password = hash_password(body.password)

        self.sync_full_name(customer)
        row.full_name = customer.full_name
        self.refresh_onboarding(customer)
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
            first_name=None,
            last_name=None,
            phone=phone,
            company=None,
            email_verified=False,
            phone_verified=True,
            onboarding_stage=STAGE_PHONE,
            onboarding_completed_at=None,
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
        full = body.full_name.strip()
        parts = full.split(None, 1)
        customer = Customer(
            user_id=user.id,
            email=email,
            full_name=full,
            first_name=parts[0][:120] if parts else None,
            last_name=parts[1][:120] if len(parts) > 1 else None,
            phone=phone,
            company=body.company,
            email_verified=False,
            phone_verified=False,
            onboarding_stage=STAGE_PHONE,
        )
        self.sync_full_name(customer)
        self.refresh_onboarding(customer)
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

    async def _resolve_user_by_identity(self, identity: str) -> User | None:
        """Resolve customer login by email, account username, or hosting_name."""
        key = identity.lower().strip()
        if not key:
            return None
        result = await self._session.execute(
            select(User).where(User.email == key, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if user is not None:
            return user
        result = await self._session.execute(
            select(User).where(func.lower(User.username) == key, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if user is not None:
            return user
        env_result = await self._session.execute(
            select(CustomerEnvironment).where(
                func.lower(CustomerEnvironment.hosting_name) == key,
            )
        )
        env = env_result.scalar_one_or_none()
        if env is None:
            return None
        customer = await self._session.get(Customer, env.customer_id)
        if customer is None or not customer.user_id:
            return None
        return await self._session.get(User, customer.user_id)

    async def authenticate_password(
        self,
        email: str,
        password: str,
        *,
        ip_address: str | None = None,
    ) -> tuple[User, Customer]:
        user = await self._resolve_user_by_identity(email)
        if user is None or user.deleted_at is not None or not verify_password(password, user.hashed_password):
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
                "full_name": cls.display_name(customer),
                "first_name": cls.resolved_first_name(customer),
                "last_name": cls.resolved_last_name(customer),
                "phone_verified": bool(getattr(customer, "phone_verified", False)),
                "profile_complete": cls.is_profile_complete(customer),
                "has_password": not (customer.email and "@phone.pending.ifnotus" in customer.email),
                "onboarding_stage": getattr(customer, "onboarding_stage", None)
                or cls.compute_onboarding_stage(customer),
                "onboarding_completed_at": getattr(customer, "onboarding_completed_at", None),
                "can_order": cls.can_order(customer),
                "can_student_hostname": cls.can_student_hostname(customer),
                "missing_for_order": cls.missing_for_order(customer),
                "missing_for_student": cls.missing_for_student(customer),
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
        from app.services.platform import email_templates
        from app.services.platform.delivery import MessageDelivery
        import asyncio

        title, text, html = email_templates.security_code(
            title="Verify your IFNOTUS email",
            code=code,
            minutes=24 * 60,
            context="Enter this code in your IFNOTUS account to confirm your email address.",
            validity_label="24 hours",
        )
        # Prefer a friendlier subject for 24h email verification.
        try:
            await asyncio.to_thread(
                MessageDelivery(self._settings).send_email,
                to=email,
                subject=title,
                body=text,
                html=html,
            )
        except Exception:  # noqa: BLE001
            # Best-effort — never block signup/profile on SMTP failures.
            return
