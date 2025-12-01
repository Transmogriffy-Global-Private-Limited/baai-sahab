import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from customauth.token_utils import decrypt_and_decode_token
from .models import (
    UserProfile,
    Service,
    HelperProfile,
    SeekerPreferences,
)


# ---------- common helpers ----------

def _json_body(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return None


def _get_bearer_token(request):
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip() or None


def _require_auth(request, allowed_types=None):
    """
    Decode token, return (user, error_response).

    allowed_types: list/set of user_type strings, e.g. ["admin"].
    If user_type not allowed -> 403.
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

    if allowed_types is not None:
        if user.user_type not in allowed_types:
            return None, JsonResponse(
                {"detail": "Forbidden: insufficient role", "user_type": user.user_type},
                status=403,
            )

    return user, None


def _service_to_dict(service: Service):
    return {
        "id": str(service.id),
        "slug": service.slug,
        "name": service.name,
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
        "available_for_work": prefs.available_for_work,
        "created_at": prefs.created_at.isoformat() if prefs.created_at else None,
        "updated_at": prefs.updated_at.isoformat() if prefs.updated_at else None,
    }


# ---------- ADMIN: add/remove services ----------

@csrf_exempt
def admin_services_view(request):
    """
    Admin-only endpoint for managing Service catalog.

    POST /profile/admin/services/
    Body:
    {
      "slug": "cooking",
      "name": "Cooking"
    }

    DELETE /profile/admin/services/
    Body:
    {
      "slug": "cooking"
    }
    """
    user, error_response = _require_auth(request, allowed_types={"admin"})
    if error_response:
        return error_response

    if request.method == "POST":
        data = _json_body(request)
        if data is None:
            return JsonResponse({"detail": "Invalid JSON body"}, status=400)

        slug = (data.get("slug") or "").strip().lower()
        name = (data.get("name") or "").strip()

        if not slug or not name:
            return JsonResponse(
                {"detail": "slug and name are required"},
                status=400,
            )

        service, created = Service.objects.get_or_create(
            slug=slug,
            defaults={"name": name},
        )
        if not created:
            # update name if already exists
            service.name = name
            service.save(update_fields=["name"])

        return JsonResponse(
            {
                "detail": "Service created/updated",
                "service": _service_to_dict(service),
            },
            status=200,
        )

    if request.method == "DELETE":
        data = _json_body(request)
        if data is None:
            return JsonResponse({"detail": "Invalid JSON body"}, status=400)

        slug = (data.get("slug") or "").strip().lower()
        if not slug:
            return JsonResponse(
                {"detail": "slug is required"},
                status=400,
            )

        try:
            service = Service.objects.get(slug=slug)
        except Service.DoesNotExist:
            return JsonResponse(
                {"detail": "Service not found"},
                status=404,
            )

        service.delete()
        return JsonResponse(
            {"detail": "Service deleted", "slug": slug},
            status=200,
        )

    return JsonResponse({"detail": "Method not allowed"}, status=405)


# ---------- HELPER CAPABILITY: add/edit ----------

@csrf_exempt
def helper_profile_view(request):
    """
    Helper capability add/edit.

    Requires:
    - user.user_type == "helper"

    GET /profile/helper/
      -> returns current helper capability (auto-creates empty? no, 404 if missing)

    POST /profile/helper/
    Body (example):
    {
      "services": ["cooking", "cleaning"],
      "city": "Kolkata",
      "area": "Salt Lake",
      "available_from": "09:00",
      "available_to": "15:00",
      "frequency_modes": ["one_time", "monthly"],
      "experience_years": 3,
      "active": true
    }
    """
    user, error_response = _require_auth(request, allowed_types={"helper"})
    if error_response:
        return error_response

    if request.method == "GET":
        try:
            hp = HelperProfile.objects.get(user=user)
        except HelperProfile.DoesNotExist:
            return JsonResponse(
                {"detail": "Helper profile not found"},
                status=404,
            )

        return JsonResponse(
            {"helper_profile": _helper_profile_to_dict(hp)},
            status=200,
        )

    if request.method == "POST":
        data = _json_body(request)
        if data is None:
            return JsonResponse({"detail": "Invalid JSON body"}, status=400)

        services = data.get("services")
        city = data.get("city")
        area = data.get("area")
        available_from = data.get("available_from")
        available_to = data.get("available_to")
        frequency_modes = data.get("frequency_modes")
        experience_years = data.get("experience_years")
        active = data.get("active")

        # basic validation
        if not isinstance(services, list) or not services:
            return JsonResponse(
                {"detail": "services must be a non-empty list of slugs"},
                status=400,
            )

        if not city or not available_from or not available_to:
            return JsonResponse(
                {"detail": "city, available_from, available_to are required"},
                status=400,
            )

        if not isinstance(frequency_modes, list) or not frequency_modes:
            return JsonResponse(
                {"detail": "frequency_modes must be a non-empty list"},
                status=400,
            )

        from datetime import time

        def _parse_time(value):
            try:
                hour, minute = map(int, value.split(":"))
                return time(hour, minute)
            except Exception:
                return None

        from_t = _parse_time(available_from)
        to_t = _parse_time(available_to)
        if from_t is None or to_t is None:
            return JsonResponse(
                {"detail": "available_from and available_to must be HH:MM"},
                status=400,
            )

        hp, _created = HelperProfile.objects.get_or_create(user=user)

        hp.services = [str(s).strip().lower() for s in services]
        hp.city = str(city).strip()
        hp.area = str(area).strip() if area else ""
        hp.available_from = from_t
        hp.available_to = to_t
        hp.frequency_modes = [str(f).strip().lower() for f in frequency_modes]
        hp.experience_years = int(experience_years) if experience_years is not None else hp.experience_years
        if active is not None:
            hp.active = bool(active)

        hp.save()

        return JsonResponse(
            {"helper_profile": _helper_profile_to_dict(hp)},
            status=200,
        )

    return JsonResponse({"detail": "Method not allowed"}, status=405)


# ---------- SEEKER REQUIREMENTS: add/edit ----------

@csrf_exempt
def seeker_prefs_view(request):
    """
    Seeker requirements/preferences add/edit.

    Requires:
    - user.user_type == "user"

    GET /profile/seeker/
      -> returns current seeker preferences (404 if none)

    POST /profile/seeker/
    Body (example):
    {
      "required_services": ["cooking", "cleaning"],
      "city": "Kolkata",
      "area": "Salt Lake",
      "from_time": "09:00",
      "to_time": "15:00",
      "frequency": "monthly",
      "available_for_work": true
    }
    """
    user, error_response = _require_auth(request, allowed_types={"user"})
    if error_response:
        return error_response

    if request.method == "GET":
        try:
            prefs = SeekerPreferences.objects.get(user=user)
        except SeekerPreferences.DoesNotExist:
            return JsonResponse(
                {"detail": "Seeker preferences not found"},
                status=404,
            )

        return JsonResponse(
            {"seeker_preferences": _seeker_prefs_to_dict(prefs)},
            status=200,
        )

    if request.method == "POST":
        data = _json_body(request)
        if data is None:
            return JsonResponse({"detail": "Invalid JSON body"}, status=400)

        required_services = data.get("required_services")
        city = data.get("city")
        area = data.get("area")
        from_time = data.get("from_time")
        to_time = data.get("to_time")
        frequency = data.get("frequency")
        available_for_work = data.get("available_for_work")

        if not isinstance(required_services, list) or not required_services:
            return JsonResponse(
                {"detail": "required_services must be a non-empty list of slugs"},
                status=400,
            )

        if not city or not from_time or not to_time or not frequency:
            return JsonResponse(
                {"detail": "city, from_time, to_time, and frequency are required"},
                status=400,
            )

        from datetime import time

        def _parse_time(value):
            try:
                hour, minute = map(int, value.split(":"))
                return time(hour, minute)
            except Exception:
                return None

        from_t = _parse_time(from_time)
        to_t = _parse_time(to_time)
        if from_t is None or to_t is None:
            return JsonResponse(
                {"detail": "from_time and to_time must be HH:MM"},
                status=400,
            )

        prefs, _created = SeekerPreferences.objects.get_or_create(user=user)

        prefs.required_services = [str(s).strip().lower() for s in required_services]
        prefs.city = str(city).strip()
        prefs.area = str(area).strip() if area else ""
        prefs.from_time = from_t
        prefs.to_time = to_t
        prefs.frequency = str(frequency).strip().lower()
        if available_for_work is not None:
            prefs.available_for_work = bool(available_for_work)

        prefs.save()

        return JsonResponse(
            {"seeker_preferences": _seeker_prefs_to_dict(prefs)},
            status=200,
        )

    return JsonResponse({"detail": "Method not allowed"}, status=405)
