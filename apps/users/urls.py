"""Routes de l'app users (préfixées /api/v1/auth/)."""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    ConnexionView, DeconnexionView, MonProfilView, InscriptionView,
    MesAppareilsView, RevoquerAppareilView, DevenirPartenaireView, MonProfilPartenaireView, MesCategoriesView, MaCategorieDetailView,
    VitrinePartenaireView,
    DemanderOTPView, VerifierOTPView, DefinirPINView, ChangerPINView,
    CreerPartenaireParAdminView,
)

urlpatterns = [
    path('inscription/', InscriptionView.as_view(), name='inscription'),
    path('connexion/', ConnexionView.as_view(), name='connexion'),
    path('otp/demander/', DemanderOTPView.as_view(), name='otp-demander'),
    path('otp/verifier/', VerifierOTPView.as_view(), name='otp-verifier'),
    path('pin/definir/', DefinirPINView.as_view(), name='pin-definir'),
    path('pin/changer/', ChangerPINView.as_view(), name='pin-changer'),
    path('rafraichir/', TokenRefreshView.as_view(), name='rafraichir'),
    path('deconnexion/', DeconnexionView.as_view(), name='deconnexion'),
    path('moi/', MonProfilView.as_view(), name='moi'),
    path('devenir-partenaire/', DevenirPartenaireView.as_view(), name='devenir-partenaire'),
    path('partenaires/creer/', CreerPartenaireParAdminView.as_view(), name='partenaire-creer'),
    path('mon-profil-partenaire/', MonProfilPartenaireView.as_view(), name='mon-profil-partenaire'),
    path('mes-categories/', MesCategoriesView.as_view(), name='mes-categories'),
    path('mes-categories/<int:pk>/', MaCategorieDetailView.as_view(), name='ma-categorie'),
    path('appareils/', MesAppareilsView.as_view(), name='appareils'),
    path('appareils/<uuid:pk>/revoquer/', RevoquerAppareilView.as_view(), name='appareil-revoquer'),
    path('partenaires/<int:pk>/', VitrinePartenaireView.as_view(), name='vitrine-partenaire'),
]
