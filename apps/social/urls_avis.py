"""Routes des avis clients (préfixées /api/v1/avis/)."""
from django.urls import path

from .views_avis import (
    AdminAvisDetailView, AdminAvisListView, AvisCreerView, AvisModifierView, MesAvisView,
    RepondreAvisView,
)

urlpatterns = [
    path('', AvisCreerView.as_view(), name='avis-creer'),
    path('mes-avis/', MesAvisView.as_view(), name='mes-avis'),
    path('admin/', AdminAvisListView.as_view(), name='avis-admin-liste'),
    path('admin/<int:pk>/', AdminAvisDetailView.as_view(), name='avis-admin-detail'),
    path('<int:pk>/', AvisModifierView.as_view(), name='avis-modifier'),
    path('<int:pk>/repondre/', RepondreAvisView.as_view(), name='avis-repondre'),
]
