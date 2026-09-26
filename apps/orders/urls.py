"""Routes Transactions (préfixées /api/v1/orders/)."""
from django.urls import path
from .views import (
    MesPaniersView, AjouterLigneView, LigneDetailView, ViderPanierView,
    ValiderPanierView, MesCommandesClientView, CommandesPartenaireView,
    ResumeCommandesPartenaireView,
    CommandeDetailView, TransitionCommandeView, CommanderLivreurView,
)
from .views_admin import (
    CommandeAdminDetailView, CommandesAdminListView,
    DemanderLivreurAdminView, ExportAdminCommandesView,
    MetaAdminCommandesView, NotesAdminCommandeView, StatsAdminCommandesView,
    TransitionAdminView,
)

urlpatterns = [
    path('admin/meta/', MetaAdminCommandesView.as_view(), name='admin-meta'),
    path('admin/stats/', StatsAdminCommandesView.as_view(), name='admin-stats'),
    path('admin/commandes/export/', ExportAdminCommandesView.as_view(), name='admin-commandes-export'),
    path('admin/commandes/', CommandesAdminListView.as_view(), name='admin-commandes'),
    path('admin/commandes/<int:pk>/', CommandeAdminDetailView.as_view(), name='admin-commande-detail'),
    path('admin/commandes/<int:pk>/transition/', TransitionAdminView.as_view(), name='admin-commande-transition'),
    path('admin/commandes/<int:pk>/demander-livreur/', DemanderLivreurAdminView.as_view(),
         name='admin-commande-demander-livreur'),
    path('admin/commandes/<int:pk>/notes/', NotesAdminCommandeView.as_view(), name='admin-commande-notes'),
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
