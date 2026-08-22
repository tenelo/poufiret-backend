"""Routes Transactions (préfixées /api/v1/orders/)."""
from django.urls import path
from .views import (
    MesPaniersView, AjouterLigneView, LigneDetailView, ViderPanierView,
    ValiderPanierView, MesCommandesClientView, CommandesPartenaireView,
    ResumeCommandesPartenaireView,
    CommandeDetailView, TransitionCommandeView, CommanderLivreurView,
)

urlpatterns = [
    path('paniers/', MesPaniersView.as_view(), name='paniers'),
    path('paniers/ajouter/', AjouterLigneView.as_view(), name='panier-ajouter'),
    path('paniers/<int:pk>/valider/', ValiderPanierView.as_view(), name='panier-valider'),
    path('paniers/<int:pk>/', ViderPanierView.as_view(), name='panier-vider'),
    path('lignes/<int:pk>/', LigneDetailView.as_view(), name='ligne-detail'),
    path('commandes/', MesCommandesClientView.as_view(), name='commandes'),
    path('commandes/partenaire/', CommandesPartenaireView.as_view(), name='commandes-partenaire'),
    path('commandes/partenaire/resume/', ResumeCommandesPartenaireView.as_view(),
         name='commandes-partenaire-resume'),
    path('commandes/<int:pk>/', CommandeDetailView.as_view(), name='commande-detail'),
    path('commandes/<int:pk>/transition/', TransitionCommandeView.as_view(), name='commande-transition'),
    path('commandes/<int:pk>/livreur/', CommanderLivreurView.as_view(), name='commande-livreur'),
]
