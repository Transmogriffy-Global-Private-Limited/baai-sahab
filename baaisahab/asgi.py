# baaisahab/asgi.py
import os

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "baaisahab.settings")

# Set up Django first
django_asgi_app = get_asgi_application()

# Only AFTER settings are configured + Django is ready,
# import anything that touches Django apps/models.
import chat.routing


application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(
            URLRouter(chat.routing.websocket_urlpatterns)
        ),
    }
)
