"""Routage WebSocket des notifications admin (compteurs temps réel)."""
from django.urls import re_path

from .consumers import NotificationsAdminConsumer

websocket_urlpatterns = [
    re_path(r'^ws/notifications/admin/$', NotificationsAdminConsumer.as_asgi()),
]
