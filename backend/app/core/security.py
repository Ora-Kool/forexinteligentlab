import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt

from app.core.config import get_settings


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def verify_password(plain: str, expected: str) -> bool:
    return hmac.compare_digest(_digest(plain), _digest(expected))


def create_access_token(subject: str, workspace_id: int = 0) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": subject, "workspace_id": int(workspace_id), "exp": expire}
    return jwt.encode(payload, settings.app_secret_key, algorithm=settings.jwt_algorithm)


def decode_token_payload(token: str) -> dict | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.app_secret_key, algorithms=[settings.jwt_algorithm])
        if not payload.get("sub"):
            return None
        return payload
    except JWTError:
        return None


def decode_access_token(token: str) -> str | None:
    payload = decode_token_payload(token)
    return str(payload["sub"]) if payload else None
