from django.urls import path

from .views import (DashboardG5View, AppareilsExportView, ModerationView,
                    JournalModerationView, JournalExportView,
                    IndicateursPartenairesView, PartenairesExportView,
                    FaveurView, FaveurPubliciteView)

app_name = 'administration'

urlpatterns = [
    path('dashboard/', DashboardG5View.as_view(), name='dashboard'),
    path('appareils/export/', AppareilsExportView.as_view(), name='appareils-export'),
    path('moderation/', ModerationView.as_view(), name='moderation'),
    path('moderation/journal/', JournalModerationView.as_view(), name='moderation-journal'),
    path('moderation/journal/export/', JournalExportView.as_view(), name='moderation-journal-export'),
    path('partenaires/', IndicateursPartenairesView.as_view(), name='partenaires'),
    path('partenaires/export/', PartenairesExportView.as_view(), name='partenaires-export'),
    path('partenaires/<int:pk>/faveur/', FaveurView.as_view(), name='partenaire-faveur'),
    path('publicites/<uuid:pk>/faveur/', FaveurPubliciteView.as_view(), name='publicite-faveur'),
]
