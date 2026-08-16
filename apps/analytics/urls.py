from django.urls import path

from .views import (DemarrerSessionView, EngagementAdminView, LivraisonStatsClientView, LivraisonStatsPartenaireView, LivraisonTableauDeBordExportView, LivraisonTableauDeBordView, OuvertureDemandeInterventionView, PingSessionView, StatsConnexionAdminView, StatsConnexionExportView, VisiteCategorieView, VueServiceLivraisonView, VueVitrineView)

app_name = 'analytics'

urlpatterns = [
    path('session/demarrer/', DemarrerSessionView.as_view(), name='session-demarrer'),
    path('session/ping/', PingSessionView.as_view(), name='session-ping'),
    path('categorie/visite/', VisiteCategorieView.as_view(), name='categorie-visite'),
    path('vitrine/vue/', VueVitrineView.as_view(), name='vitrine-vue'),
    path('livraison/vue/', VueServiceLivraisonView.as_view(), name='livraison-vue'),
    path('livraison/client/<int:user_id>/', LivraisonStatsClientView.as_view(), name='livraison-stats-client'),
    path('livraison/partenaire/<int:partenaire_id>/', LivraisonStatsPartenaireView.as_view(), name='livraison-stats-partenaire'),
    path('livraison/tableau-de-bord/', LivraisonTableauDeBordView.as_view(), name='livraison-tableau-de-bord'),
    path('livraison/tableau-de-bord/export/', LivraisonTableauDeBordExportView.as_view(), name='livraison-tableau-de-bord-export'),
    path('intervention/ouverture/', OuvertureDemandeInterventionView.as_view(), name='intervention-ouverture'),
    path('admin/engagement/', EngagementAdminView.as_view(), name='admin-engagement'),
    path('admin/stats-connexion/', StatsConnexionAdminView.as_view(), name='admin-stats-connexion'),
    path('admin/stats-connexion/export/', StatsConnexionExportView.as_view(), name='admin-stats-connexion-export'),
]
