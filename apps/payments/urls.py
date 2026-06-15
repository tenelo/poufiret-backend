"""Routes Paiement (préfixées /api/v1/payments/)."""
from django.urls import path
from .views import PaiementsView, ValiderPaiementView

urlpatterns = [
    path('paiements/', PaiementsView.as_view(), name='paiements'),
    path('paiements/<uuid:pk>/valider/', ValiderPaiementView.as_view(), name='paiement-valider'),
]
