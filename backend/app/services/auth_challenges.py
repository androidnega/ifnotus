"""One-time login challenges for untrusted admin IPs.

Primary store: Redis (shared across API workers, auto-TTL).
Fallback: local JSON file when Redis is unavailable (CLI / degraded mode).
"""

from __future__ import annotations

import asyncio
import hmac
import json
import secrets
import string
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_PATH = Path("/srv/apps/ifnotus/backend/.ifnotus/state/login-challenges.json")
FALLBACK_PATH = Path(".ifnotus/state/login-challenges.json")
CHALLENGE_TTL_MINUTES = 15
CODE_LENGTH = 6
MAX_ATTEMPTS = 5

KEY_PREFIX = "ifnotus:login_challenge:"
INDEX_KEY = "ifnotus:login_challenges:pending"
USER_IP_PREFIX = "ifnotus:login_challenge:by_user_ip:"
ATTEMPTS_PREFIX = "ifnotus:login_challenge:attempts:"

_lock = Lock()


@dataclass
class LoginChallenge:
    challenge_id: str
    code: str
    ip_address: str
    user_id: str
    username_or_email: str
    device_fingerprint: str | None
    user_agent: str | None
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


def _load_file() -> dict[str, LoginChallenge]:
    path = _path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, LoginChallenge] = {}
    for item in raw.get("challenges", []):
        try:
            ch = LoginChallenge(**item)
        except TypeError:
            continue
        out[ch.challenge_id] = ch
    return out


def _save_file(challenges: dict[str, LoginChallenge]) -> None:
    path = _path()
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    kept: list[dict] = []
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


def _new_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(4))
    return f"IF-{body}"


def _new_code() -> str:
    return "".join(secrets.choice(string.digits) for _ in range(CODE_LENGTH))


def _normalize_id(challenge_id: str) -> str:
    return challenge_id.strip().upper()


def _ttl_seconds() -> int:
    return CHALLENGE_TTL_MINUTES * 60


async def _redis():
    """Return a short-lived Redis client, or None if unavailable."""
    try:
        from redis.asyncio import Redis

        from app.core.config import get_settings

        settings = get_settings()
        client = Redis.from_url(str(settings.redis_url), decode_responses=True)
        await client.ping()
        return client
    except Exception as exc:  # noqa: BLE001
        logger.warning("login_challenge_redis_unavailable", error=str(exc))
        return None


def _challenge_key(challenge_id: str) -> str:
    return f"{KEY_PREFIX}{_normalize_id(challenge_id)}"


def _user_ip_key(user_id: str, ip_address: str) -> str:
    return f"{USER_IP_PREFIX}{user_id}:{ip_address}"


def _attempts_key(challenge_id: str) -> str:
    return f"{ATTEMPTS_PREFIX}{_normalize_id(challenge_id)}"


def _from_raw(raw: dict[str, Any] | str | None) -> LoginChallenge | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    try:
        return LoginChallenge(**raw)  # type: ignore[arg-type]
    except TypeError:
        return None


async def create_challenge(
    *,
    ip_address: str,
    user_id: str,
    username_or_email: str,
    device_fingerprint: str | None,
    user_agent: str | None,
) -> LoginChallenge:
    now = datetime.now(UTC)
    ch = LoginChallenge(
        challenge_id=_new_id(),
        code=_new_code(),
        ip_address=ip_address,
        user_id=user_id,
        username_or_email=username_or_email,
        device_fingerprint=device_fingerprint,
        user_agent=(user_agent or "")[:512] or None,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=CHALLENGE_TTL_MINUTES)).isoformat(),
        consumed=False,
    )
    ttl = _ttl_seconds()
    exp_ts = int((now + timedelta(minutes=CHALLENGE_TTL_MINUTES)).timestamp())

    redis = await _redis()
    if redis is not None:
        try:
            # Invalidate previous open challenge for same user+IP.
            old_id = await redis.get(_user_ip_key(user_id, ip_address))
            if old_id:
                await redis.delete(_challenge_key(str(old_id)), _attempts_key(str(old_id)))
                await redis.zrem(INDEX_KEY, _normalize_id(str(old_id)))

            pipe = redis.pipeline()
            pipe.set(_challenge_key(ch.challenge_id), json.dumps(asdict(ch)), ex=ttl)
            pipe.set(_user_ip_key(user_id, ip_address), ch.challenge_id, ex=ttl)
            pipe.zadd(INDEX_KEY, {_normalize_id(ch.challenge_id): exp_ts})
            pipe.expire(INDEX_KEY, ttl + 60)
            await pipe.execute()
            logger.info(
                "login_challenge_created",
                challenge_id=ch.challenge_id,
                ip=ip_address,
                user=username_or_email,
                store="redis",
            )
            return ch
        except Exception as exc:  # noqa: BLE001
            logger.warning("login_challenge_redis_write_failed", error=str(exc))
        finally:
            await redis.aclose()

    # File fallback
    with _lock:
        challenges = _load_file()
        for existing in list(challenges.values()):
            if (
                not existing.consumed
                and not existing.is_expired()
                and existing.ip_address == ip_address
                and existing.user_id == user_id
            ):
                existing.consumed = True
        challenges[ch.challenge_id] = ch
        _save_file(challenges)
    logger.info(
        "login_challenge_created",
        challenge_id=ch.challenge_id,
        ip=ip_address,
        user=username_or_email,
        store="file",
    )
    return ch


