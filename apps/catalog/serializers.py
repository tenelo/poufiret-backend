"""
Serializers du module Catalogue.
"""
from rest_framework import serializers
from .models import Categorie, Article, ArticleImage


class CategorieSerializer(serializers.ModelSerializer):
    """Catégorie, avec ses enfants imbriqués (arborescence)."""
    enfants = serializers.SerializerMethodField()

    class Meta:
        model = Categorie
        fields = [
            'id', 'nom', 'slug', 'description', 'icone', 'image_couverture',
            'parent', 'mode_transaction', 'module_flutter', 'ordre', 'enfants',
        ]

    def get_enfants(self, obj):
        enfants = obj.enfants.filter(est_active=True).order_by('ordre', 'nom')
        return CategorieSerializer(enfants, many=True, context=self.context).data


class ArticleImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArticleImage
        fields = ['id', 'image', 'legende', 'ordre', 'est_principale']


class ArticleListeSerializer(serializers.ModelSerializer):
    """Version légère pour les listes (perf : pas de relations lourdes)."""
    image_principale = serializers.SerializerMethodField()
    partenaire_nom = serializers.CharField(source='partenaire.nom_commerce', read_only=True)

    class Meta:
        model = Article
        fields = [
            'id', 'nom', 'slug', 'type', 'prix', 'prix_promotion',
            'est_en_promotion', 'est_disponible', 'nb_vues', 'nb_likes',
            'partenaire', 'partenaire_nom', 'categorie', 'image_principale',
        ]

    def get_image_principale(self, obj):
        img = obj.images.filter(est_principale=True, est_active=True).first()
        if not img:
            img = obj.images.filter(est_active=True).first()
        if img and img.image:
            request = self.context.get('request')
            url = img.image.url
            return request.build_absolute_uri(url) if request else url
        return None


class ArticleDetailSerializer(serializers.ModelSerializer):
    """Version complète pour la fiche article."""
    images = ArticleImageSerializer(many=True, read_only=True)
    partenaire_nom = serializers.CharField(source='partenaire.nom_commerce', read_only=True)

    class Meta:
        model = Article
        fields = [
            'id', 'nom', 'slug', 'description', 'type', 'prix', 'prix_promotion',
            'unite', 'details', 'est_actif', 'est_disponible', 'est_en_promotion',
            'temps_preparation_min', 'nb_vues', 'nb_likes', 'nb_commentaires',
            'nb_favoris', 'partenaire', 'partenaire_nom', 'categorie',
            'section_menu', 'images', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'slug', 'nb_vues', 'nb_likes', 'nb_commentaires', 'nb_favoris',
            'partenaire',
        ]
