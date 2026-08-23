"""Phone OTP challenges for customer portal entry.

Primary store: Redis. Fallback: local JSON when Redis is unavailable.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_PATH = Path("/srv/apps/ifnotus/backend/.ifnotus/state/phone-otp.json")
FALLBACK_PATH = Path(".ifnotus/state/phone-otp.json")
OTP_TTL_MINUTES = 10
CODE_LENGTH = 6
MAX_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 45

KEY_PREFIX = "ifnotus:phone_otp:"
ATTEMPTS_PREFIX = "ifnotus:phone_otp:attempts:"

_lock = Lock()


@dataclass
class PhoneOtpChallenge:
    challenge_id: str
    phone: str
    code: str
    created_at: str
    expires_at: str
    consumed: bool = False

    def is_expired(self) -> bool:
        try:
            return datetime.fromisoformat(self.expires_at) <= datetime.now(UTC)
        except ValueError:
            return True


def _path() -> Path:
    if DEFAULT_PATH.parent.exists() or Path("/srv/apps/ifnotus/backend").exists():
        DEFAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        return DEFAULT_PATH
    FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    return FALLBACK_PATH


def _load_file() -> dict[str, PhoneOtpChallenge]:
    path = _path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, PhoneOtpChallenge] = {}
    for item in raw.get("challenges", []):
        try:
            ch = PhoneOtpChallenge(**item)
        except TypeError:
            continue
        out[ch.challenge_id] = ch
    return out


def _save_file(challenges: dict[str, PhoneOtpChallenge]) -> None:
    path = _path()
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    kept: list[dict[str, Any]] = []
    for ch in challenges.values():
        try:
            created = datetime.fromisoformat(ch.created_at)
        except ValueError:
            continue
        if ch.consumed and created < cutoff:
            continue
        if ch.is_expired() and created < cutoff:
            continue
        kept.append(asdict(ch))
    path.write_text(json.dumps({"challenges": kept}, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _new_code() -> str:
    return f"{secrets.randbelow(10**CODE_LENGTH):0{CODE_LENGTH}d}"


def _new_id() -> str:
    return secrets.token_urlsafe(18)


async def _redis():
    try:
        from redis.asyncio import Redis

        from app.core.config import get_settings

        settings = get_settings()
        client = Redis.from_url(str(settings.redis_url), decode_responses=True)
        await client.ping()
        return client
    except Exception as exc:  # noqa: BLE001
        logger.warning("phone_otp_redis_unavailable", error=str(exc))
        return None


async def assert_can_request(phone: str, *, settings: object | None = None) -> None:
    """Enforce resend cooldown; file-backed fallback when Redis is down (PHASE 38M)."""
    from app.core.exceptions import ValidationError
    from app.utils import limit_store

    redis = await _redis()
    cooldown_key = f"{KEY_PREFIX}cooldown:{phone}"

    if redis is None:
        if limit_store.in_cooldown(cooldown_key):
            raise ValidationError(
                f"Please wait {RESEND_COOLDOWN_SECONDS} seconds before requesting another code.",
                code="otp_cooldown",
            )
        if not limit_store.set_cooldown(cooldown_key, RESEND_COOLDOWN_SECONDS):
            raise ValidationError(
                f"Please wait {RESEND_COOLDOWN_SECONDS} seconds before requesting another code.",
                code="otp_cooldown",
            )
        return

    try:
        if await redis.exists(cooldown_key):
            raise ValidationError(
                f"Please wait {RESEND_COOLDOWN_SECONDS} seconds before requesting another code.",
                code="otp_cooldown",
            )
        await redis.setex(cooldown_key, RESEND_COOLDOWN_SECONDS, "1")
    finally:
        try:
            await redis.aclose()
        except Exception:  # noqa: BLE001
            pass


async def create_challenge(phone: str, *, settings: object | None = None) -> PhoneOtpChallenge:
    now = datetime.now(UTC)
    ch = PhoneOtpChallenge(
        challenge_id=_new_id(),
        phone=phone,
        code=_new_code(),
        created_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=OTP_TTL_MINUTES)).isoformat(),
    )
    redis = await _redis()

    if redis is not None:
        try:
            key = f"{KEY_PREFIX}{ch.challenge_id}"
            await redis.setex(key, OTP_TTL_MINUTES * 60, json.dumps(asdict(ch)))
            await redis.setex(f"{KEY_PREFIX}phone:{phone}", OTP_TTL_MINUTES * 60, ch.challenge_id)
            await redis.setex(f"{ATTEMPTS_PREFIX}{ch.challenge_id}", OTP_TTL_MINUTES * 60, "0")
            await redis.aclose()
            return ch
        except Exception as exc:  # noqa: BLE001
            logger.warning("phone_otp_redis_write_failed", error=str(exc))
            try:
                await redis.aclose()
            except Exception:  # noqa: BLE001
                pass

    with _lock:
        data = _load_file()
        data = {cid: c for cid, c in data.items() if not (c.phone == phone and not c.consumed)}
        data[ch.challenge_id] = ch
        _save_file(data)
    return ch


async def get_challenge(challenge_id: str) -> PhoneOtpChallenge | None:
    redis = await _redis()
    if redis is not None:
        try:
            raw = await redis.get(f"{KEY_PREFIX}{challenge_id}")
            await redis.aclose()
            if raw:
                return PhoneOtpChallenge(**json.loads(raw))
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("phone_otp_redis_read_failed", error=str(exc))
            try:
                await redis.aclose()
            except Exception:  # noqa: BLE001
                pass

    with _lock:
        return _load_file().get(challenge_id)


async def consume_challenge(challenge_id: str, code: str) -> PhoneOtpChallenge:
    from app.core.exceptions import AuthenticationError

    ch = await get_challenge(challenge_id)
    if ch is None or ch.consumed or ch.is_expired():
        raise AuthenticationError("That code expired. Request a new one.")

    attempts = await _bump_attempts(challenge_id)
    if attempts > MAX_ATTEMPTS:
        raise AuthenticationError("Too many attempts. Request a new code.")

    entered = (code or "").strip()
    from app.core.config import get_settings
    from app.core.dev_mode import dev_auth_bypass_allowed

    if not dev_auth_bypass_allowed(get_settings()):
        if len(entered) != len(ch.code) or not secrets.compare_digest(ch.code, entered):
            raise AuthenticationError("Invalid verification code.")
    elif not entered:
        # DEBUG: any non-empty code works; default to stored code when omitted.
        entered = ch.code

    ch.consumed = True
    await _persist(ch)
    return ch


async def _bump_attempts(challenge_id: str) -> int:
    from app.utils import limit_store

    redis = await _redis()
    if redis is not None:
        try:
            key = f"{ATTEMPTS_PREFIX}{challenge_id}"
            val = await redis.incr(key)
            await redis.expire(key, OTP_TTL_MINUTES * 60)
            await redis.aclose()
            return int(val)
        except Exception:  # noqa: BLE001
            try:
                await redis.aclose()
            except Exception:  # noqa: BLE001
                pass

    key = f"{ATTEMPTS_PREFIX}{challenge_id}"
    _, count = limit_store.incr(key, window_seconds=OTP_TTL_MINUTES * 60, limit=MAX_ATTEMPTS + 1)
    return count


async def _persist(ch: PhoneOtpChallenge) -> None:
    redis = await _redis()
    if redis is not None:
        try:
            ttl = max(
                1,
                int((datetime.fromisoformat(ch.expires_at) - datetime.now(UTC)).total_seconds()),
            )
            await redis.setex(f"{KEY_PREFIX}{ch.challenge_id}", ttl, json.dumps(asdict(ch)))
            await redis.aclose()
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("phone_otp_redis_persist_failed", error=str(exc))
            try:
                await redis.aclose()
            except Exception:  # noqa: BLE001
                pass

    with _lock:
        data = _load_file()
        data[ch.challenge_id] = ch
        _save_file(data)
