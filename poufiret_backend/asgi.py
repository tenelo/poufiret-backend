"""ASGI : route le HTTP (REST) et le WebSocket (chat temps réel)."""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'poufiret_backend.settings')

from django.core.asgi import get_asgi_application
django_asgi_app = get_asgi_application()  # initialise Django avant les imports Channels

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from apps.core.ws_auth import JWTAuthMiddleware
from apps.messaging.routing import websocket_urlpatterns as ws_messaging
from apps.livraison.routing import websocket_urlpatterns as ws_livraison

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AllowedHostsOriginValidator(
        JWTAuthMiddleware(URLRouter(ws_messaging + ws_livraison))
    ),
})
