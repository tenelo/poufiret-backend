"""
Serializers de l'app users : authentification et profil.
"""
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User


class UtilisateurSerializer(serializers.ModelSerializer):
    """Représentation publique d'un utilisateur (lecture/édition profil)."""
    class Meta:
        model = User
        fields = [
            'id', 'telephone', 'username', 'first_name', 'last_name',
            'role', 'est_verifie', 'langue_preferee', 'token_fcm',
        ]
        read_only_fields = ['id', 'telephone', 'role', 'est_verifie']


class ConnexionSerializer(TokenObtainPairSerializer):
    """
    Connexion par téléphone + mot de passe.
    Retourne access + refresh, enrichis des infos utilisateur.
    """
    def validate(self, attrs):
        data = super().validate(attrs)
        data['utilisateur'] = UtilisateurSerializer(self.user).data
        return data


class LogoutSerializer(serializers.Serializer):
    """Déconnexion volontaire : blackliste le refresh token fourni."""
    refresh = serializers.CharField()

    def save(self, **kwargs):
        try:
            RefreshToken(self.validated_data['refresh']).blacklist()
        except Exception:
            raise serializers.ValidationError(
                {'refresh': 'Token invalide ou déjà expiré.'}
            )
