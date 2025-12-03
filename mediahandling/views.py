import os
import mimetypes

from django.conf import settings
from django.http import JsonResponse, FileResponse, HttpResponseNotFound
from django.views.decorators.csrf import csrf_exempt

from customauth.token_utils import decrypt_and_decode_token
from userprofile.models import UserProfile


# Base upload directory: <BASE_DIR>/baaisahab/uploads/profile_pictures
UPLOAD_BASE = os.path.join(settings.BASE_DIR, "baaisahab", "uploads")
PROFILE_PIC_DIR = os.path.join(UPLOAD_BASE, "profile_pictures")


def _ensure_profile_pic_dir():
    os.makedirs(PROFILE_PIC_DIR, exist_ok=True)


def _get_bearer_token(request):
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip() or None


def _require_auth(request):
    """
    Decode token and return (user, error_response).
    """
    token = _get_bearer_token(request)
    if not token:
        return None, JsonResponse(
            {"detail": "Authorization header with Bearer token required"},
            status=401,
        )

    from customauth.token_utils import decrypt_and_decode_token

    user, session, error = decrypt_and_decode_token(token)
    if error is not None or user is None:
        return None, JsonResponse(
            {"detail": "Invalid or expired token", "error": error},
            status=401,
        )

    return user, None


@csrf_exempt
def upload_profile_picture_view(request):
    """
    POST /media/profile-picture/

    Auth required (any user type).
    Body: multipart/form-data with field "file".

    Behavior:
    - Ensures uploads/profile_pictures/ exists.
    - Saves file as <user_id>.<ext> under that folder.
    - Overwrites any existing file for that user.
    - Updates UserProfile.avatar_url = "/uploads/profile_pictures/<user_id>.<ext>".
    """
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    user, error_response = _require_auth(request)
    if error_response:
        return error_response

    # ensure directory exists
    _ensure_profile_pic_dir()

    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return JsonResponse(
            {"detail": "file is required as multipart/form-data"},
            status=400,
        )

    # determine extension
    _, ext = os.path.splitext(uploaded_file.name)
    ext = (ext or "").lower()
    allowed_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    if ext not in allowed_exts:
        return JsonResponse(
            {"detail": f"Unsupported file type '{ext}'. Allowed: {sorted(allowed_exts)}"},
            status=400,
        )

    # filename = <user_id>.<ext>
    filename = f"{user.id}{ext}"
    file_path = os.path.join(PROFILE_PIC_DIR, filename)

    # write file to disk (overwrite if exists)
    with open(file_path, "wb+") as destination:
        for chunk in uploaded_file.chunks():
            destination.write(chunk)

    # store relative URL path in profile (for FE or future direct serving)
    relative_url = f"/uploads/profile_pictures/{filename}"

    profile, _created = UserProfile.objects.get_or_create(user=user)
    profile.avatar_url = relative_url
    profile.save(update_fields=["avatar_url"])

    return JsonResponse(
        {
            "detail": "Profile picture uploaded successfully",
            "avatar_url": relative_url,
        },
        status=200,
    )


def get_profile_picture_view(request, user_id):
    """
    GET /media/profile-picture/<user_id>/

    Public endpoint: anyone can see the DP.

    Behavior:
    - Looks up UserProfile by user_id.
    - Reads avatar_url to figure out the stored file.
    - Streams the image bytes.
    """
    # get profile
    try:
        profile = UserProfile.objects.select_related("user").get(user_id=user_id)
    except UserProfile.DoesNotExist:
        return HttpResponseNotFound("Profile not found")

    avatar_url = profile.avatar_url or ""
    if not avatar_url.startswith("/uploads/"):
        return HttpResponseNotFound("Profile picture not set")

    # avatar_url is like "/uploads/profile_pictures/<user_id>.<ext>"
    # strip the prefix and map to filesystem path
    rel_path = avatar_url[len("/uploads/") :]  # "profile_pictures/xxx.ext"
    file_path = os.path.join(UPLOAD_BASE, rel_path)

    if not os.path.exists(file_path):
        return HttpResponseNotFound("Profile picture file not found")

    content_type, _ = mimetypes.guess_type(file_path)
    if content_type is None:
        content_type = "application/octet-stream"

    return FileResponse(open(file_path, "rb"), content_type=content_type)
