import hashlib
from typing import Optional


def hash_password(password: str) -> str:
    """Generate SHA-256 hash for password."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    """Verify plain password against hashed password."""
    if not hashed_password:
        return True
    return hash_password(plain_password) == hashed_password
