"""Vues du module Catalogue."""
from django.utils.text import slugify
from django.db.models import F
from rest_framework import viewsets, generics, permissions, status
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from apps.core.permissions import EstPartenaireProprietaireOuLectureSeule
from .models import (
    Categorie, Article, VueArticle, ArticleImage, Variante,
    Supplement, Panorama, Logement, Vehicule,
)
from .serializers import (
    CategorieSerializer, ArticleListeSerializer, ArticleDetailSerializer,
    ArticleImageSerializer, VarianteSerializer, SupplementSerializer,
    PanoramaSerializer, LogementSerializer, VehiculeSerializer,
)


def _article_possede_par(article, user):
    return article.partenaire.user_id == user.id


class CategorieViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CategorieSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = 'slug'

    def get_queryset(self):
        from django.db.models import Count, Q
        qs = Categorie.objects.filter(est_archivee=False)
        if self.action == 'list':
            qs = qs.filter(parent__isnull=True)
        # Nombre de partenaires actifs : rattachés via PartenaireCategorie
        # OU ayant au moins un article actif dans la catégorie (logique annuaire).
        qs = qs.annotate(
            nb_via_liaison=Count('liens_partenaires__partenaire', distinct=True,
                filter=Q(liens_partenaires__partenaire__statut='actif')),
            nb_via_articles=Count('articles__partenaire', distinct=True,
                filter=Q(articles__est_actif=True,
                         articles__partenaire__statut='actif')),
        )
        return qs.order_by('ordre', 'nom')


class ArticleViewSet(viewsets.ModelViewSet):
    permission_classes = [EstPartenaireProprietaireOuLectureSeule]
    lookup_field = 'slug'

    def get_serializer_class(self):
        return ArticleListeSerializer if self.action == 'list' else ArticleDetailSerializer

    def get_queryset(self):
        qs = (Article.objects.select_related('partenaire', 'categorie')
              .prefetch_related('images', 'variantes', 'supplements', 'panoramas'))
        u = self.request.user
        if u.is_authenticated and u.role == u.Role.PARTENAIRE:
            qs = (qs.filter(est_actif=True) | qs.filter(partenaire__user=u)).distinct()
        else:
            qs = qs.filter(est_actif=True)
        p = self.request.query_params
        if p.get('categorie'):
            qs = qs.filter(categorie_id=p['categorie'])
        if p.get('partenaire'):
            qs = qs.filter(partenaire_id=p['partenaire'])
        if p.get('type'):
            qs = qs.filter(type=p['type'])
        if p.get('recherche'):
            qs = qs.filter(nom__icontains=p['recherche'])
        return qs.order_by('-created_at')

    def perform_create(self, serializer):
        profil = self.request.user.profil_partenaire
        # Quota d'articles selon le plan (-1 = illimité)
        maxi = profil.plan.nb_articles_max
        if maxi != -1 and profil.articles.count() >= maxi:
            raise PermissionDenied(
                f"Quota atteint : votre plan {profil.plan.libelle} est limité à "
                f"{maxi} articles. Passez à un plan supérieur pour en ajouter."
            )
        nom = serializer.validated_data.get('nom', '')
        base = slugify(nom)[:200] or 'article'
        slug, i = base, 1
        while profil.articles.filter(slug=slug).exists():
            i += 1
            slug = f"{base}-{i}"
        serializer.save(partenaire=profil, slug=slug)


class _SousRessourceViewSet(viewsets.ModelViewSet):
    """Base pour images/variantes/suppléments/panoramas : filtre par ?article=<id>,
    écriture réservée au partenaire propriétaire de l'article parent."""
    permission_classes = [EstPartenaireProprietaireOuLectureSeule]

    def get_queryset(self):
        qs = self.model.objects.all()
        art = self.request.query_params.get('article')
        return qs.filter(article_id=art) if art else qs

    def _verifier_proprietaire(self, serializer):
        article = serializer.validated_data['article']
        if not _article_possede_par(article, self.request.user):
            raise PermissionDenied("Cet article ne vous appartient pas.")
        return article

    def perform_create(self, serializer):
        self._verifier_proprietaire(serializer)
        serializer.save()


class ArticleImageViewSet(_SousRessourceViewSet):
    model = ArticleImage
    serializer_class = ArticleImageSerializer

    def perform_create(self, serializer):
        article = self._verifier_proprietaire(serializer)
        # Quota photos selon le plan
        maxi = article.partenaire.plan.nb_photos_par_article
        if maxi and article.images.count() >= maxi:
            raise PermissionDenied(
                f"Quota photos atteint ({maxi}/article pour le plan "
                f"{article.partenaire.plan.libelle})."
            )
        serializer.save(est_active=True)


