from django.urls import path

from .views import (DemarrerSessionView, EngagementAdminView, PingSessionView, VisiteCategorieView)

app_name = 'analytics'

urlpatterns = [
    path('session/demarrer/', DemarrerSessionView.as_view(), name='session-demarrer'),
    path('session/ping/', PingSessionView.as_view(), name='session-ping'),
    path('categorie/visite/', VisiteCategorieView.as_view(), name='categorie-visite'),
    path('admin/engagement/', EngagementAdminView.as_view(), name='admin-engagement'),
]
