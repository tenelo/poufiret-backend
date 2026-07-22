from django.urls import path

from .views import (DemarrerSessionView, EngagementAdminView, OuvertureDemandeInterventionView, PingSessionView, VisiteCategorieView, VueVitrineView)

app_name = 'analytics'

urlpatterns = [
    path('session/demarrer/', DemarrerSessionView.as_view(), name='session-demarrer'),
    path('session/ping/', PingSessionView.as_view(), name='session-ping'),
    path('categorie/visite/', VisiteCategorieView.as_view(), name='categorie-visite'),
    path('vitrine/vue/', VueVitrineView.as_view(), name='vitrine-vue'),
    path('intervention/ouverture/', OuvertureDemandeInterventionView.as_view(), name='intervention-ouverture'),
    path('admin/engagement/', EngagementAdminView.as_view(), name='admin-engagement'),
]
