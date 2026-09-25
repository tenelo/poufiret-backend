"""Routes notifications (préfixées /api/v1/notifications/)."""
from django.urls import path

from .views import (
    EnregistrerTokenFCMView, NotificationAdminLireView,
    NotificationsAdminCompteurView, NotificationsAdminListView,
    NotificationsAdminToutLireView,
)

urlpatterns = [
    path('token/', EnregistrerTokenFCMView.as_view(), name='fcm-token'),
    path('admin/', NotificationsAdminListView.as_view(), name='admin-liste'),
    path('admin/compteur/', NotificationsAdminCompteurView.as_view(), name='admin-compteur'),
    path('admin/tout-lire/', NotificationsAdminToutLireView.as_view(), name='admin-tout-lire'),
    path('admin/<int:pk>/lire/', NotificationAdminLireView.as_view(), name='admin-lire'),
]
