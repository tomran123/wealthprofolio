import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings

settings = get_settings()


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    active_family_id: uuid.UUID
    jti: uuid.UUID


def create_access_token(subject: uuid.UUID | str, active_family_id: uuid.UUID | str) -> str:
    issued_at = datetime.now(timezone.utc)
    expire = issued_at + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(subject),
        "active_family": str(active_family_id),
        "jti": str(uuid.uuid4()),
        "iat": issued_at,
        "nbf": issued_at,
        "exp": expire,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> AccessTokenClaims | None:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={
                "require": [
                    "sub",
                    "active_family",
                    "jti",
                    "iat",
                    "nbf",
                    "exp",
                    "iss",
                    "aud",
                ]
            },
        )
        return AccessTokenClaims(
            user_id=uuid.UUID(str(payload["sub"])),
            active_family_id=uuid.UUID(str(payload["active_family"])),
            jti=uuid.UUID(str(payload["jti"])),
        )
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        return None
