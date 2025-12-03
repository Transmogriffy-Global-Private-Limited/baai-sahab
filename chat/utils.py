from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from .models import Message
from userprofile.models import UserProfile  # if you want avatar, etc.
from customauth.models import User


def _user_public_dict(user: User):
    return {
        "id": str(user.id),
        "name": user.name,
        "phone_number": user.phone_number,
        "user_type": getattr(user, "user_type", None),
    }


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


def broadcast_message(message: Message, event_type: str = "message"):
    """
    Broadcast to all connections of sender + recipient.
    event_type: "message" | "edited" | "deleted" | "seen"
    """
    channel_layer = get_channel_layer()
    payload = {
        "type": event_type,
        "message": _message_to_dict(message),
    }

    for user_id in [message.from_user_id, message.to_user_id]:
        group_name = f"user_{user_id}"
        async_to_sync(channel_layer.group_send)(
            group_name,
            {"type": "chat.message", "message": payload},
        )
