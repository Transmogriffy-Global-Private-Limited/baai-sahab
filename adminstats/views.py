from datetime import timedelta

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from customauth.token_utils import decrypt_and_decode_token
from customauth.models import User
from userprofile.models import HelperProfile, SeekerPreferences


# ---------- common helpers ----------

def _get_bearer_token(request):
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip() or None


def _require_admin(request):
    """
    Auth helper: require a valid token AND user_type == 'admin'.
    Returns (user, error_response or None).
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

    if user.user_type != "admin":
        return None, JsonResponse(
            {"detail": "Forbidden: admin access only", "user_type": user.user_type},
            status=403,
        )

    return user, None


def _parse_int(val, default):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


# ---------- 1. Seekers per service ----------

@csrf_exempt
def seekers_per_service_view(request):
    """
    GET /adminstats/seekers-per-service/

    Returns counts per service slug,
    including slugs with 0 seekers.
    """
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    admin, err = _require_admin(request)
    if err:
        return err

    # --- 1. Load all services ---
    all_services = list(Service.objects.values_list("slug", flat=True))

    # Initialize all entries with 0
    per_service = {slug: 0 for slug in all_services}

    # --- 2. Load all seeker preferences ---
    prefs_qs = SeekerPreferences.objects.select_related("user").filter(
        user__user_type="user"
    )

    total_seekers_with_prefs = prefs_qs.count()

    # --- 3. Count how many seekers require each service ---
    for prefs in prefs_qs:
        for service_slug in prefs.required_services or []:
            if service_slug in per_service:
                per_service[service_slug] += 1
            # If unknown slugs appear in DB, we ignore them silently.

    return JsonResponse(
        {
            "total_seekers_with_prefs": total_seekers_with_prefs,
            "per_service": per_service,
        },
        status=200,
    )

# ---------- 2. Summary counts ----------

@csrf_exempt
def summary_counts_view(request):
    """
    GET /adminstats/summary/

    Returns:
    {
      "total_helpers": N,
      "total_seekers": M,
      "total_active_helpers": K
    }
    """
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    admin, err = _require_admin(request)
    if err:
        return err

    total_helpers = User.objects.filter(user_type="helper").count()
    total_seekers = User.objects.filter(user_type="user").count()
    total_active_helpers = HelperProfile.objects.filter(
        user__user_type="helper",
        active=True,
    ).count()

    return JsonResponse(
        {
            "total_helpers": total_helpers,
            "total_seekers": total_seekers,
            "total_active_helpers": total_active_helpers,
        },
        status=200,
    )


# ---------- 3. Registrations in last X days ----------

@csrf_exempt
def registrations_stats_view(request):
    """
    GET /adminstats/registrations/?days=7

    Returns counts of new users in the last X days, broken down by type:

    {
      "days": 7,
      "from": "2025-12-01T00:00:00Z",
      "to":   "2025-12-08T00:00:00Z",
      "counts": {
        "helpers": 5,
        "seekers": 12,
        "total": 17
      }
    }

    Assumes User has a 'created_at' DateTimeField (auto_now_add=True).
    """
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    admin, err = _require_admin(request)
    if err:
        return err

    days = _parse_int(request.GET.get("days"), 7)
    if days <= 0:
        days = 7

    now = timezone.now()
    since = now - timedelta(days=days)

    # filter by created_at >= since
    recent_users = User.objects.filter(created_at__gte=since)

    helpers = recent_users.filter(user_type="helper").count()
    seekers = recent_users.filter(user_type="user").count()
    total = recent_users.count()

    return JsonResponse(
        {
            "days": days,
            "from": since.isoformat(),
            "to": now.isoformat(),
            "counts": {
                "helpers": helpers,
                "seekers": seekers,
                "total": total,
            },
        },
        status=200,
    )