async def list_pending() -> list[LoginChallenge]:
    redis = await _redis()
    if redis is not None:
        try:
            now_ts = int(datetime.now(UTC).timestamp())
            await redis.zremrangebyscore(INDEX_KEY, "-inf", now_ts)
            ids = await redis.zrange(INDEX_KEY, 0, -1)
            pending: list[LoginChallenge] = []
            for cid in ids:
                raw = await redis.get(_challenge_key(str(cid)))
                ch = _from_raw(raw)
                if ch is None or ch.consumed or ch.is_expired():
                    await redis.zrem(INDEX_KEY, str(cid))
                    continue
                pending.append(ch)
            pending.sort(key=lambda c: c.created_at, reverse=True)
            return pending
        except Exception as exc:  # noqa: BLE001
            logger.warning("login_challenge_redis_list_failed", error=str(exc))
        finally:
            await redis.aclose()

    with _lock:
        challenges = _load_file()
        pending = [ch for ch in challenges.values() if not ch.consumed and not ch.is_expired()]
        pending.sort(key=lambda c: c.created_at, reverse=True)
        return pending


async def get_challenge(challenge_id: str) -> LoginChallenge | None:
    cid = _normalize_id(challenge_id)
    redis = await _redis()
    if redis is not None:
        try:
            raw = await redis.get(_challenge_key(cid))
            ch = _from_raw(raw)
            if ch is not None:
                return ch
        except Exception as exc:  # noqa: BLE001
            logger.warning("login_challenge_redis_get_failed", error=str(exc))
        finally:
            await redis.aclose()

    with _lock:
        challenges = _load_file()
        return challenges.get(cid) or challenges.get(challenge_id.strip())


async def consume_challenge(challenge_id: str, code: str) -> LoginChallenge | None:
    cid = _normalize_id(challenge_id)
    code = code.strip()
    redis = await _redis()
    if redis is not None:
        try:
            raw = await redis.get(_challenge_key(cid))
            ch = _from_raw(raw)
            if ch is None or ch.consumed or ch.is_expired():
                # Fall through to file in case challenge was created during Redis outage.
                pass
            else:
                attempts = int(await redis.incr(_attempts_key(cid)))
                if attempts == 1:
                    await redis.expire(_attempts_key(cid), _ttl_seconds())
                if attempts > MAX_ATTEMPTS:
                    await redis.delete(_challenge_key(cid), _attempts_key(cid))
                    await redis.zrem(INDEX_KEY, cid)
                    logger.warning("login_challenge_locked", challenge_id=cid, attempts=attempts)
                    return None
                if not hmac.compare_digest(ch.code, code):
                    return None
                ch.consumed = True
                await redis.delete(_challenge_key(cid), _attempts_key(cid), _user_ip_key(ch.user_id, ch.ip_address))
                await redis.zrem(INDEX_KEY, cid)
                return ch
        except Exception as exc:  # noqa: BLE001
            logger.warning("login_challenge_redis_consume_failed", error=str(exc))
        finally:
            await redis.aclose()

    with _lock:
        challenges = _load_file()
        ch = challenges.get(cid) or challenges.get(challenge_id.strip())
        if ch is None or ch.consumed or ch.is_expired():
            return None
        if not hmac.compare_digest(ch.code, code):
            return None
        ch.consumed = True
        challenges[ch.challenge_id] = ch
        _save_file(challenges)
        return ch


async def approve_challenge(challenge_id: str) -> LoginChallenge | None:
    """Mark challenge consumed after CLI approval (code already verified offline)."""
    cid = _normalize_id(challenge_id)
    redis = await _redis()
    if redis is not None:
        try:
            raw = await redis.get(_challenge_key(cid))
            ch = _from_raw(raw)
            if ch is not None and not ch.consumed and not ch.is_expired():
                ch.consumed = True
                await redis.delete(
                    _challenge_key(cid),
                    _attempts_key(cid),
                    _user_ip_key(ch.user_id, ch.ip_address),
                )
                await redis.zrem(INDEX_KEY, cid)
                return ch
        except Exception as exc:  # noqa: BLE001
            logger.warning("login_challenge_redis_approve_failed", error=str(exc))
        finally:
            await redis.aclose()

    with _lock:
        challenges = _load_file()
        ch = challenges.get(cid) or challenges.get(challenge_id.strip())
        if ch is None or ch.consumed or ch.is_expired():
            return None
        ch.consumed = True
        challenges[ch.challenge_id] = ch
        _save_file(challenges)
        return ch


# Sync wrappers for CLI scripts (ifnotus-unlock).
def list_pending_sync() -> list[LoginChallenge]:
    return asyncio.run(list_pending())


def get_challenge_sync(challenge_id: str) -> LoginChallenge | None:
    return asyncio.run(get_challenge(challenge_id))


def approve_challenge_sync(challenge_id: str) -> LoginChallenge | None:
    return asyncio.run(approve_challenge(challenge_id))
