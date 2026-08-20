from django.urls import path

from .views import (DashboardG5View, AppareilsExportView, ModerationView,
                    JournalModerationView, JournalExportView,
                    IndicateursPartenairesView, PartenairesExportView,
                    FaveurView, FaveurPubliciteView,
                    DemandesPartenariatView, MesPermissionsView,
                    ChangerFormulePubliciteView, RecherchePartenairesView,
                    CreditsPartenaireView, CreditDetailView,
                    RechercheComptesView, AdminsListView,
                    CreerAdminView, AdminDetailView)

app_name = 'administration'

urlpatterns = [
    path('mes-permissions/', MesPermissionsView.as_view(), name='mes-permissions'),
    path('dashboard/', DashboardG5View.as_view(), name='dashboard'),
    path('appareils/export/', AppareilsExportView.as_view(), name='appareils-export'),
    path('moderation/', ModerationView.as_view(), name='moderation'),
    path('moderation/journal/', JournalModerationView.as_view(), name='moderation-journal'),
    path('moderation/journal/export/', JournalExportView.as_view(), name='moderation-journal-export'),
    path('partenaires/', IndicateursPartenairesView.as_view(), name='partenaires'),
    path('partenaires/export/', PartenairesExportView.as_view(), name='partenaires-export'),
    path('partenaires/<int:pk>/faveur/', FaveurView.as_view(), name='partenaire-faveur'),
    path('publicites/<uuid:pk>/faveur/', FaveurPubliciteView.as_view(), name='publicite-faveur'),
    path('publicites/<uuid:pk>/formule/', ChangerFormulePubliciteView.as_view(), name='publicite-formule'),
    path('partenaires/recherche/', RecherchePartenairesView.as_view(), name='partenaires-recherche'),
    path('partenaires/<int:pk>/credits/', CreditsPartenaireView.as_view(), name='partenaire-credits'),
    path('credits/<uuid:pk>/', CreditDetailView.as_view(), name='credit-detail'),
    path('comptes/recherche/', RechercheComptesView.as_view(), name='comptes-recherche'),
    path('admins/', AdminsListView.as_view(), name='admins-liste'),
    path('admins/creer/', CreerAdminView.as_view(), name='admins-creer'),
    path('admins/<int:pk>/', AdminDetailView.as_view(), name='admin-detail'),
    path('demandes-partenariat/', DemandesPartenariatView.as_view(), name='demandes-partenariat'),
]
