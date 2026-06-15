"""
Serializers de l'app users : authentification et profil.
"""
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User, SessionAppareil, ProfilPartenaire


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


class InscriptionSerializer(serializers.ModelSerializer):
    """
    Inscription d'un nouvel utilisateur (rôle client par défaut).
    Le passage partenaire se fait via un flux séparé.
    """
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ['telephone', 'username', 'first_name', 'last_name', 'password']

    def validate_password(self, value):
        from django.contrib.auth.password_validation import validate_password
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.role = User.Role.CLIENT
        user.set_password(password)
        user.save()
        return user


class SessionAppareilSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionAppareil
        fields = ['id', 'appareil_nom', 'appareil_id', 'plateforme',
                  'adresse_ip', 'derniere_activite_le', 'est_active', 'cree_le']
        read_only_fields = fields


class DevenirPartenaireSerializer(serializers.ModelSerializer):
    """Crée le ProfilPartenaire d'un client. Rôle partenaire immédiat,
    mais profil EN_ATTENTE + invisible jusqu'à validation admin."""
    class Meta:
        model = ProfilPartenaire
        fields = ['type_partenaire', 'nom_commerce', 'description', 'adresse',
                  'quartier', 'secteur', 'ville', 'telephone_pro', 'whatsapp', 'email_pro']

    def create(self, validated_data):
        from .models import PlanAbonnement
        user = self.context['request'].user
        if hasattr(user, 'profil_partenaire'):
            raise serializers.ValidationError("Vous avez déjà un profil partenaire.")
        plan, _ = PlanAbonnement.objects.get_or_create(
            code='basique', duree_jours=-1,
            defaults={'libelle': 'Basique', 'prix': 0,
                      'nb_articles_max': 10, 'nb_photos_par_article': 1})
        profil = ProfilPartenaire.objects.create(
            user=user, plan=plan,
            statut=ProfilPartenaire.Statut.EN_ATTENTE,
            est_visible=False, **validated_data)
        user.role = User.Role.PARTENAIRE
        user.save(update_fields=['role'])
        return profil
