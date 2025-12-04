import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import IntegrityError

from .models import User, UserSession
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
        "user_type": user.user_type,
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
    POST /auth/signup/

    Body:
    {
        "name": "Some Name",
        "phone_number": "9876543210",
        "password": "plain-text-password",
        "user_type":"user" (or "helper")
    }
    """
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    data = _json_body(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body"}, status=400)

    name = (data.get("name") or "").strip()
    phone_number = (data.get("phone_number") or "").strip()
    password = data.get("password") or ""
    user_type = (data.get("user_type") or "user").strip().lower()

    # enforce allowed values
    allowed_types = {"user", "helper"}
    if user_type not in allowed_types:
        return JsonResponse(
            {"detail": f"user_type must be one of {sorted(allowed_types)}"},
            status=400,
        )

    if not name or not phone_number or not password:
        return JsonResponse(
            {"detail": "name, phone_number, and password are required"},
            status=400,
        )

    try:
        user = User(
            name=name,
            phone_number=phone_number,
            user_type=user_type,
            password="",  # will be replaced by set_password()
        )
        user.save()
        user.set_password(password)
    except IntegrityError:
        return JsonResponse(
            {"detail": "User with this phone_number already exists"},
            status=400,
        )

    session, token = create_session(user)
    return JsonResponse(_auth_response(user, session, token), status=201)


@csrf_exempt
def signin_view(request):
    """
    POST /auth/signin/

    Body:
    {
        "phone_number": "9876543210",
        "password": "plain-text-password"
    }
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

    session, token = create_session(user)
    return JsonResponse(_auth_response(user, session, token), status=200)


@csrf_exempt
def logout_view(request):
    """
    POST /auth/logout/

    Needs:
    - Authorization: Bearer <token>
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

    if error is not None or session is None:
        return JsonResponse(
            {"detail": "Invalid or expired token", "error": error},
            status=401,
        )

    # Revoke this session only (this device)
    revoke_session(session, hard_delete=False)

    return JsonResponse(
        {
            "detail": "Logged out successfully",
            "session": _session_to_dict(session),
        },
        status=200,
    )


@csrf_exempt
def change_password_view(request):
    """
    POST /auth/change-password/

    Needs:
    - Authorization: Bearer <token>

    Body:
    {
        "old_password": "old",
        "new_password": "new"
    }
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
    if error is not None or user is None:
        return JsonResponse(
            {"detail": "Invalid or expired token", "error": error},
            status=401,
        )

    data = _json_body(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body"}, status=400)

    old_password = data.get("old_password") or ""
    new_password = data.get("new_password") or ""

    if not old_password or not new_password:
        return JsonResponse(
            {"detail": "old_password and new_password are required"},
            status=400,
        )

    if not user.check_password(old_password):
        return JsonResponse(
            {"detail": "Old password is incorrect"},
            status=400,
        )

    user.set_password(new_password)

    return JsonResponse(
        {"detail": "Password changed successfully"},
        status=200,
    )


@csrf_exempt
def revoke_all_sessions_view(request):
    """
    POST /auth/revoke-all-sessions/

    Needs:
    - Authorization: Bearer <token>

    Body:
    {
        "password": "current-password"
    }

    Behavior:
    - verifies password of user from token
    - revokes *all* sessions for that user
      (including the one used in this request)
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
    if error is not None or user is None:
        return JsonResponse(
            {"detail": "Invalid or expired token", "error": error},
            status=401,
        )

    data = _json_body(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body"}, status=400)

    password = data.get("password") or ""
    if not password:
        return JsonResponse(
            {"detail": "password is required"},
            status=400,
        )

    if not user.check_password(password):
        return JsonResponse(
            {"detail": "Password is incorrect"},
            status=400,
        )

    # Revoke all sessions for this user
    sessions = UserSession.objects.filter(user=user)
    for s in sessions:
        revoke_session(s, hard_delete=True)

    return JsonResponse(
        {"detail": "All sessions revoked for this user"},
        status=200,
    )
