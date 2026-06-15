"""Vues du module Social : likes ❤️ (publics) et favoris 🤎 (privés), en toggle."""
from django.db.models import F
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from itertools import chain

from apps.catalog.models import Article
from apps.users.models import ProfilPartenaire
from .models import (
    LikeArticle, LikePartenaire, FavoriArticle, FavoriPartenaire,
)
from .serializers import FavoriArticleSerializer, FavoriPartenaireSerializer


class _ToggleBase(APIView):
    """Ajoute la relation si absente, la retire si présente. Renvoie l'état + compteur."""
    permission_classes = [permissions.IsAuthenticated]
    model = None              # ex: LikeArticle
    cible_model = None        # ex: Article
    cible_champ = None        # ex: 'article'
    compteur = None           # ex: 'nb_likes' (sur la cible) ou None

    def post(self, request, pk=None):
        cible = get_object_or_404(self.cible_model, pk=pk)
        filtre = {'user': request.user, self.cible_champ: cible}
        existant = self.model.objects.filter(**filtre).first()
        if existant:
            existant.delete()
            actif = False
            if self.compteur:
                self.cible_model.objects.filter(pk=cible.pk).update(
                    **{self.compteur: F(self.compteur) - 1})
        else:
            self.model.objects.create(**filtre)
            actif = True
            if self.compteur:
                self.cible_model.objects.filter(pk=cible.pk).update(
                    **{self.compteur: F(self.compteur) + 1})
        total = None
        if self.compteur:
            total = getattr(self.cible_model.objects.get(pk=cible.pk), self.compteur)
        return Response({'actif': actif, 'total': total}, status=status.HTTP_200_OK)


class ToggleLikeArticle(_ToggleBase):
    model = LikeArticle; cible_model = Article; cible_champ = 'article'; compteur = 'nb_likes'

class ToggleFavoriArticle(_ToggleBase):
    model = FavoriArticle; cible_model = Article; cible_champ = 'article'; compteur = 'nb_favoris'

class ToggleLikePartenaire(_ToggleBase):
    model = LikePartenaire; cible_model = ProfilPartenaire; cible_champ = 'partenaire'; compteur = None

class ToggleFavoriPartenaire(_ToggleBase):
    model = FavoriPartenaire; cible_model = ProfilPartenaire; cible_champ = 'partenaire'; compteur = None


class MesFavorisView(APIView):
    """GET /social/mes-favoris/ — favoris articles + partenaires de l'utilisateur."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        arts = FavoriArticle.objects.filter(user=request.user).select_related('article', 'article__partenaire')
        parts = FavoriPartenaire.objects.filter(user=request.user).select_related('partenaire')
        return Response({
            'articles': FavoriArticleSerializer(arts, many=True, context={'request': request}).data,
            'partenaires': FavoriPartenaireSerializer(parts, many=True, context={'request': request}).data,
        })


class MesLikesView(APIView):
    """GET /social/mes-likes/ — ids des articles et partenaires likés (pour l'UI)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        articles = list(LikeArticle.objects.filter(user=request.user).values_list('article_id', flat=True))
        partenaires = list(LikePartenaire.objects.filter(user=request.user).values_list('partenaire_id', flat=True))
        return Response({'articles': articles, 'partenaires': partenaires})
