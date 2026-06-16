"""Routes notifications (préfixées /api/v1/notifications/)."""
from django.urls import path
from .views import EnregistrerTokenFCMView

urlpatterns = [
    path('token/', EnregistrerTokenFCMView.as_view(), name='fcm-token'),
]
