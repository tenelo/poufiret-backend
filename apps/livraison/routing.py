"""Routage WebSocket du positionnement livreur."""
from django.urls import re_path
from .consumers import PositionCourseConsumer

websocket_urlpatterns = [
    re_path(r'^ws/course/(?P<course_id>[0-9a-f-]+)/position/$',
            PositionCourseConsumer.as_asgi()),
]
