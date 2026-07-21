"""Serializers du module Catalogue."""
from rest_framework import serializers
from .models import (
    Categorie, Article, ArticleImage, Variante, Supplement,
    Panorama, Logement, Vehicule,
)


class CategorieSerializer(serializers.ModelSerializer):
    enfants = serializers.SerializerMethodField()
    nb_partenaires = serializers.SerializerMethodField()

    class Meta:
        model = Categorie
        fields = ['id', 'nom', 'slug', 'description', 'icone', 'image_couverture',
                  'parent', 'mode_transaction', 'types_articles', 'affiche_catalogue', 'module_flutter', 'ordre',
                  'est_active', 'nb_partenaires', 'enfants']

    def get_nb_partenaires(self, obj):
        a = getattr(obj, 'nb_via_liaison', None)
        b = getattr(obj, 'nb_via_articles', None)
        if a is None and b is None:
            return None  # contexte sans annotation (ex: enfants imbriqués)
        return max(a or 0, b or 0)

    def get_enfants(self, obj):
        e = obj.enfants.filter(est_active=True).order_by('ordre', 'nom')
        return CategorieSerializer(e, many=True, context=self.context).data


class ArticleImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArticleImage
        fields = ['id', 'article', 'image', 'legende', 'ordre', 'est_principale', 'est_active']
        read_only_fields = ['est_active']


class VarianteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Variante
        fields = ['id', 'article', 'nom', 'prix_supplement', 'est_par_defaut', 'ordre', 'est_active']


class SupplementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplement
        fields = ['id', 'article', 'nom', 'prix', 'est_optionnel', 'ordre', 'est_actif']


class PanoramaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Panorama
        fields = ['id', 'article', 'image', 'nom_piece', 'ordre', 'est_active']


class LogementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Logement
        fields = ['id', 'article', 'nb_chambres', 'nb_sdb', 'surface_m2', 'meuble',
                  'duree_min_jours', 'caution', 'equipements']
        read_only_fields = ['article']


class VehiculeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicule
        fields = ['id', 'article', 'marque', 'modele', 'annee', 'kilometrage',
                  'carburant', 'boite_vitesse', 'places', 'mode']
        read_only_fields = ['article']


class ArticleListeSerializer(serializers.ModelSerializer):
    image_principale = serializers.SerializerMethodField()
    partenaire_nom = serializers.CharField(source='partenaire.nom_commerce', read_only=True)

    class Meta:
        model = Article
        fields = ['id', 'nom', 'slug', 'type', 'prix', 'prix_promotion',
                  'est_en_promotion', 'est_disponible', 'nb_vues', 'nb_likes',
                  'partenaire', 'partenaire_nom', 'categorie', 'image_principale']

    def get_image_principale(self, obj):
        img = (obj.images.filter(est_principale=True, est_active=True).first()
               or obj.images.filter(est_active=True).first())
        if img and img.image:
            req = self.context.get('request')
            return req.build_absolute_uri(img.image.url) if req else img.image.url
        return None

class ArticleDetailSerializer(serializers.ModelSerializer):
    images = ArticleImageSerializer(many=True, read_only=True)
    variantes = VarianteSerializer(many=True, read_only=True)
    supplements = SupplementSerializer(many=True, read_only=True)
    panoramas = PanoramaSerializer(many=True, read_only=True)
    logement = LogementSerializer(read_only=True)
    vehicule = VehiculeSerializer(read_only=True)
    partenaire_nom = serializers.CharField(source='partenaire.nom_commerce', read_only=True)
    est_like_par_moi = serializers.SerializerMethodField()
    est_favori_par_moi = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = ['id', 'nom', 'slug', 'description', 'type', 'prix', 'prix_promotion',
                  'unite', 'details', 'est_actif', 'est_disponible', 'est_en_promotion',
                  'temps_preparation_min', 'nb_vues', 'nb_likes', 'nb_commentaires',
                  'nb_favoris', 'partenaire', 'partenaire_nom', 'categorie', 'section_menu',
                  'images', 'variantes', 'supplements', 'panoramas', 'logement', 'vehicule',
                  'est_like_par_moi', 'est_favori_par_moi',
                  'created_at', 'updated_at']
        read_only_fields = ['slug', 'nb_vues', 'nb_likes', 'nb_commentaires',
                            'nb_favoris', 'partenaire']

    def _user(self):
        req = self.context.get('request')
        if req and req.user and req.user.is_authenticated:
            return req.user
        return None

    def get_est_like_par_moi(self, obj):
        user = self._user()
        if user is None:
            return False
        return obj.likes.filter(user=user).exists()

    def get_est_favori_par_moi(self, obj):
        user = self._user()
        if user is None:
            return False
        return obj.favoris.filter(user=user).exists()