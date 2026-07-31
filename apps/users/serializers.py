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
        fields = ['telephone', 'username', 'first_name', 'last_name', 'password', 'departement', 'tranche_age', 'sexe']
        extra_kwargs = {
            'departement': {'required': False},
            'tranche_age': {'required': False},
            'sexe': {'required': False},
        }

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
    categories = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True,
        help_text="IDs des categories. La premiere devient la principale. "
                  "Si vide, deduite du type_partenaire.",
    )

    class Meta:
        model = ProfilPartenaire
        fields = ['type_partenaire', 'nom_commerce', 'description', 'adresse',
                  'quartier', 'secteur', 'ville', 'departement',
                  'telephone_pro', 'whatsapp', 'email_pro', 'categories']

    def validate_categories(self, ids):
        from apps.catalog.models import Categorie
        if not ids:
            return ids
        existantes = set(Categorie.objects.filter(
            id__in=ids, est_active=True).values_list('id', flat=True))
        inconnues = [i for i in ids if i not in existantes]
        if inconnues:
            raise serializers.ValidationError(
                f'Categories inconnues ou inactives : {inconnues}')
        return ids

    def create(self, validated_data):
        from .models import PlanAbonnement
        categories = validated_data.pop('categories', [])
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
        self._rattacher_categories(profil, categories)
        return profil

    @staticmethod
    def _rattacher_categories(profil, ids):
        """Cree les liens PartenaireCategorie.

        Si aucune categorie choisie, on deduit celle qui declare ce
        type_partenaire (champ Categorie.types_partenaire).
        """
        from apps.catalog.models import Categorie, PartenaireCategorie
        if not ids:
            ids = list(
                Categorie.objects.filter(
                    est_active=True,
                    types_partenaire__contains=profil.type_partenaire,
                ).values_list('id', flat=True)[:1]
            )
        for rang, cid in enumerate(ids):
            PartenaireCategorie.objects.get_or_create(
                partenaire=profil, categorie_id=cid,
                defaults={'est_principale': rang == 0},
            )


class VitrinePartenaireSerializer(serializers.ModelSerializer):
    """Représentation PUBLIQUE d'un partenaire (vitrine côté client).
    Lecture seule. N'expose aucun champ sensible (plan, abonnement, GPS)."""
    nombre_likes = serializers.SerializerMethodField()
    est_like_par_moi = serializers.SerializerMethodField()
    est_favori_par_moi = serializers.SerializerMethodField()
    type_partenaire_libelle = serializers.CharField(
        source='get_type_partenaire_display', read_only=True)

    class Meta:
        model = ProfilPartenaire
        fields = [
            'id', 'nom_commerce', 'type_partenaire', 'type_partenaire_libelle',
            'description', 'logo', 'photo_couverture',
            'adresse', 'quartier', 'secteur', 'ville', 'description_acces',
            'telephone_pro', 'whatsapp', 'email_pro',
            'nombre_likes', 'nb_vues', 'est_like_par_moi', 'est_favori_par_moi',
        ]
        read_only_fields = fields

    def get_nombre_likes(self, obj):
        return obj.likes.count() if hasattr(obj, 'likes') else 0

    def get_est_like_par_moi(self, obj):
        user = self.context['request'].user
        if not user.is_authenticated:
            return False
        return obj.likes.filter(user=user).exists() if hasattr(obj, 'likes') else False

    def get_est_favori_par_moi(self, obj):
        user = self.context['request'].user
        if not user.is_authenticated:
            return False
        return obj.favoris.filter(user=user).exists() if hasattr(obj, 'favoris') else False


class MonProfilPartenaireSerializer(serializers.ModelSerializer):
    """Profil du partenaire connecte : lecture et modification.

    Les champs de controle (statut, visibilite, plan, faveur, badge) sont
    en lecture seule : ils relevent de l'administration, pas du partenaire.
    """
    plan_libelle = serializers.CharField(source='plan.libelle', read_only=True)
    nb_photos_par_article = serializers.IntegerField(
        source='plan.nb_photos_par_article', read_only=True)
    nb_articles_max = serializers.IntegerField(
        source='plan.nb_articles_max', read_only=True)
    type_partenaire_libelle = serializers.CharField(
        source='get_type_partenaire_display', read_only=True)
    statut_libelle = serializers.CharField(
        source='get_statut_display', read_only=True)

    class Meta:
        model = ProfilPartenaire
        fields = [
            'id', 'nom_commerce', 'description', 'logo', 'photo_couverture',
            'type_partenaire', 'type_partenaire_libelle',
            'adresse', 'quartier', 'secteur', 'ville', 'description_acces',
            'telephone_pro', 'whatsapp', 'email_pro',
            # Lecture seule : pilotes par l'administration
            'statut', 'statut_libelle', 'est_visible', 'badge_certifie',
            'est_faveur', 'plan_libelle', 'abonnement_fin', 'nb_vues',
            'nb_photos_par_article', 'nb_articles_max',
        ]
        read_only_fields = [
            'id', 'statut', 'statut_libelle', 'est_visible', 'badge_certifie',
            'est_faveur', 'plan_libelle', 'abonnement_fin', 'nb_vues',
            'type_partenaire_libelle', 'nb_photos_par_article',
            'nb_articles_max',
        ]


class MaCategorieSerializer(serializers.ModelSerializer):
    """Rattachement du partenaire a une categorie, avec son image dediee."""
    categorie_nom = serializers.CharField(source='categorie.nom', read_only=True)
    categorie_slug = serializers.CharField(source='categorie.slug', read_only=True)
    categorie_icone = serializers.CharField(source='categorie.icone', read_only=True)

    class Meta:
        from apps.catalog.models import PartenaireCategorie as _PC
        model = _PC
        fields = ['id', 'categorie', 'categorie_nom', 'categorie_slug',
                  'categorie_icone', 'est_principale', 'image_couverture']
        read_only_fields = ['id', 'categorie', 'est_principale']
