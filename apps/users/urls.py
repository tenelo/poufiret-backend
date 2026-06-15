"""Routes de l'app users (préfixées /api/v1/auth/)."""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    ConnexionView, DeconnexionView, MonProfilView, InscriptionView,
    MesAppareilsView, RevoquerAppareilView, DevenirPartenaireView,
)

urlpatterns = [
    path('inscription/', InscriptionView.as_view(), name='inscription'),
    path('connexion/', ConnexionView.as_view(), name='connexion'),
    path('rafraichir/', TokenRefreshView.as_view(), name='rafraichir'),
    path('deconnexion/', DeconnexionView.as_view(), name='deconnexion'),
    path('moi/', MonProfilView.as_view(), name='moi'),
    path('devenir-partenaire/', DevenirPartenaireView.as_view(), name='devenir-partenaire'),
    path('appareils/', MesAppareilsView.as_view(), name='appareils'),
    path('appareils/<uuid:pk>/revoquer/', RevoquerAppareilView.as_view(), name='appareil-revoquer'),
]
