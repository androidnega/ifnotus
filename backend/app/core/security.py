"""Security primitives: JWT, password hashing, token payloads."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.exceptions import AuthenticationError


class TokenType(StrEnum):
    """JWT token types."""

    ACCESS = "access"
    REFRESH = "refresh"


class TokenPayload(BaseModel):
    """Decoded JWT payload."""

    sub: UUID
    type: TokenType
    exp: datetime
    iat: datetime
    jti: str | None = None
    scopes: list[str] = Field(default_factory=list)


class TokenPair(BaseModel):
    """Access and refresh token pair."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_token(
    settings: Settings,
    *,
    subject: UUID,
    token_type: TokenType,
    scopes: list[str] | None = None,
    jti: str | None = None,
) -> str:
    """Create a signed JWT."""
    now = datetime.now(UTC)
    if token_type == TokenType.ACCESS:
        expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    else:
        expire = now + timedelta(days=settings.refresh_token_expire_days)

    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type.value,
        "exp": expire,
        "iat": now,
        "scopes": scopes or [],
    }
    if jti:
        payload["jti"] = jti

    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(settings: Settings, token: str) -> TokenPayload:
    """Decode and validate a JWT."""
    try:
        data = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        return TokenPayload(
            sub=UUID(data["sub"]),
            type=TokenType(data["type"]),
            exp=datetime.fromtimestamp(data["exp"], tz=UTC),
            iat=datetime.fromtimestamp(data["iat"], tz=UTC),
            jti=data.get("jti"),
            scopes=data.get("scopes", []),
        )
    except (JWTError, KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid or expired token.") from exc


def create_token_pair(
    settings: Settings,
    *,
    subject: UUID,
    scopes: list[str] | None = None,
) -> TokenPair:
    """Create access + refresh token pair."""
    access = create_token(settings, subject=subject, token_type=TokenType.ACCESS, scopes=scopes)
    refresh = create_token(settings, subject=subject, token_type=TokenType.REFRESH, scopes=scopes)
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )
