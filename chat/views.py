import json
import os
from datetime import timedelta

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.conf import settings

from customauth.token_utils import decrypt_and_decode_token
from customauth.models import User
from .models import Message
from .utils import broadcast_message


MESSAGE_UPLOAD_DIR = os.path.join(
    settings.BASE_DIR, "baaisahab", "uploads", "messageattachments"
)


def _ensure_message_upload_dir():
    os.makedirs(MESSAGE_UPLOAD_DIR, exist_ok=True)


def _get_bearer_token(request):
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip() or None


def _require_auth(request):
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

    return user, None


def _message_to_dict(message: Message):
    return {
        "id": message.id,
        "from_user": str(message.from_user_id),
        "to_user": str(message.to_user_id),
        "content": message.content,
        "attachments": message.attachments,
        "is_seen": message.is_seen,
        "time_sent": message.time_sent.isoformat() if message.time_sent else None,
        "time_seen": message.time_seen.isoformat() if message.time_seen else None,
        "is_deleted": message.is_deleted,
        "deleted_at": message.deleted_at.isoformat() if message.deleted_at else None,
    }


def _parse_json_body(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return None


# ---------- CREATE message ----------

@csrf_exempt
def create_message_view(request):
    """
    POST /chat/messages/

    Auth: required (any user)

    Content-Type:
        - application/json  (text-only)
        - multipart/form-data (with 'content' and 'to_user_id' and 'attachments[]')

    JSON body:
    {
      "to_user_id": "<uuid>",
      "content": "hello there"
    }
    """
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    user, err = _require_auth(request)
    if err:
        return err

    _ensure_message_upload_dir()

    to_user_id = None
    content = ""

    if request.content_type.startswith("multipart/form-data"):
        to_user_id = request.POST.get("to_user_id")
        content = request.POST.get("content") or ""
    else:
        data = _parse_json_body(request)
        if data is None:
            return JsonResponse({"detail": "Invalid JSON body"}, status=400)
        to_user_id = data.get("to_user_id")
        content = data.get("content") or ""

    if not to_user_id:
        return JsonResponse({"detail": "to_user_id is required"}, status=400)

    try:
        to_user = User.objects.get(id=to_user_id)
    except User.DoesNotExist:
        return JsonResponse({"detail": "Recipient user not found"}, status=404)

    # Create message first (attachments empty)
    message = Message.objects.create(
        from_user=user,
        to_user=to_user,
        content=content,
        attachments=[],
    )

    # Handle attachments from multipart (if any)
    attachments_urls = []
    if request.content_type.startswith("multipart/form-data"):
        files = request.FILES.getlist("attachments")
        for idx, f in enumerate(files, start=1):
            _, ext = os.path.splitext(f.name)
            ext = (ext or "").lower()
            filename = f"{message.id}-{idx}{ext}"
            file_path = os.path.join(MESSAGE_UPLOAD_DIR, filename)

            with open(file_path, "wb+") as dest:
                for chunk in f.chunks():
                    dest.write(chunk)

            rel_url = f"/uploads/messageattachments/{filename}"
            attachments_urls.append(rel_url)

    if attachments_urls:
        message.attachments = attachments_urls
        message.save(update_fields=["attachments"])

    # broadcast via WS
    broadcast_message(message, event_type="message")

    return JsonResponse(_message_to_dict(message), status=201)


# ---------- GET conversation messages ----------

@csrf_exempt
def list_messages_view(request):
    """
    GET /chat/messages/?with_user=<uuid>&page=1&page_size=20

    Returns conversation messages between current user and with_user.
    Excludes deleted messages.
    """
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    user, err = _require_auth(request)
    if err:
        return err

    other_id = request.GET.get("with_user")
    if not other_id:
        return JsonResponse(
            {"detail": "with_user query parameter is required"},
            status=400,
        )

    try:
        _ = User.objects.get(id=other_id)
    except User.DoesNotExist:
        return JsonResponse({"detail": "Other user not found"}, status=404)

    from django.db.models import Q

    page = int(request.GET.get("page", "1") or 1)
    page_size = int(request.GET.get("page_size", "20") or 20)
    if page_size > 100:
        page_size = 100

    qs = Message.objects.filter(
        is_deleted=False,
        (
            Q(from_user=user, to_user_id=other_id)
            | Q(from_user_id=other_id, to_user=user)
        ),
    ).order_by("time_sent")

    total = qs.count()
    start = (page - 1) * page_size
    end = start + page_size

    messages = qs[start:end]

    return JsonResponse(
        {
            "with_user": other_id,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "has_next": end < total,
            },
            "results": [_message_to_dict(m) for m in messages],
        },
        status=200,
    )


# ---------- EDIT message ----------

@csrf_exempt
def edit_message_view(request, message_id: int):
    """
    PATCH /chat/messages/<message_id>/

    Rules:
    - Only sender can edit.
    - Only if NOT seen AND within 15 minutes of time_sent.
    """
    if request.method not in ("PATCH", "PUT"):
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    user, err = _require_auth(request)
    if err:
        return err

    try:
        message = Message.objects.get(id=message_id)
    except Message.DoesNotExist:
        return JsonResponse({"detail": "Message not found"}, status=404)

    if message.from_user_id != user.id:
        return JsonResponse({"detail": "Only sender can edit this message"}, status=403)

    # rule: not seen AND within 15 mins
    now = timezone.now()
    if message.is_seen or (now - message.time_sent) > timedelta(minutes=15):
        return JsonResponse(
            {
                "detail": "Message can no longer be edited (either seen or too old)",
            },
            status=400,
        )

    data = _parse_json_body(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body"}, status=400)

    new_content = data.get("content")
    if new_content is None:
        return JsonResponse({"detail": "content is required"}, status=400)

    message.content = new_content
    message.save(update_fields=["content"])

    broadcast_message(message, event_type="edited")

    return JsonResponse(_message_to_dict(message), status=200)


# ---------- DELETE message ----------

@csrf_exempt
def delete_message_view(request, message_id: int):
    """
    DELETE /chat/messages/<message_id>/

    Rules:
    - Only sender can delete.
    - NOT possible if seen.
    - Soft delete (is_deleted = True).
    """
    if request.method != "DELETE":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    user, err = _require_auth(request)
    if err:
        return err

    try:
        message = Message.objects.get(id=message_id)
    except Message.DoesNotExist:
        return JsonResponse({"detail": "Message not found"}, status=404)

    if message.from_user_id != user.id:
        return JsonResponse({"detail": "Only sender can delete this message"}, status=403)

    if message.is_seen:
        return JsonResponse(
            {"detail": "Message cannot be deleted because it has been seen"},
            status=400,
        )

    message.soft_delete()
    broadcast_message(message, event_type="deleted")

    return JsonResponse(
        {"detail": "Message deleted", "id": message.id},
        status=200,
    )


# ---------- MARK SEEN ----------

@csrf_exempt
def mark_seen_view(request, message_id: int):
    """
    POST /chat/messages/<message_id>/seen/

    Rules:
    - Only recipient can mark seen.
    """
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    user, err = _require_auth(request)
    if err:
        return err

    try:
        message = Message.objects.get(id=message_id)
    except Message.DoesNotExist:
        return JsonResponse({"detail": "Message not found"}, status=404)

    if message.to_user_id != user.id:
        return JsonResponse(
            {"detail": "Only recipient can mark message as seen"}, status=403
        )

    message.mark_seen()
    broadcast_message(message, event_type="seen")

    return JsonResponse(_message_to_dict(message), status=200)

@csrf_exempt
def get_secure_file_view(request):
    """
    GET /chat/secure-file/?path=/uploads/messageattachments/123-1.png

    - 'path' is exactly what is stored in message.attachments
      (e.g. '/uploads/messageattachments/123-1.png')
    - Auth via Bearer token (same as other chat views)
    - Only sender or recipient of the message can access the file
    """
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    user, err = _require_auth(request)
    if err:
        return err

    rel_url = request.GET.get("path")
    if not rel_url:
        return JsonResponse({"detail": "Missing 'path' parameter"}, status=400)

    # Expect URLs starting with /uploads/
    uploads_prefix = "/uploads/"
    if not rel_url.startswith(uploads_prefix):
        return JsonResponse({"detail": "Invalid path"}, status=400)

    # Strip '/uploads/' to get path relative to uploads dir
    # '/uploads/messageattachments/123-1.png' -> 'messageattachments/123-1.png'
    rel_path = rel_url[len(uploads_prefix):]

    # Basic traversal protection
    if ".." in rel_path or rel_path.startswith("/") or rel_path.startswith("\\"):
        return JsonResponse({"detail": "Invalid path"}, status=400)

    base_dir = os.path.join(settings.BASE_DIR, "baaisahab", "uploads")
    abs_path = os.path.join(base_dir, rel_path)

    # Ensure we are still under the uploads root
    if not abs_path.startswith(base_dir):
        return JsonResponse({"detail": "Invalid path"}, status=400)

    if not os.path.exists(abs_path):
        return HttpResponseNotFound("File not found")

    # -------- PERMISSION CHECK: derive message id from filename --------
    filename = os.path.basename(abs_path)
    try:
        # '123-1.png' -> '123'
        msg_id_str = filename.split("-", 1)[0]
        msg_id = int(msg_id_str)
    except Exception:
        return JsonResponse({"detail": "Invalid file naming format"}, status=400)

    try:
        message = Message.objects.get(id=msg_id)
    except Message.DoesNotExist:
        return JsonResponse({"detail": "Message not found"}, status=404)

    # Only sender or recipient can access
    if user.id not in (message.from_user_id, message.to_user_id):
        return JsonResponse({"detail": "Forbidden"}, status=403)

    # -------------------------------------------------------------------

    content_type, _ = mimetypes.guess_type(abs_path)
    if content_type is None:
        content_type = "application/octet-stream"

    return FileResponse(open(abs_path, "rb"), content_type=content_type)
