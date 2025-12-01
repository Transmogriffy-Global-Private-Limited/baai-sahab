from datetime import datetime, timezone
from typing import Optional, Tuple

import jwt
from cryptography.fernet import Fernet, InvalidToken as FernetInvalidToken
from django.conf import settings

from .models import User


# -------- time helpers --------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_access_lifetime_seconds() -> int:
    """
    Uses settings.JWT_ACCESS_TOKEN_LIFETIME (a timedelta),
    which you wired from JWT_ACCESS_TOKEN_LIFETIME_MIN in .env.
    """
    lifetime = getattr(settings, "JWT_ACCESS_TOKEN_LIFETIME", None)
    if lifetime is None:
        raise RuntimeError("JWT_ACCESS_TOKEN_LIFETIME is not configured in settings.")
    return int(lifetime.total_seconds())


# -------- crypto helpers --------

def _get_fernet() -> Fernet:
    """
    Build a Fernet instance from settings.JWT_ENCRYPTION_KEY.
    This must be a urlsafe base64-encoded 32-byte key.
    """
    key = getattr(settings, "JWT_ENCRYPTION_KEY", None)
    if not key:
        raise RuntimeError("JWT_ENCRYPTION_KEY is not set in settings.")
    if isinstance(key, str):
        key = key.encode("utf-8")
    return Fernet(key)


def _get_jwt_params():
    secret = getattr(settings, "JWT_SECRET_KEY", None)
    alg = getattr(settings, "JWT_ALGORITHM", None)

    if not secret:
        raise RuntimeError("JWT_SECRET_KEY is not set in settings.")
    if not alg:
        raise RuntimeError("JWT_ALGORITHM is not set in settings.")

    return secret, alg


# -------- public API --------

def create_encrypted_access_token_for_user(user: User) -> str:
    """
    Create a signed JWT with custom claims (user_id, phone_number),
    then encrypt it with Fernet. Returns an opaque string suitable for:

        Authorization: Bearer <token>
    """
    now = _now()
    exp_seconds = _get_access_lifetime_seconds()

    payload = {
        "user_id": str(user.id),
        "phone_number": user.phone_number,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp() + exp_seconds),
    }

    secret, alg = _get_jwt_params()

    token = jwt.encode(payload, secret, algorithm=alg)
    if isinstance(token, bytes):
        token = token.decode("utf-8")

    f = _get_fernet()
    encrypted = f.encrypt(token.encode("utf-8"))
    return encrypted.decode("utf-8")


def decrypt_and_decode_token(
    encrypted_token: str,
    expected_type: str = "access",
) -> Tuple[Optional[User], Optional[str]]:
    """
    Decrypts the token, verifies the JWT, enforces 'type', and returns (user, error_code).

    error_code values:
    - None                 -> success
    - "invalid_encrypted"  -> Fernet couldn't decrypt
    - "token_expired"      -> JWT 'exp' check failed
    - "invalid_token"      -> bad JWT / bad signature
    - "invalid_type"       -> payload['type'] != expected_type
    - "user_id_missing"    -> no user_id in payload
    - "user_not_found"     -> user doesn't exist in DB
    """
    if not encrypted_token:
        return None, "invalid_encrypted"

    try:
        f = _get_fernet()
        decrypted_bytes = f.decrypt(encrypted_token.encode("utf-8"))
    except (FernetInvalidToken, ValueError, TypeError):
        return None, "invalid_encrypted"

    decrypted = decrypted_bytes.decode("utf-8")
    secret, alg = _get_jwt_params()

    try:
        payload = jwt.decode(decrypted, secret, algorithms=[alg])
    except jwt.ExpiredSignatureError:
        return None, "token_expired"
    except jwt.InvalidTokenError:
        return None, "invalid_token"

    if expected_type is not None:
        token_type = payload.get("type")
        if token_type != expected_type:
            return None, "invalid_type"

    user_id = payload.get("user_id")
    if not user_id:
        return None, "user_id_missing"

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return None, "user_not_found"

    return user, None


def decrypt_and_get_payload(
    encrypted_token: str,
) -> Tuple[Optional[dict], Optional[str]]:
    """
    Like decrypt_and_decode_token, but returns the raw payload instead of the User.
    Useful if you want custom claim-level logic without hitting the DB.
    """
    if not encrypted_token:
        return None, "invalid_encrypted"

    try:
        f = _get_fernet()
        decrypted_bytes = f.decrypt(encrypted_token.encode("utf-8"))
    except (FernetInvalidToken, ValueError, TypeError):
        return None, "invalid_encrypted"

    decrypted = decrypted_bytes.decode("utf-8")
    secret, alg = _get_jwt_params()

    try:
        payload = jwt.decode(decrypted, secret, algorithms=[alg])
    except jwt.ExpiredSignatureError:
        return None, "token_expired"
    except jwt.InvalidTokenError:
        return None, "invalid_token"

    return payload, None
