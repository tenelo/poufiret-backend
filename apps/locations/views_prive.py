"""Espace loueur / admin : logements (Article + Logement, une ressource),
images, panoramas, disponibilité. Même contrat pour les deux périmètres
(mon-espace/admin), comme apps.restaurants — mixins de périmètre + classes
de base partagées, sous-classes minces."""
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Article, ArticleImage, Logement, Panorama
from apps.catalog.serializers import ArticleImageSerializer, PanoramaSerializer
from apps.core.permissions import ADroitDe
from apps.users.models import ProfilPartenaire

from . import services
from .serializers import LogementGestionSerializer


def _journaliser_admin(acteur, partenaire, action, motif):
    try:
        from apps.administration.moderation import _journaliser
        _journaliser(acteur, partenaire.user, action, motif)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# Mixins de périmètre
# ═══════════════════════════════════════════════════════════════════════

class _PerimetreLoueurMixin:
    permission_classes = [permissions.IsAuthenticated]
    acteur_role = 'loueur'

    def get_partenaire(self):
        profil = getattr(self.request.user, 'profil_partenaire', None)
        if profil is None or profil.type_partenaire not in services.TYPES_LOCATION:
            raise PermissionDenied('Réservé aux loueurs.')
        return profil

    def acteur_nom(self):
        u = self.request.user
        return u.get_full_name() or u.username or u.telephone


class _PerimetreAdminMixin:
    permission_classes = [permissions.IsAuthenticated, ADroitDe('gerer_locations')]
    acteur_role = 'admin'

    def get_partenaire(self):
        partenaire = ProfilPartenaire.objects.filter(
            pk=self.kwargs['partenaire_id'], type_partenaire__in=services.TYPES_LOCATION).first()
        if partenaire is None:
            from django.http import Http404
            raise Http404('Loueur introuvable.')
        return partenaire

    def acteur_nom(self):
        u = self.request.user
        return u.get_full_name() or u.username or u.telephone


# ═══════════════════════════════════════════════════════════════════════
# LOGEMENTS
# ═══════════════════════════════════════════════════════════════════════

class _LogementsListCreateBase(APIView):
    """GET ?disponibilite= — tous les logements du loueur (gestion, y
    compris indisponibles). POST crée un logement (Article + Logement)."""

    def get(self, request, *args, **kwargs):
        partenaire = self.get_partenaire()
        qs = (Logement.objects.filter(article__partenaire=partenaire, article__type=Article.Type.LOGEMENT)
              .select_related('article', 'localite__departement', 'quartier_geo').order_by('-article__created_at'))
        dispo = request.query_params.get('disponibilite')
        if dispo:
            qs = qs.filter(disponibilite=dispo)
        return Response({'resultats': [services.logement_dict(l, request) for l in qs]})

    def post(self, request, *args, **kwargs):
        partenaire = self.get_partenaire()
        ser = LogementGestionSerializer(data=request.data, context={
            'partenaire': partenaire, 'acteur_role': self.acteur_role, 'acteur_nom': self.acteur_nom()})
        if not ser.is_valid():
            return Response({'erreur': True, 'details': ser.errors}, status=400)
        logement = ser.save()
        if self.acteur_role == 'admin':
            _journaliser_admin(request.user, partenaire, 'loc_logement_modif',
                               f'Logement « {logement.article.nom} » créé par l\'admin.')
        return Response(services.logement_dict(logement, request), status=201)


class _LogementDetailBase(APIView):
    """GET/PATCH/DELETE <id>/ — pk = Article.id."""

    def _obj(self, pk, **kwargs):
        partenaire = self.get_partenaire()
        return partenaire, get_object_or_404(
            Logement.objects.select_related('article', 'localite__departement', 'quartier_geo'),
            article_id=pk, article__partenaire=partenaire, article__type=Article.Type.LOGEMENT)

    def get(self, request, pk=None, **kwargs):
        _, obj = self._obj(pk)
        return Response(services.logement_dict(obj, request))

    def patch(self, request, pk=None, **kwargs):
        partenaire, obj = self._obj(pk)
        ser = LogementGestionSerializer(obj, data=request.data, partial=True, context={
            'partenaire': partenaire, 'acteur_role': self.acteur_role, 'acteur_nom': self.acteur_nom()})
        if not ser.is_valid():
            return Response({'erreur': True, 'details': ser.errors}, status=400)
        obj = ser.save()
        if self.acteur_role == 'admin':
            _journaliser_admin(request.user, partenaire, 'loc_logement_modif',
                               f'Logement « {obj.article.nom} » modifié par l\'admin.')
        return Response(services.logement_dict(obj, request))

    def delete(self, request, pk=None, **kwargs):
        from django.db.models import ProtectedError
        partenaire, obj = self._obj(pk)
        nom = obj.article.nom
        try:
            obj.article.delete()
        except ProtectedError:
            return Response({'erreur': True, 'message':
                             'Impossible de supprimer : des demandes de visite/réservation '
                             'portent sur ce logement. Désactivez-le plutôt (est_actif=false).'},
                            status=409)
        if self.acteur_role == 'admin':
            _journaliser_admin(request.user, partenaire, 'loc_logement_modif',
                               f'Logement « {nom} » supprimé par l\'admin.')
        return Response(status=204)


