"""Vues du module Social : likes ❤️, favoris 🤎, commentaires 💬."""
from django.db.models import F
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response

from apps.catalog.models import Article
from apps.users.models import ProfilPartenaire
from apps.core.permissions import EstAuteurOuModerateurOuLectureSeule
from .models import (
    LikeArticle, LikePartenaire, FavoriArticle, FavoriPartenaire,
    CommentaireArticle, CommentairePartenaire, LikeCommentaire,
)
from .serializers import (
    FavoriArticleSerializer, FavoriPartenaireSerializer,
    CommentaireArticleSerializer, CommentairePartenaireSerializer,
)


# ── LIKES / FAVORIS (toggle) ──────────────────────────────────────────
class _ToggleBase(APIView):
    permission_classes = [permissions.IsAuthenticated]
    model = None; cible_model = None; cible_champ = None; compteur = None

    def post(self, request, pk=None):
        cible = get_object_or_404(self.cible_model, pk=pk)
        filtre = {'user': request.user, self.cible_champ: cible}
        existant = self.model.objects.filter(**filtre).first()
        if existant:
            existant.delete(); actif = False
            if self.compteur:
                self.cible_model.objects.filter(pk=cible.pk).update(**{self.compteur: F(self.compteur) - 1})
        else:
            self.model.objects.create(**filtre); actif = True
            if self.compteur:
                self.cible_model.objects.filter(pk=cible.pk).update(**{self.compteur: F(self.compteur) + 1})
        total = getattr(self.cible_model.objects.get(pk=cible.pk), self.compteur) if self.compteur else None
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
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        arts = FavoriArticle.objects.filter(user=request.user).select_related('article', 'article__partenaire')
        parts = FavoriPartenaire.objects.filter(user=request.user).select_related('partenaire')
        return Response({
            'articles': FavoriArticleSerializer(arts, many=True, context={'request': request}).data,
            'partenaires': FavoriPartenaireSerializer(parts, many=True, context={'request': request}).data,
        })


class MesLikesView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        return Response({
            'articles': list(LikeArticle.objects.filter(user=request.user).values_list('article_id', flat=True)),
            'partenaires': list(LikePartenaire.objects.filter(user=request.user).values_list('partenaire_id', flat=True)),
        })


# ── COMMENTAIRES ──────────────────────────────────────────────────────
class CommentaireArticleViewSet(generics.ListCreateAPIView):
    """GET (public) liste racines d'un article ?article=<id> ; POST (authentifié)."""
    serializer_class = CommentaireArticleSerializer
    permission_classes = [EstAuteurOuModerateurOuLectureSeule]

    def get_queryset(self):
        qs = CommentaireArticle.objects.filter(est_visible=True, parent__isnull=True).select_related('user')
        art = self.request.query_params.get('article')
        return qs.filter(article_id=art) if art else qs

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class CommentaireArticleDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = CommentaireArticle.objects.all()
    serializer_class = CommentaireArticleSerializer
    permission_classes = [EstAuteurOuModerateurOuLectureSeule]

    def perform_update(self, serializer):
        serializer.save(est_modifie=True)


class CommentairePartenaireViewSet(generics.ListCreateAPIView):
    serializer_class = CommentairePartenaireSerializer
    permission_classes = [EstAuteurOuModerateurOuLectureSeule]

    def get_queryset(self):
        qs = CommentairePartenaire.objects.filter(est_visible=True, parent__isnull=True).select_related('user')
        part = self.request.query_params.get('partenaire')
        return qs.filter(partenaire_id=part) if part else qs

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class CommentairePartenaireDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = CommentairePartenaire.objects.all()
    serializer_class = CommentairePartenaireSerializer
    permission_classes = [EstAuteurOuModerateurOuLectureSeule]

    def perform_update(self, serializer):
        serializer.save(est_modifie=True)


# ── LIKES DE COMMENTAIRES (toggle) ────────────────────────────────────
class ToggleLikeCommentaire(APIView):
    """POST /commentaires/<type>/<id>/like/ où type = 'article' ou 'partenaire'."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, type_comm=None, pk=None):
        if type_comm == 'article':
            comm = get_object_or_404(CommentaireArticle, pk=pk)
            filtre = {'user': request.user, 'commentaire_article': comm}
        elif type_comm == 'partenaire':
            comm = get_object_or_404(CommentairePartenaire, pk=pk)
            filtre = {'user': request.user, 'commentaire_partenaire': comm}
        else:
            return Response({'erreur': True, 'message': 'Type invalide.'}, status=400)
        existant = LikeCommentaire.objects.filter(**filtre).first()
        cls = type(comm)
        if existant:
            existant.delete(); actif = False
            cls.objects.filter(pk=comm.pk).update(nb_likes=F('nb_likes') - 1)
        else:
            LikeCommentaire.objects.create(**filtre); actif = True
            cls.objects.filter(pk=comm.pk).update(nb_likes=F('nb_likes') + 1)
        total = cls.objects.get(pk=comm.pk).nb_likes
        return Response({'actif': actif, 'total': total}, status=status.HTTP_200_OK)
