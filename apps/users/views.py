"""
Vues de l'app users : authentification JWT et profil.
"""
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import (
    ConnexionSerializer, UtilisateurSerializer, LogoutSerializer,
)


class ConnexionView(TokenObtainPairView):
    """POST /auth/connexion/ — login par téléphone + mot de passe."""
    serializer_class = ConnexionSerializer


class DeconnexionView(APIView):
    """POST /auth/deconnexion/ — blackliste le refresh token."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {'message': 'Déconnexion réussie.'},
            status=status.HTTP_200_OK,
        )


class MonProfilView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /auth/moi/ — consulter ou modifier son profil."""
    serializer_class = UtilisateurSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user
