from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q, F
from django.db.models.functions import Greatest
from django.contrib.postgres.search import TrigramSimilarity

from customauth.token_utils import decrypt_and_decode_token
from userprofile.models import UserProfile, HelperProfile, SeekerPreferences


# ---------- common helpers ----------

def _get_bearer_token(request):
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip() or None


def _require_auth(request, allowed_types=None):
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


# ---------- 1. Seeker searching HELPERS (fuzzy) ----------

@csrf_exempt
def search_helpers_view(request):
    """
    GET /search/helpers/?q=Anu%20Kolkata

    - Allowed user types: "user", "admin"
    - Typo-tolerant fuzzy match using trigram similarity
    - We compute a similarity score across:
        - user.name
        - profile.display_name
        - helper_profile.city
        - helper_profile.area
      and sort by highest score.
    """
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    user, error_response = _require_auth(request, allowed_types={"user", "admin"})
    if error_response:
        return error_response

    raw_q = (request.GET.get("q") or "").strip()
    if not raw_q:
        return JsonResponse(
            {"detail": "q is required", "results": []},
            status=400,
        )

    # Base queryset: active helpers only
    qs = (
        HelperProfile.objects.filter(
            user__user_type="helper",
            active=True,
        )
        .select_related("user")
        .prefetch_related("user__profile")
    )

    # Annotate with similarity across multiple fields
    # If there is no profile, TrigramSimilarity on NULL becomes 0.
    qs = qs.annotate(
        sim_name=TrigramSimilarity("user__name", raw_q),
        sim_display_name=TrigramSimilarity("user__profile__display_name", raw_q),
        sim_city=TrigramSimilarity("city", raw_q),
        sim_area=TrigramSimilarity("area", raw_q),
    ).annotate(
        similarity=Greatest(
            F("sim_name"),
            F("sim_display_name"),
            F("sim_city"),
            F("sim_area"),
        )
    )

    # Filter out very low-similarity matches (tune threshold as needed)
    qs = qs.filter(similarity__gt=0.2).order_by("-similarity")[:50]

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
                "similarity": float(hp.similarity),
            }
        )

    return JsonResponse(
        {
            "query": raw_q,
            "results": results,
        },
        status=200,
    )


# ---------- 2. Helper searching SEEKERS (fuzzy) ----------

@csrf_exempt
def search_seekers_view(request):
    """
    GET /search/seekers/?q=Something

    - Allowed user types: "helper", "admin"
    - Fuzzy search on seekers by:
        - user.name
        - profile.display_name
        - seeker_prefs.city
        - seeker_prefs.area
    """
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    user, error_response = _require_auth(request, allowed_types={"helper", "admin"})
    if error_response:
        return error_response

    raw_q = (request.GET.get("q") or "").strip()
    if not raw_q:
        return JsonResponse(
            {"detail": "q is required", "results": []},
            status=400,
        )

    qs = (
        SeekerPreferences.objects.filter(
            user__user_type="user",
        )
        .select_related("user")
        .prefetch_related("user__profile")
    )

    qs = qs.annotate(
        sim_name=TrigramSimilarity("user__name", raw_q),
        sim_display_name=TrigramSimilarity("user__profile__display_name", raw_q),
        sim_city=TrigramSimilarity("city", raw_q),
        sim_area=TrigramSimilarity("area", raw_q),
    ).annotate(
        similarity=Greatest(
            F("sim_name"),
            F("sim_display_name"),
            F("sim_city"),
            F("sim_area"),
        )
    )

    qs = qs.filter(similarity__gt=0.2).order_by("-similarity")[:50]

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
                "similarity": float(prefs.similarity),
            }
        )

    return JsonResponse(
        {
            "query": raw_q,
            "results": results,
        },
        status=200,
    )
