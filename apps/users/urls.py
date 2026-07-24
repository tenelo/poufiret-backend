"""Routes de l'app users (préfixées /api/v1/auth/)."""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    ConnexionView, DeconnexionView, MonProfilView, InscriptionView,
    MesAppareilsView, RevoquerAppareilView, DevenirPartenaireView, MonProfilPartenaireView, MesCategoriesView, MaCategorieDetailView,
    VitrinePartenaireView,
)

urlpatterns = [
    path('inscription/', InscriptionView.as_view(), name='inscription'),
    path('connexion/', ConnexionView.as_view(), name='connexion'),
    path('rafraichir/', TokenRefreshView.as_view(), name='rafraichir'),
    path('deconnexion/', DeconnexionView.as_view(), name='deconnexion'),
    path('moi/', MonProfilView.as_view(), name='moi'),
    path('devenir-partenaire/', DevenirPartenaireView.as_view(), name='devenir-partenaire'),
    path('mon-profil-partenaire/', MonProfilPartenaireView.as_view(), name='mon-profil-partenaire'),
    path('mes-categories/', MesCategoriesView.as_view(), name='mes-categories'),
    path('mes-categories/<int:pk>/', MaCategorieDetailView.as_view(), name='ma-categorie'),
    path('appareils/', MesAppareilsView.as_view(), name='appareils'),
    path('appareils/<uuid:pk>/revoquer/', RevoquerAppareilView.as_view(), name='appareil-revoquer'),
    path('partenaires/<int:pk>/', VitrinePartenaireView.as_view(), name='vitrine-partenaire'),
]
