"""Routes panier (préfixées /api/v1/orders/)."""
from django.urls import path
from .views import (MesPaniersView, AjouterLigneView, LigneDetailView, ViderPanierView)

urlpatterns = [
    path('paniers/', MesPaniersView.as_view(), name='paniers'),
    path('paniers/ajouter/', AjouterLigneView.as_view(), name='panier-ajouter'),
    path('paniers/<int:pk>/', ViderPanierView.as_view(), name='panier-vider'),
    path('lignes/<int:pk>/', LigneDetailView.as_view(), name='ligne-detail'),
]
