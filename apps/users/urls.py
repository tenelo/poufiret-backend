"""
Routes de l'app users (préfixées /api/v1/auth/ par le routeur principal).
"""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import ConnexionView, DeconnexionView, MonProfilView

urlpatterns = [
    path('connexion/', ConnexionView.as_view(), name='connexion'),
    path('rafraichir/', TokenRefreshView.as_view(), name='rafraichir'),
    path('deconnexion/', DeconnexionView.as_view(), name='deconnexion'),
    path('moi/', MonProfilView.as_view(), name='moi'),
]
