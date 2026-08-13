"""Routes de l'app livreurs (prefixees /api/v1/livreurs/)."""
from django.urls import path
from .views import (
    MaPositionView, PositionTranspondeurView, MonStatutView, LivreursProchesView,
)

urlpatterns = [
    path('position/', MaPositionView.as_view(), name='livreur-position'),
    path('position-transpondeur/', PositionTranspondeurView.as_view(),
         name='livreur-position-transpondeur'),
    path('statut/', MonStatutView.as_view(), name='livreur-statut'),
    path('proches/', LivreursProchesView.as_view(), name='livreurs-proches'),
]
