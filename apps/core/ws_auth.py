"""Middleware Channels : authentifie une connexion WebSocket via un JWT en query-string.
Usage côté client : ws://host/ws/.../?token=<access_token>
"""
from urllib.parse import parse_qs
from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser


@database_sync_to_async
def _get_user(token):
    from rest_framework_simplejwt.tokens import AccessToken
    from django.contrib.auth import get_user_model
    try:
        data = AccessToken(token)
        return get_user_model().objects.get(id=data['user_id'])
    except Exception:
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        query = parse_qs(scope.get('query_string', b'').decode())
        token = query.get('token', [None])[0]
        scope['user'] = await _get_user(token) if token else AnonymousUser()
        return await super().__call__(scope, receive, send)