class VarianteViewSet(_SousRessourceViewSet):
    model = Variante
    serializer_class = VarianteSerializer


class SupplementViewSet(_SousRessourceViewSet):
    model = Supplement
    serializer_class = SupplementSerializer


class PanoramaViewSet(_SousRessourceViewSet):
    model = Panorama
    serializer_class = PanoramaSerializer


class _ExtensionView(generics.RetrieveUpdateAPIView):
    """Logement / Véhicule (1-1 avec article). GET public ; PUT/PATCH propriétaire.
    Crée l'extension si absente lors d'une écriture."""
    permission_classes = [EstPartenaireProprietaireOuLectureSeule]
    lookup_field = 'slug'

    def get_object(self):
        article = generics.get_object_or_404(Article, slug=self.kwargs['slug'])
        if self.request.method not in permissions.SAFE_METHODS:
            if not _article_possede_par(article, self.request.user):
                raise PermissionDenied("Cet article ne vous appartient pas.")
        obj, _ = self.model.objects.get_or_create(article=article)
        return obj


class LogementView(_ExtensionView):
    model = Logement
    serializer_class = LogementSerializer


class VehiculeView(_ExtensionView):
    model = Vehicule
    serializer_class = VehiculeSerializer


class EnregistrerVueView(generics.GenericAPIView):
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
        from apps.analytics.services import enregistrer_vue_dans_profil
        enregistrer_vue_dans_profil(request.user if request.user.is_authenticated else None, article)
        return Response({'message': 'Vue enregistrée.'}, status=status.HTTP_201_CREATED)


# ── Annuaire : partenaires d'une catégorie ───────────────────────────
from rest_framework.views import APIView as _APIView
from rest_framework.response import Response as _Response
from apps.users.models import ProfilPartenaire as _ProfilPartenaire


class PartenairesParCategorieView(_APIView):
    """GET /categories/<slug>/partenaires/ — partenaires visibles ayant
    au moins un article actif dans la catégorie."""
    permission_classes = []

    def get(self, request, slug=None):
        from .models import Categorie, Article
        try:
            cat = Categorie.objects.get(slug=slug, est_active=True)
        except Categorie.DoesNotExist:
            return _Response({'erreur': True, 'message': 'Catégorie introuvable.'}, status=404)
        from .models import PartenaireCategorie
        ids = set(Article.objects.filter(categorie=cat, est_actif=True)
                  .values_list('partenaire_id', flat=True))
        ids |= set(PartenaireCategorie.objects.filter(categorie=cat)
                   .values_list('partenaire_id', flat=True))
        partenaires = (_ProfilPartenaire.objects
                       .filter(id__in=list(ids), est_visible=True)
                       .order_by('-est_faveur', 'nom_commerce'))
        def _url(champ):
            if not champ:
                return ''
            try:
                return request.build_absolute_uri(champ.url)
            except Exception:
                return ''
        donnees = [{
            'id': p.id,
            'nom_commerce': p.nom_commerce,
            'description': p.description,
            'logo': _url(p.logo),
            'photo_couverture': _url(p.photo_couverture),
        } for p in partenaires]
        return _Response(donnees)


# ── Stats de vues pour l'espace partenaire ───────────────────────────
from django.utils import timezone as _tz
from datetime import timedelta as _td
from django.db.models import Count as _Count


class StatsVuesPartenaireView(_APIView):
    """GET /partenaire/stats-vues/ — vues par article (jour/semaine/mois/total)
    pour le partenaire connecté."""
    from rest_framework import permissions as _perms
    permission_classes = [_perms.IsAuthenticated]

    def get(self, request):
        if not hasattr(request.user, 'profil_partenaire'):
            return _Response({'erreur': True, 'message': 'Réservé aux partenaires.'}, status=403)
        profil = request.user.profil_partenaire
        maintenant = _tz.now()
        bornes = {
            'jour': maintenant - _td(days=1),
            'semaine': maintenant - _td(days=7),
            'mois': maintenant - _td(days=30),
        }
        donnees = []
        articles = Article.objects.filter(partenaire=profil).order_by('-nb_vues')
        for a in articles:
            qs = VueArticle.objects.filter(article=a)
            donnees.append({
                'article_id': a.id,
                'nom': a.nom,
                'slug': a.slug,
                'est_actif': a.est_actif,
                'total': a.nb_vues,
                'jour': qs.filter(date_vue__gte=bornes['jour']).count(),
                'semaine': qs.filter(date_vue__gte=bornes['semaine']).count(),
                'mois': qs.filter(date_vue__gte=bornes['mois']).count(),
            })
        return _Response({
            'total_vues': sum(d['total'] for d in donnees),
            'articles': donnees,
        })
