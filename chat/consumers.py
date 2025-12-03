import json
from urllib.parse import parse_qs

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

from customauth.token_utils import decrypt_and_decode_token


@database_sync_to_async
def _auth_from_token(token: str):
    # returns (user, session, error)
    return decrypt_and_decode_token(token)


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # token from query string: ws://.../ws/chat/?token=...
        query_string = self.scope.get("query_string", b"").decode()
        params = parse_qs(query_string)
        token = params.get("token", [None])[0]

        if not token:
            await self.close(code=4001)
            return

        user, session, error = await _auth_from_token(token)
        if error is not None or user is None:
            await self.close(code=4003)
            return

        self.user = user
        self.group_name = f"user_{self.user.id}"

        # Join group for this user (all devices/tabs with this user)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # optional: send ack
        await self.send(
            text_data=json.dumps({"type": "connection", "status": "ok"})
        )

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(
                self.group_name, self.channel_name
            )

    async def receive(self, text_data=None, bytes_data=None):
        # For now, ignore client->server messages via WS,
        # we use HTTP API to create/edit/delete messages.
        # You can later support "typing", "ping", etc.
        pass

    async def chat_message(self, event):
        """
        Handler for group_send(type="chat.message", message=payload)
        """
        await self.send(text_data=json.dumps(event["message"]))
