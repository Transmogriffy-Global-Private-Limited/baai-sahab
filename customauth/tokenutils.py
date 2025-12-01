from datetime import datetime, timezone
from typing import Optional, Tuple

import jwt
from cryptography.fernet import Fernet, InvalidToken as FernetInvalidToken
from django.conf import settings

from .models import User, UserSession


# -------- time helpers --------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_access_lifetime_seconds() -> int:
    """
    Uses settings.JWT_ACCESS_TOKEN_LIFETIME (a timedelta),
    wired from JWT_ACCESS_TOKEN_LIFETIME_MIN in .env.
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


# -------- session helpers (DB) --------

def _create_session_row(user: User) -> UserSession:
    """
    Low-level: create a new session row for the user.
    One device / login = one UserSession.
    """
    return UserSession.objects.create(user=user)


def create_encrypted_access_token_for_session(session: UserSession) -> str:
    """
    Create a signed JWT for a given session and then encrypt it.

    Payload includes:
    - user_id
    - phone_number
    - session_id
    - session_version_id
    - type = "access"
    - iat, exp

    Returns opaque string suitable for:
        Authorization: Bearer <token>
    """
    now = _now()
    exp_seconds = _get_access_lifetime_seconds()

    user = session.user

    payload = {
        "user_id": str(user.id),
        "phone_number": user.phone_number,
        "session_id": str(session.id),
        "session_version_id": str(session.version_id),
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


def create_session(user: User) -> Tuple[UserSession, str]:
    """
    High-level helper used in signin:
    - creates a new UserSession for the user
    - creates an encrypted access token bound to that session

    Returns (session, token).
    """
    session = _create_session_row(user)
    token = create_encrypted_access_token_for_session(session)
    return session, token


def revoke_session(session: UserSession, hard_delete: bool = False) -> None:
    """
    Revoke a single session.

    Two strategies:
    - hard_delete=True  -> delete the row (tokens get 'session_not_found')
    - hard_delete=False -> rotate version_id (tokens get 'session_version_mismatch')

    You can pick which one you want from your signout logic.
    """
    if hard_delete:
        session.delete()
    else:
        # uses the model helper if you defined rotate_version()
        if hasattr(session, "rotate_version"):
            session.rotate_version()
        else:
            # fallback: emulate rotate_version if method not present
            import uuid
            session.version_id = uuid.uuid4()
            session.save(update_fields=["version_id", "updated_at"])


# -------- token decode / validation --------

def decrypt_and_decode_token(
    encrypted_token: str,
    expected_type: str = "access",
) -> Tuple[Optional[User], Optional[UserSession], Optional[str]]:
    """
    Decrypts the token, verifies the JWT, validates user + session,
    and returns (user, session, error_code).

    error_code values:
    - None                       -> success
    - "invalid_encrypted"        -> Fernet couldn't decrypt
    - "token_expired"            -> JWT 'exp' check failed
    - "invalid_token"            -> bad JWT / bad signature
    - "invalid_type"             -> payload['type'] != expected_type
    - "user_id_missing"          -> no user_id in payload
    - "session_id_missing"       -> no session_id in payload
    - "session_not_found"        -> UserSession not in DB
    - "user_not_found"           -> User not in DB
    - "session_user_mismatch"    -> session.user != user
    - "session_version_mismatch" -> session.version_id != payload version
    """
    if not encrypted_token:
        return None, None, "invalid_encrypted"

    # Decrypt the outer layer
    try:
        f = _get_fernet()
        decrypted_bytes = f.decrypt(encrypted_token.encode("utf-8"))
    except (FernetInvalidToken, ValueError, TypeError):
        return None, None, "invalid_encrypted"

    decrypted = decrypted_bytes.decode("utf-8")
    secret, alg = _get_jwt_params()

    # Decode and verify JWT
    try:
        payload = jwt.decode(decrypted, secret, algorithms=[alg])
    except jwt.ExpiredSignatureError:
        return None, None, "token_expired"
    except jwt.InvalidTokenError:
        return None, None, "invalid_token"

    # Type check (access / refresh etc.)
    if expected_type is not None:
        token_type = payload.get("type")
        if token_type != expected_type:
            return None, None, "invalid_type"

    # User
    user_id = payload.get("user_id")
    if not user_id:
        return None, None, "user_id_missing"

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return None, None, "user_not_found"

    # Session
    session_id = payload.get("session_id")
    session_version_id = payload.get("session_version_id")

    if not session_id:
        return user, None, "session_id_missing"

    try:
        session = UserSession.objects.get(id=session_id)
    except UserSession.DoesNotExist:
        return user, None, "session_not_found"

    if session.user_id != user.id:
        return user, None, "session_user_mismatch"

    if not session_version_id or str(session.version_id) != str(session_version_id):
        return user, session, "session_version_mismatch"

    # All good
    return user, session, None


def decrypt_and_get_payload(
    encrypted_token: str,
) -> Tuple[Optional[dict], Optional[str]]:
    """
    Decrypt token and return raw JWT payload (no DB lookup).

    error_code values:
    - None                 -> success
    - "invalid_encrypted"  -> Fernet couldn't decrypt
    - "token_expired"      -> JWT 'exp' check failed
    - "invalid_token"      -> bad JWT / bad signature
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
