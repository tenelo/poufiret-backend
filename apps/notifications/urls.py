"""Routes notifications (préfixées /api/v1/notifications/)."""
from django.urls import path

from .views import (
    EnregistrerTokenFCMView, NotificationAdminLireView,
    NotificationsAdminCompteurView, NotificationsAdminListView,
    NotificationsAdminToutLireView,
)
from .views_push_web import AbonnementPushWebView, ClePubliquePushWebView, TestPushWebView

urlpatterns = [
    path('token/', EnregistrerTokenFCMView.as_view(), name='fcm-token'),
    path('admin/', NotificationsAdminListView.as_view(), name='admin-liste'),
    path('admin/compteur/', NotificationsAdminCompteurView.as_view(), name='admin-compteur'),
    path('admin/tout-lire/', NotificationsAdminToutLireView.as_view(), name='admin-tout-lire'),
    path('admin/<int:pk>/lire/', NotificationAdminLireView.as_view(), name='admin-lire'),
    # Web Push de l'admin web (admins et partenaires)
    path('push-web/cle-publique/', ClePubliquePushWebView.as_view(), name='push-web-cle-publique'),
    path('push-web/abonnement/', AbonnementPushWebView.as_view(), name='push-web-abonnement'),
    path('push-web/test/', TestPushWebView.as_view(), name='push-web-test'),
]