class _DisponibiliteBase(APIView):
    """POST <id>/disponibilite/ {"disponibilite": "disponible|reserve|loue"}."""

    def post(self, request, pk=None, **kwargs):
        partenaire = self.get_partenaire()
        obj = get_object_or_404(
            Logement, article_id=pk, article__partenaire=partenaire, article__type=Article.Type.LOGEMENT)
        valeur = request.data.get('disponibilite')
        if valeur not in dict(Logement.Disponibilite.choices):
            return Response({'erreur': True, 'details': {'disponibilite': [
                f'Valeur attendue parmi : {", ".join(dict(Logement.Disponibilite.choices))}.']}}, status=400)
        obj.disponibilite = valeur
        obj.modifie_par_role = self.acteur_role
        obj.modifie_par_nom = self.acteur_nom()
        obj.save(update_fields=['disponibilite', 'modifie_par_role', 'modifie_par_nom', 'updated_at'])
        if self.acteur_role == 'admin':
            _journaliser_admin(request.user, partenaire, 'loc_dispo_modif',
                               f'Logement « {obj.article.nom} » → {obj.get_disponibilite_display()} (admin).')
        return Response(services.logement_dict(obj, request))


class MonLogementsView(_PerimetreLoueurMixin, _LogementsListCreateBase):
    """GET/POST /locations/mon-espace/logements/"""


class MonLogementDetailView(_PerimetreLoueurMixin, _LogementDetailBase):
    """GET/PATCH/DELETE /locations/mon-espace/logements/<id>/"""


class MonLogementDisponibiliteView(_PerimetreLoueurMixin, _DisponibiliteBase):
    """POST /locations/mon-espace/logements/<id>/disponibilite/"""


class AdminLogementsView(_PerimetreAdminMixin, _LogementsListCreateBase):
    """GET/POST /locations/admin/<partenaire_id>/logements/"""


class AdminLogementDetailView(_PerimetreAdminMixin, _LogementDetailBase):
    """GET/PATCH/DELETE /locations/admin/<partenaire_id>/logements/<id>/"""


class AdminLogementDisponibiliteView(_PerimetreAdminMixin, _DisponibiliteBase):
    """POST /locations/admin/<partenaire_id>/logements/<id>/disponibilite/"""


# ═══════════════════════════════════════════════════════════════════════
# IMAGES (même comportement que /catalogue/images/ existant : quota du
# plan, pas de bascule auto d'image principale).
# ═══════════════════════════════════════════════════════════════════════

class _LogementImagesListCreateBase(generics.ListCreateAPIView):
    serializer_class = ArticleImageSerializer

    def _logement_article(self):
        return get_object_or_404(
            Article, pk=self.kwargs['logement_id'], partenaire=self.get_partenaire(),
            type=Article.Type.LOGEMENT)

    def get_queryset(self):
        return self._logement_article().images.order_by('ordre')

    def perform_create(self, serializer):
        article = self._logement_article()
        maxi = article.partenaire.plan.nb_photos_par_article
        if maxi and article.images.count() >= maxi:
            raise PermissionDenied(
                f'Quota photos atteint ({maxi}/article pour le plan {article.partenaire.plan.libelle}).')
        serializer.save(article=article, est_active=True)


class _LogementImageDetailBase(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ArticleImageSerializer

    def get_queryset(self):
        return ArticleImage.objects.filter(
            article_id=self.kwargs['logement_id'], article__partenaire=self.get_partenaire())


class MonLogementImagesView(_PerimetreLoueurMixin, _LogementImagesListCreateBase):
    """GET/POST /locations/mon-espace/logements/<logement_id>/images/"""


class MonLogementImageDetailView(_PerimetreLoueurMixin, _LogementImageDetailBase):
    """GET/PATCH/DELETE /locations/mon-espace/logements/<logement_id>/images/<id>/"""


class AdminLogementImagesView(_PerimetreAdminMixin, _LogementImagesListCreateBase):
    """GET/POST /locations/admin/<partenaire_id>/logements/<logement_id>/images/"""


class AdminLogementImageDetailView(_PerimetreAdminMixin, _LogementImageDetailBase):
    """GET/PATCH/DELETE /locations/admin/<partenaire_id>/logements/<logement_id>/images/<id>/"""


# ═══════════════════════════════════════════════════════════════════════
# PANORAMAS (visite immersive) — même modèle/serializer que /catalogue/panoramas/.
# ═══════════════════════════════════════════════════════════════════════

class _LogementPanoramasListCreateBase(generics.ListCreateAPIView):
    serializer_class = PanoramaSerializer

    def _logement_article(self):
        return get_object_or_404(
            Article, pk=self.kwargs['logement_id'], partenaire=self.get_partenaire(),
            type=Article.Type.LOGEMENT)

    def get_queryset(self):
        return self._logement_article().panoramas.order_by('ordre')

    def perform_create(self, serializer):
        serializer.save(article=self._logement_article(), est_active=True)


class _LogementPanoramaDetailBase(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PanoramaSerializer

    def get_queryset(self):
        return Panorama.objects.filter(
            article_id=self.kwargs['logement_id'], article__partenaire=self.get_partenaire())


class MonLogementPanoramasView(_PerimetreLoueurMixin, _LogementPanoramasListCreateBase):
    """GET/POST /locations/mon-espace/logements/<logement_id>/panoramas/"""


class MonLogementPanoramaDetailView(_PerimetreLoueurMixin, _LogementPanoramaDetailBase):
    """GET/PATCH/DELETE /locations/mon-espace/logements/<logement_id>/panoramas/<id>/"""


class AdminLogementPanoramasView(_PerimetreAdminMixin, _LogementPanoramasListCreateBase):
    """GET/POST /locations/admin/<partenaire_id>/logements/<logement_id>/panoramas/"""


class AdminLogementPanoramaDetailView(_PerimetreAdminMixin, _LogementPanoramaDetailBase):
    """GET/PATCH/DELETE /locations/admin/<partenaire_id>/logements/<logement_id>/panoramas/<id>/"""
