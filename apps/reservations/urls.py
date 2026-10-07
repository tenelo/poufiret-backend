"""Routes du module reservations (préfixées /api/v1/reservations/)."""
from django.urls import path

from .views import (
    AnnulerDemandeView, CreerDemandeView, MesDemandesView,
    MonEspaceLoueurView, TransitionLoueurView,
)
from .views_admin import (
    DemandeAdminDetailView, DemandesAdminListView, ExportAdminDemandesView,
    MetaAdminDemandesView, NotesAdminDemandeView, TransitionAdminView,
)

app_name = 'reservations'

urlpatterns = [
    # ── Client ──────────────────────────────────────────────────────────
    path('', CreerDemandeView.as_view(), name='creer'),
    path('mes-demandes/', MesDemandesView.as_view(), name='mes-demandes'),
    path('<int:pk>/annuler/', AnnulerDemandeView.as_view(), name='annuler'),

    # ── Loueur ──────────────────────────────────────────────────────────
    path('mon-espace/', MonEspaceLoueurView.as_view(), name='mon-espace'),
    path('<int:pk>/transition/', TransitionLoueurView.as_view(), name='transition-loueur'),

    # ── Admin ───────────────────────────────────────────────────────────
    path('admin/meta/', MetaAdminDemandesView.as_view(), name='admin-meta'),
    path('admin/demandes/export/', ExportAdminDemandesView.as_view(), name='admin-demandes-export'),
    path('admin/demandes/', DemandesAdminListView.as_view(), name='admin-demandes'),
    path('admin/demandes/<int:pk>/', DemandeAdminDetailView.as_view(), name='admin-demande-detail'),
    path('admin/demandes/<int:pk>/transition/', TransitionAdminView.as_view(), name='admin-demande-transition'),
    path('admin/demandes/<int:pk>/notes/', NotesAdminDemandeView.as_view(), name='admin-demande-notes'),
]
