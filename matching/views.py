import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from customauth.token_utils import decrypt_and_decode_token
from userprofile.models import HelperProfile, SeekerPreferences


# ---------- common helpers ----------

def _get_bearer_token(request):
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip() or None


def _require_auth(request, allowed_types=None):
    """
    Decode token, return (user, error_response).

    allowed_types: set/list of user_type strings, e.g. {"user"} or {"helper"}.
    """
    token = _get_bearer_token(request)
    if not token:
        return None, JsonResponse(
            {"detail": "Authorization header with Bearer token required"},
            status=401,
        )

    user, session, error = decrypt_and_decode_token(token)
    if error is not None or user is None:
        return None, JsonResponse(
            {"detail": "Invalid or expired token", "error": error},
            status=401,
        )

    if allowed_types is not None and user.user_type not in allowed_types:
        return None, JsonResponse(
            {"detail": "Forbidden: insufficient role", "user_type": user.user_type},
            status=403,
        )

    return user, None


def _user_public_dict(user):
    return {
        "id": str(user.id),
        "name": user.name,
        "phone_number": user.phone_number,
        "user_type": getattr(user, "user_type", None),
    }


def _helper_profile_to_dict(hp: HelperProfile):
    return {
        "id": str(hp.id),
        "services": hp.services,
        "city": hp.city,
        "area": hp.area,
        "available_from": hp.available_from.isoformat(),
        "available_to": hp.available_to.isoformat(),
        "frequency_modes": hp.frequency_modes,
        "experience_years": hp.experience_years,
        "active": hp.active,
        "created_at": hp.created_at.isoformat() if hp.created_at else None,
        "updated_at": hp.updated_at.isoformat() if hp.updated_at else None,
    }


def _seeker_prefs_to_dict(prefs: SeekerPreferences):
    return {
        "id": str(prefs.id),
        "required_services": prefs.required_services,
        "city": prefs.city,
        "area": prefs.area,
        "from_time": prefs.from_time.isoformat(),
        "to_time": prefs.to_time.isoformat(),
        "frequency": prefs.frequency,
        "created_at": prefs.created_at.isoformat() if prefs.created_at else None,
        "updated_at": prefs.updated_at.isoformat() if prefs.updated_at else None,
    }


# ---------- 1. Get matches for USERS (seekers) ----------

@csrf_exempt
def seeker_matches_view(request):
    """
    GET /match/helpers/

    For user.user_type == "user" (seekers).

    Uses SeekerPreferences of the current user to find matching HelperProfiles.

    Matching logic:
    - helper.user_type == "helper"
    - helper.active == True
    - same city
    - helper.services contains ALL required_services
    - helper.frequency_modes contains seeker.frequency
    - helper availability window fully covers seeker window
    """
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    user, error_response = _require_auth(request, allowed_types={"user"})
    if error_response:
        return error_response

    try:
        prefs = SeekerPreferences.objects.get(user=user)
    except SeekerPreferences.DoesNotExist:
        return JsonResponse(
            {"detail": "Seeker preferences not found"},
            status=404,
        )

    required_services = prefs.required_services
    city = prefs.city

    qs = (
        HelperProfile.objects.filter(
            user__user_type="helper",
            active=True,                                   # <-- availability is 'active'
            city=city,
            services__contains=required_services,          # helper can do ALL required services
            frequency_modes__contains=[prefs.frequency],   # helper supports this frequency
            available_from__lte=prefs.from_time,
            available_to__gte=prefs.to_time,
        )
        .select_related("user")
    )

    results = []
    for hp in qs:
        helper_user = hp.user
        results.append(
            {
                "helper": _user_public_dict(helper_user),
                "helper_profile": _helper_profile_to_dict(hp),
            }
        )

    return JsonResponse(
        {
            "seeker_preferences": _seeker_prefs_to_dict(prefs),
            "matches": results,
        },
        status=200,
    )


# ---------- 2. Get matches for HELPERS ----------

@csrf_exempt
def helper_matches_view(request):
    """
    GET /match/seekers/

    For user.user_type == "helper".

    Uses HelperProfile of the current helper to find matching SeekerPreferences.

    Matching logic:
    - seeker.user_type == "user"
    - same city
    - seeker.required_services is a subset of helper.services
    - seeker.frequency is in helper.frequency_modes
    - seeker time window fits inside helper's availability window
    """
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    user, error_response = _require_auth(request, allowed_types={"helper"})
    if error_response:
        return error_response

    try:
        hp = HelperProfile.objects.get(user=user)
    except HelperProfile.DoesNotExist:
        return JsonResponse(
            {"detail": "Helper profile not found"},
            status=404,
        )

    helper_services = hp.services  # list of slugs

    qs = (
        SeekerPreferences.objects.filter(
            user__user_type="user",
            city=hp.city,
            required_services__contained_by=helper_services,
            from_time__gte=hp.available_from,
            to_time__lte=hp.available_to,
            frequency__in=hp.frequency_modes,
        )
        .select_related("user")
    )

    results = []
    for prefs in qs:
        seeker_user = prefs.user
        results.append(
            {
                "seeker": _user_public_dict(seeker_user),
                "seeker_preferences": _seeker_prefs_to_dict(prefs),
            }
        )

    return JsonResponse(
        {
            "helper_profile": _helper_profile_to_dict(hp),
            "matches": results,
        },
        status=200,
    )
