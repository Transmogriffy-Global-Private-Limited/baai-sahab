import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import IntegrityError

from .models import User
from .token_utils import (
    create_session,
    decrypt_and_decode_token,
    revoke_session,
)


# ---------- small helpers ----------

def _json_body(request):
    """
    Parse JSON body. Return dict or None if invalid.
    """
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return None


def _user_to_dict(user: User):
    return {
        "id": str(user.id),
        "name": user.name,
        "phone_number": user.phone_number,
    }


def _session_to_dict(session):
    return {
        "id": str(session.id),
        "created_at": session.created_at.isoformat() if hasattr(session, "created_at") else None,
        "updated_at": session.updated_at.isoformat() if hasattr(session, "updated_at") else None,
    }


def _auth_response(user, session, token: str):
    """
    Unified shape for signup / signin response.
    """
    return {
        "user": _user_to_dict(user),
        "session": _session_to_dict(session),
        "token": token,
    }


def _get_bearer_token(request):
    """
    Extract token from Authorization: Bearer <token> header.
    """
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip() or None


# ---------- views ----------

@csrf_exempt
def signup_view(request):
    """
    POST /.../signup/

    Body (JSON):
    {
        "name": "Some Name",
        "phone_number": "9876543210",
        "password": "plain-text-password"
    }

    Behavior:
    - creates User
    - hashes password
    - creates UserSession
    - returns encrypted token bound to that session
    """
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    data = _json_body(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body"}, status=400)

    name = (data.get("name") or "").strip()
    phone_number = (data.get("phone_number") or "").strip()
    password = data.get("password") or ""

    if not name or not phone_number or not password:
        return JsonResponse(
            {"detail": "name, phone_number, and password are required"},
            status=400,
        )

    # Create the user. We rely on the model's set_password to hash and save.
    try:
        user = User(
            name=name,
            phone_number=phone_number,
            password="",  # will be replaced by set_password()
        )
        user.save()
        user.set_password(password)
    except IntegrityError:
        # likely unique constraint on phone_number
        return JsonResponse(
            {"detail": "User with this phone_number already exists"},
            status=400,
        )

    # Create session + token
    session, token = create_session(user)

    return JsonResponse(_auth_response(user, session, token), status=201)


@csrf_exempt
def signin_view(request):
    """
    POST /.../signin/

    Body (JSON):
    {
        "phone_number": "9876543210",
        "password": "plain-text-password"
    }

    Behavior:
    - verifies credentials against User
    - creates new UserSession (per-device / per-login)
    - returns encrypted token bound to that session
    """
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    data = _json_body(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body"}, status=400)

    phone_number = (data.get("phone_number") or "").strip()
    password = data.get("password") or ""

    if not phone_number or not password:
        return JsonResponse(
            {"detail": "phone_number and password are required"},
            status=400,
        )

    try:
        user = User.objects.get(phone_number=phone_number)
    except User.DoesNotExist:
        return JsonResponse({"detail": "Invalid credentials"}, status=400)

    if not user.check_password(password):
        return JsonResponse({"detail": "Invalid credentials"}, status=400)

    # Create session + token
    session, token = create_session(user)

    return JsonResponse(_auth_response(user, session, token), status=200)


@csrf_exempt
def logout_view(request):
    """
    POST /.../logout/

    Uses Authorization: Bearer <token> header.

    Behavior:
    - extracts token
    - decrypts + validates user + session
    - revokes that specific session (so this device is logged out)
    """
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    token = _get_bearer_token(request)
    if not token:
        return JsonResponse(
            {"detail": "Authorization header with Bearer token required"},
            status=401,
        )

    user, session, error = decrypt_and_decode_token(token)

    if error is not None:
        # You can customize mapping error -> status if you like.
        # For now, treat all auth failures as 401.
        return JsonResponse(
            {"detail": "Invalid or expired token", "error": error},
            status=401,
        )

    if session is None:
        # Very unlikely if token was valid, but guard anyway
        return JsonResponse(
            {"detail": "Session missing for this token"},
            status=401,
        )

    # Revoke this session only (this device)
    revoke_session(session, hard_delete=False)  # or True if you prefer hard delete

    return JsonResponse(
        {
            "detail": "Logged out successfully",
            "session": _session_to_dict(session),
        },
        status=200,
    )
