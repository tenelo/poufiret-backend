"""Serializers du module Social (likes ❤️ / favoris 🤎)."""
from rest_framework import serializers
from apps.catalog.models import Article
from apps.users.models import ProfilPartenaire
from .models import FavoriArticle, FavoriPartenaire


class _ArticleMiniSerializer(serializers.ModelSerializer):
    partenaire_nom = serializers.CharField(source='partenaire.nom_commerce', read_only=True)
    class Meta:
        model = Article
        fields = ['id', 'nom', 'slug', 'type', 'prix', 'nb_vues', 'nb_likes',
                  'partenaire', 'partenaire_nom', 'categorie']


class _PartenaireMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProfilPartenaire
        fields = ['id', 'nom_commerce', 'type_partenaire', 'ville', 'quartier', 'logo']


class FavoriArticleSerializer(serializers.ModelSerializer):
    article = _ArticleMiniSerializer(read_only=True)
    class Meta:
        model = FavoriArticle
        fields = ['id', 'article', 'created_at']


class FavoriPartenaireSerializer(serializers.ModelSerializer):
    partenaire = _PartenaireMiniSerializer(read_only=True)
    class Meta:
        model = FavoriPartenaire
        fields = ['id', 'partenaire', 'created_at']
