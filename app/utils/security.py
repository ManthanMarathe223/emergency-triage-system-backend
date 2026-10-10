import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


def hash_password(password: str) -> str:
    """Hash a password with a salted PBKDF2 derivation."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    """Verify current PBKDF2 hashes and legacy SHA-256 hashes."""
    if not hashed_password:
        return False
    if hashed_password.startswith("pbkdf2_sha256$"):
        try:
            algorithm, iterations, salt_hex, digest_hex = hashed_password.split("$")
            if algorithm != "pbkdf2_sha256":
                return False
            digest = hashlib.pbkdf2_hmac(
                "sha256",
                plain_password.encode(),
                bytes.fromhex(salt_hex),
                int(iterations),
            )
            return hmac.compare_digest(digest.hex(), digest_hex)
        except (ValueError, TypeError):
            return False
    return hmac.compare_digest(
        hashlib.sha256(plain_password.encode("utf-8")).hexdigest(),
        hashed_password,
    )


JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
bearer_scheme = HTTPBearer(auto_error=True)


def validate_security_config() -> None:
    environment = os.getenv("ENVIRONMENT", "development").lower()
    if environment in {"production", "prod"} or os.getenv("VERCEL") == "1":
        if not JWT_SECRET_KEY or len(JWT_SECRET_KEY) < 32:
            raise RuntimeError(
                "JWT_SECRET_KEY must be set to a random value of at least 32 characters in production."
            )


def _signing_key() -> str:
    validate_security_config()
    if JWT_SECRET_KEY:
        return JWT_SECRET_KEY
    if os.getenv("TESTING") == "1":
        return "test-only-jwt-secret-change-me-32-chars"
    return "local-development-jwt-secret-change-me"


def _create_token(hospital_id: str, token_type: str, lifetime: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": hospital_id,
        "type": token_type,
        "iat": now,
        "exp": now + lifetime,
    }
    return jwt.encode(payload, _signing_key(), algorithm=JWT_ALGORITHM)


def create_access_token(hospital_id: str) -> str:
    return _create_token(
        hospital_id,
        "access",
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(hospital_id: str) -> str:
    return _create_token(
        hospital_id,
        "refresh",
        timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            _signing_key(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "type", "iat", "exp"]},
        )
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise credentials_error from exc
    if payload.get("type") != expected_type or not isinstance(payload.get("sub"), str):
        raise credentials_error
    return payload


def get_current_hospital_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    """Require a valid access token and return its hospital ID subject."""
    return str(decode_token(credentials.credentials, "access")["sub"])
