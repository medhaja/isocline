"""Password hashing, session tokens, secret encryption and API key hashing."""
import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from cryptography.fernet import Fernet

from .config import get_settings

_ph = PasswordHasher()


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except Exception:
        return False


def create_session_token(user_id: str) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user_id, "iat": now, "exp": now + timedelta(minutes=s.session_ttl_minutes), "typ": "session"},
        s.secret_key,
        algorithm="HS256",
    )


def decode_session_token(token: str) -> str | None:
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        return data["sub"] if data.get("typ") == "session" else None
    except jwt.PyJWTError:
        return None


def _fernet() -> Fernet:
    s = get_settings()
    key = s.encryption_key
    if not key:
        if s.env == "production":
            raise RuntimeError("ISOCLINE_ENCRYPTION_KEY must be set in production")
        # Development only: derive a stable key from the secret key.
        key = base64.urlsafe_b64encode(hashlib.sha256(s.secret_key.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt_secret(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt_secret(ciphertext: bytes) -> str:
    return _fernet().decrypt(ciphertext).decode()


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def random_token(n: int = 32) -> str:
    return secrets.token_urlsafe(n)
