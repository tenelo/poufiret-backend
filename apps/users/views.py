"""
Vues de l'app users : authentification JWT et profil.
"""
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import (
    ConnexionSerializer, UtilisateurSerializer, LogoutSerializer, InscriptionSerializer,
)


def _ip_client(request):
    """Récupère l'IP réelle, en tenant compte d'un éventuel proxy (Nginx)."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


class ConnexionView(TokenObtainPairView):
    """POST /auth/connexion/ — login par téléphone + mot de passe.
    Enregistre aussi une SessionAppareil (traçabilité + déconnexion ciblée)."""
    serializer_class = ConnexionSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            from .models import User, SessionAppareil
            tel = request.data.get('telephone')
            user = User.objects.filter(telephone=tel).first()
            if user:
                appareil_id = request.data.get('appareil_id', '')
                defaults = {
                    'appareil_nom': request.data.get('appareil_nom', ''),
                    'plateforme': request.data.get('plateforme',
                                                    SessionAppareil.Plateforme.AUTRE),
                    'adresse_ip': _ip_client(request),
                    'est_active': True,
                }
                if appareil_id:
                    SessionAppareil.objects.update_or_create(
                        user=user, appareil_id=appareil_id, defaults=defaults,
                    )
                else:
                    SessionAppareil.objects.create(user=user, **defaults)
        return response


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


class InscriptionView(generics.CreateAPIView):
    """POST /auth/inscription/ — créer un compte (client). Public."""
    serializer_class = InscriptionSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'utilisateur': UtilisateurSerializer(user).data,
        }, status=status.HTTP_201_CREATED)
