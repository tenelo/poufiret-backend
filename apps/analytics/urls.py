from django.urls import path

from .views import DemarrerSessionView, PingSessionView

app_name = 'analytics'

urlpatterns = [
    path('session/demarrer/', DemarrerSessionView.as_view(), name='session-demarrer'),
    path('session/ping/', PingSessionView.as_view(), name='session-ping'),
]
