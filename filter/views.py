from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q

from customauth.token_utils import decrypt_and_decode_token
from userprofile.models import UserProfile, HelperProfile, SeekerPreferences


# ---------- common helpers ----------

def _get_bearer_token(request):
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip() or None


def _require_auth(request, allowed_types=None):
    """
    Decode token, return (user, error_response).
    allowed_types: set/list of user_type strings (e.g. {"user", "helper"}).
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


def _profile_dict_or_none(profile: UserProfile | None):
    if profile is None:
        return None
    return {
        "id": str(profile.id),
        "display_name": profile.display_name,
        "avatar_url": profile.avatar_url,
        "bio": profile.bio,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
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


def _parse_bool_param(val: str | None):
    if val is None:
        return None
    v = val.strip().lower()
    if v in ("1", "true", "yes", "y", "on"):
        return True
    if v in ("0", "false", "no", "n", "off"):
        return False
    return None


def _parse_int_param(val: str | None):
    if val is None or val.strip() == "":
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _parse_time_param(val: str | None):
    """
    Expect "HH:MM". Return datetime.time or None.
    """
    if not val:
        return None
    from datetime import time
    try:
        hour, minute = map(int, val.split(":"))
        return time(hour, minute)
    except Exception:
        return None


def _parse_list_param(val: str | None):
    """
    Parse comma-separated string into lowercase-trimmed list.
    "cooking, cleaning" -> ["cooking","cleaning"]
    """
    if not val:
        return []
    return [p.strip().lower() for p in val.split(",") if p.strip()]


# ---------- 1. Filter HELPERS ----------

@csrf_exempt
def filter_helpers_view(request):
    """
    GET /filter/helpers/?city=Kolkata&services=cooking,cleaning&frequency=monthly&from_time=09:00&to_time=15:00&min_experience=2&active=true

    Allowed user types:
      - "user"
      - "helper"
      - "admin"

    Filters (all optional):
      - city: exact match
      - area: exact match
      - services: comma-separated slugs, helper.services must contain ALL of them
      - frequency: "one_time", "weekly", "monthly", etc. -> helper.frequency_modes must contain it
      - from_time / to_time: helper availability must fully cover this window
      - min_experience: helper.experience_years >= this
      - active: true/false (default: true if omitted)
    """
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    user, error_response = _require_auth(request, allowed_types={"user", "helper", "admin"})
    if error_response:
        return error_response

    city = request.GET.get("city")
    area = request.GET.get("area")
    services_param = request.GET.get("services")
    frequency = request.GET.get("frequency")
    from_time_param = request.GET.get("from_time")
    to_time_param = request.GET.get("to_time")
    min_experience_param = request.GET.get("min_experience")
    active_param = request.GET.get("active")

    services = _parse_list_param(services_param)
    from_time = _parse_time_param(from_time_param)
    to_time = _parse_time_param(to_time_param)
    min_experience = _parse_int_param(min_experience_param)
    active = _parse_bool_param(active_param)

    qs = HelperProfile.objects.filter(user__user_type="helper").select_related("user")

    # default active=true if not provided
    if active is None:
        qs = qs.filter(active=True)
    else:
        qs = qs.filter(active=active)

    if city:
        qs = qs.filter(city__iexact=city.strip())
    if area:
        qs = qs.filter(area__iexact=area.strip())

    if services:
        # helper must support ALL requested services
        qs = qs.filter(services__contains=services)

    if frequency:
        qs = qs.filter(frequency_modes__contains=[frequency.strip().lower()])

    if from_time and to_time:
        qs = qs.filter(
            available_from__lte=from_time,
            available_to__gte=to_time,
        )
    elif from_time:
        qs = qs.filter(available_from__lte=from_time)
    elif to_time:
        qs = qs.filter(available_to__gte=to_time)

    if min_experience is not None:
        qs = qs.filter(experience_years__gte=min_experience)

    qs = qs[:50]

    results = []
    for hp in qs:
        helper_user = hp.user
        try:
            profile_obj = helper_user.profile
        except UserProfile.DoesNotExist:
            profile_obj = None

        results.append(
            {
                "helper": _user_public_dict(helper_user),
                "profile": _profile_dict_or_none(profile_obj),
                "helper_profile": _helper_profile_to_dict(hp),
            }
        )

    return JsonResponse(
        {
            "filters": {
                "city": city,
                "area": area,
                "services": services,
                "frequency": frequency,
                "from_time": from_time_param,
                "to_time": to_time_param,
                "min_experience": min_experience,
                "active": active if active is not None else True,
            },
            "results": results,
        },
        status=200,
    )


# ---------- 2. Filter SEEKERS ----------

@csrf_exempt
def filter_seekers_view(request):
    """
    GET /filter/seekers/?city=Kolkata&services=cooking,cleaning&frequency=monthly&from_time=09:00&to_time=15:00

    Allowed user types:
      - "helper"
      - "admin"
      - "user" (if you want seekers to see other seekers too; adjust allowed_types as needed)

    Filters (all optional):
      - city: exact
      - area: exact
      - services: comma-separated slugs, seeker.required_services must contain ALL of them
      - frequency: exact match
      - from_time / to_time: seeker window must be inside provided window (or intersect, depending on taste)
    """
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    user, error_response = _require_auth(request, allowed_types={"helper", "admin", "user"})
    if error_response:
        return error_response

    city = request.GET.get("city")
    area = request.GET.get("area")
    services_param = request.GET.get("services")
    frequency = request.GET.get("frequency")
    from_time_param = request.GET.get("from_time")
    to_time_param = request.GET.get("to_time")

    services = _parse_list_param(services_param)
    from_time = _parse_time_param(from_time_param)
    to_time = _parse_time_param(to_time_param)

    qs = SeekerPreferences.objects.filter(user__user_type="user").select_related("user")

    if city:
        qs = qs.filter(city__iexact=city.strip())
    if area:
        qs = qs.filter(area__iexact=area.strip())

    if services:
        qs = qs.filter(required_services__contains=services)

    if frequency:
        qs = qs.filter(frequency__iexact=frequency.strip())

    # You can tweak this logic; here we require seeker window to be within the filter window if both provided
    if from_time and to_time:
        qs = qs.filter(from_time__gte=from_time, to_time__lte=to_time)
    elif from_time:
        qs = qs.filter(from_time__gte=from_time)
    elif to_time:
        qs = qs.filter(to_time__lte=to_time)

    qs = qs[:50]

    results = []
    for prefs in qs:
        seeker_user = prefs.user
        try:
            profile_obj = seeker_user.profile
        except UserProfile.DoesNotExist:
            profile_obj = None

        results.append(
            {
                "seeker": _user_public_dict(seeker_user),
                "profile": _profile_dict_or_none(profile_obj),
                "seeker_preferences": _seeker_prefs_to_dict(prefs),
            }
        )

    return JsonResponse(
        {
            "filters": {
                "city": city,
                "area": area,
                "services": services,
                "frequency": frequency,
                "from_time": from_time_param,
                "to_time": to_time_param,
            },
            "results": results,
        },
        status=200,
    )
