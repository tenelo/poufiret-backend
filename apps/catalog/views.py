"""
Vues du module Catalogue.
"""
from django.utils.text import slugify
from django.db.models import F
from rest_framework import viewsets, generics, permissions, status
from rest_framework.response import Response
from apps.core.permissions import EstPartenaireProprietaireOuLectureSeule
from .models import Categorie, Article, VueArticle
from .serializers import (
    CategorieSerializer, ArticleListeSerializer, ArticleDetailSerializer,
)


class CategorieViewSet(viewsets.ReadOnlyModelViewSet):
    """Lecture seule des catégories. Public. Racines seulement (enfants imbriqués)."""
    serializer_class = CategorieSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = 'slug'

    def get_queryset(self):
        qs = Categorie.objects.filter(est_active=True)
        # En liste : seulement les racines (les enfants sont imbriqués par le serializer)
        if self.action == 'list':
            qs = qs.filter(parent__isnull=True)
        return qs.order_by('ordre', 'nom')


class ArticleViewSet(viewsets.ModelViewSet):
    """
    Articles : lecture publique, écriture réservée au partenaire propriétaire.
    Filtrage par ?categorie=<id>, ?partenaire=<id>, ?type=<type>, ?recherche=<texte>.
    """
    permission_classes = [EstPartenaireProprietaireOuLectureSeule]
    lookup_field = 'slug'

    def get_serializer_class(self):
        if self.action == 'list':
            return ArticleListeSerializer
        return ArticleDetailSerializer

    def get_queryset(self):
        qs = (Article.objects
              .select_related('partenaire', 'categorie')
              .prefetch_related('images'))
        # Le public ne voit que les articles actifs ; le partenaire voit les siens (même inactifs)
        user = self.request.user
        if user.is_authenticated and user.role == user.Role.PARTENAIRE:
            qs = qs.filter(est_actif=True) | qs.filter(partenaire__user=user)
            qs = qs.distinct()
        else:
            qs = qs.filter(est_actif=True)

        params = self.request.query_params
        if params.get('categorie'):
            qs = qs.filter(categorie_id=params['categorie'])
        if params.get('partenaire'):
            qs = qs.filter(partenaire_id=params['partenaire'])
        if params.get('type'):
            qs = qs.filter(type=params['type'])
        if params.get('recherche'):
            qs = qs.filter(nom__icontains=params['recherche'])
        return qs.order_by('-created_at')

    def perform_create(self, serializer):
        # Le partenaire ne peut créer QUE pour lui-même : on force le propriétaire.
        profil = self.request.user.profil_partenaire
        nom = serializer.validated_data.get('nom', '')
        slug = slugify(nom)[:220] or 'article'
        serializer.save(partenaire=profil, slug=slug)


class EnregistrerVueView(generics.GenericAPIView):
    """
    POST /catalogue/articles/<slug>/vue/ — enregistre une consultation
    et incrémente le compteur dénormalisé nb_vues.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, slug=None):
        article = Article.objects.filter(slug=slug, est_actif=True).first()
        if not article:
            return Response({'erreur': True, 'message': 'Article introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)
        VueArticle.objects.create(
            article=article,
            user=request.user if request.user.is_authenticated else None,
            source=request.data.get('source', VueArticle.Source.AUTRE),
            duree_secondes=request.data.get('duree_secondes'),
        )
        Article.objects.filter(pk=article.pk).update(nb_vues=F('nb_vues') + 1)
        return Response({'message': 'Vue enregistrée.'}, status=status.HTTP_201_CREATED)
