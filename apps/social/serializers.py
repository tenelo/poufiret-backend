"""Serializers du module Social (likes ❤️ / favoris 🤎 / commentaires 💬)."""
from rest_framework import serializers
from apps.catalog.models import Article
from apps.users.models import ProfilPartenaire
from .models import (
    FavoriArticle, FavoriPartenaire,
    CommentaireArticle, CommentairePartenaire,
)


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

class CommentaireArticleSerializer(serializers.ModelSerializer):
    user_nom = serializers.SerializerMethodField()
    reponses = serializers.SerializerMethodField()
    est_like_par_moi = serializers.SerializerMethodField()
    class Meta:
        model = CommentaireArticle
        fields = ['id', 'user', 'user_nom', 'article', 'parent', 'contenu',
                  'est_visible', 'est_modifie', 'nb_likes', 'est_like_par_moi',
                  'reponses', 'created_at', 'updated_at']
        read_only_fields = ['user', 'est_visible', 'est_modifie', 'nb_likes']
    def get_user_nom(self, obj):
        return obj.user.get_full_name() or obj.user.username or obj.user.telephone
    def get_est_like_par_moi(self, obj):
        req = self.context.get('request')
        if req and req.user and req.user.is_authenticated:
            return obj.likes.filter(user=req.user).exists()
        return False
    def get_reponses(self, obj):
        # 1 seul niveau : on ne sérialise les réponses que pour les commentaires racines
        if obj.parent_id is not None:
            return []
        rep = obj.reponses.filter(est_visible=True).order_by('created_at')
        return CommentaireArticleSerializer(rep, many=True, context=self.context).data
    def validate(self, attrs):
        parent = attrs.get('parent')
        if parent is not None:
            if parent.parent_id is not None:
                raise serializers.ValidationError(
                    "Une réponse ne peut pas répondre à une autre réponse (1 seul niveau).")
            article = attrs.get('article') or getattr(self.instance, 'article', None)
            if article and parent.article_id != article.id:
                raise serializers.ValidationError(
                    "La réponse doit porter sur le même article que le commentaire parent.")
        return attrs

class CommentairePartenaireSerializer(serializers.ModelSerializer):
    user_nom = serializers.SerializerMethodField()
    reponses = serializers.SerializerMethodField()

    class Meta:
        model = CommentairePartenaire
        fields = ['id', 'user', 'user_nom', 'partenaire', 'parent', 'contenu',
                  'est_visible', 'est_modifie', 'nb_likes', 'reponses',
                  'created_at', 'updated_at']
        read_only_fields = ['user', 'est_visible', 'est_modifie', 'nb_likes']

    def get_user_nom(self, obj):
        return obj.user.get_full_name() or obj.user.username or obj.user.telephone

    def get_reponses(self, obj):
        if obj.parent_id is not None:
            return []
        rep = obj.reponses.filter(est_visible=True).order_by('created_at')
        return CommentairePartenaireSerializer(rep, many=True, context=self.context).data

    def validate(self, attrs):
        parent = attrs.get('parent')
        if parent is not None:
            if parent.parent_id is not None:
                raise serializers.ValidationError(
                    "Une réponse ne peut pas répondre à une autre réponse (1 seul niveau).")
            partenaire = attrs.get('partenaire') or getattr(self.instance, 'partenaire', None)
            if partenaire and parent.partenaire_id != partenaire.id:
                raise serializers.ValidationError(
                    "La réponse doit porter sur le même partenaire que le commentaire parent.")
        return attrs
