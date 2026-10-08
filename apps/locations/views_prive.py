"""Espace loueur / admin : biens en location — logements (M1), véhicules
(V1), hébergements (V2) — (Article + fiche, une ressource), images,
panoramas, disponibilité ; fiche établissement (V2).
Même contrat pour les deux périmètres (mon-espace/admin), comme
apps.restaurants — mixins de périmètre + classes de base partagées,
paramétrées par le type de bien (_BienLogement / _BienVehicule /
_BienHebergement), sous-classes
minces."""
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Article, ArticleImage, Hebergement, Logement, Panorama, Vehicule
from apps.catalog.serializers import ArticleImageSerializer, PanoramaSerializer
from apps.core.permissions import ADroitDe
from apps.users.models import ProfilPartenaire

from . import services
from .serializers import (
    EtablissementGestionSerializer, HebergementGestionSerializer, LogementGestionSerializer,
    VehiculeGestionSerializer,
)


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
        if profil is None or profil.type_partenaire not in self.types_partenaire:
            raise PermissionDenied(self.message_refus)
        return profil

    def acteur_nom(self):
        u = self.request.user
        return u.get_full_name() or u.username or u.telephone


class _PerimetreAdminMixin:
    permission_classes = [permissions.IsAuthenticated, ADroitDe('gerer_locations')]
    acteur_role = 'admin'

    def get_partenaire(self):
        partenaire = ProfilPartenaire.objects.filter(
            pk=self.kwargs['partenaire_id'], type_partenaire__in=self.types_partenaire).first()
        if partenaire is None:
            from django.http import Http404
            raise Http404('Loueur introuvable.')
        return partenaire

    def acteur_nom(self):
        u = self.request.user
        return u.get_full_name() or u.username or u.telephone


# ═══════════════════════════════════════════════════════════════════════
# Types de biens — tout ce qui distingue un logement d'un véhicule
# ═══════════════════════════════════════════════════════════════════════

class _BienLogement:
    types_partenaire = [ProfilPartenaire.TypePartenaire.LOUEUR_MAISON]
    message_refus = 'Réservé aux loueurs.'
    modele_fiche = Logement
    article_type = Article.Type.LOGEMENT
    serializer_gestion = LogementGestionSerializer
    kwarg_objet = 'logement_id'
    libelle = 'Logement'
    action_modif = 'loc_logement_modif'
    action_dispo = 'loc_dispo_modif'
    message_409 = ('Impossible de supprimer : des demandes de visite/réservation '
                   'portent sur ce logement. Désactivez-le plutôt (est_actif=false).')

    @staticmethod
    def representer(obj, request):
        return services.logement_dict(obj, request)


class _BienVehicule:
    types_partenaire = [ProfilPartenaire.TypePartenaire.LOUEUR_VOITURE]
    message_refus = 'Réservé aux loueurs de véhicules.'
    modele_fiche = Vehicule
    article_type = Article.Type.VEHICULE
    serializer_gestion = VehiculeGestionSerializer
    kwarg_objet = 'vehicule_id'
    libelle = 'Véhicule'
    action_modif = 'loc_vehicule_modif'
    action_dispo = 'loc_vehicule_dispo'
    message_409 = ('Impossible de supprimer : des demandes de réservation '
                   'portent sur ce véhicule. Désactivez-le plutôt (est_actif=false).')

    @staticmethod
    def representer(obj, request):
        return services.vehicule_dict(obj, request)


class _BienHebergement:
    types_partenaire = [ProfilPartenaire.TypePartenaire.HOTELIER]
    message_refus = 'Réservé aux hôteliers.'
    modele_fiche = Hebergement
    article_type = Article.Type.HEBERGEMENT
    serializer_gestion = HebergementGestionSerializer
    relations_fiche = ('article',)
    kwarg_objet = 'hebergement_id'
    libelle = 'Hébergement'
    action_modif = 'loc_hebergement_modif'
    action_dispo = 'loc_hebergement_dispo'
    message_409 = ('Impossible de supprimer : des demandes de réservation '
                   'portent sur cet hébergement. Désactivez-le plutôt (est_actif=false).')

    @staticmethod
    def representer(obj, request):
        return services.hebergement_dict(obj, request)


# ═══════════════════════════════════════════════════════════════════════
# BIENS (logements, véhicules, hébergements)
# ═══════════════════════════════════════════════════════════════════════

class _BienQuerysetMixin:
    relations_fiche = ('article', 'localite__departement', 'quartier_geo')

    def _fiches(self, partenaire):
        return (self.modele_fiche.objects
                .filter(article__partenaire=partenaire, article__type=self.article_type)
                .select_related(*self.relations_fiche))

    def _contexte(self, partenaire):
        return {'partenaire': partenaire, 'acteur_role': self.acteur_role, 'acteur_nom': self.acteur_nom()}


class _BiensListCreateBase(_BienQuerysetMixin, APIView):
    """GET ?disponibilite= — tous les biens du loueur (gestion, y compris
    indisponibles). POST crée un bien (Article + fiche)."""

    def get(self, request, *args, **kwargs):
        partenaire = self.get_partenaire()
        qs = self._fiches(partenaire).order_by('-article__created_at')
        dispo = request.query_params.get('disponibilite')
        if dispo:
            qs = qs.filter(disponibilite=dispo)
        return Response({'resultats': [self.representer(o, request) for o in qs]})

    def post(self, request, *args, **kwargs):
        partenaire = self.get_partenaire()
        ser = self.serializer_gestion(data=request.data, context=self._contexte(partenaire))
        if not ser.is_valid():
            return Response({'erreur': True, 'details': ser.errors}, status=400)
        obj = ser.save()
        if self.acteur_role == 'admin':
            _journaliser_admin(request.user, partenaire, self.action_modif,
                               f'{self.libelle} « {obj.article.nom} » créé par l\'admin.')
        return Response(self.representer(obj, request), status=201)


class _BienDetailBase(_BienQuerysetMixin, APIView):
    """GET/PATCH/DELETE <id>/ — pk = Article.id."""

    def _obj(self, pk):
        partenaire = self.get_partenaire()
        return partenaire, get_object_or_404(self._fiches(partenaire), article_id=pk)

    def get(self, request, pk=None, **kwargs):
        _, obj = self._obj(pk)
        return Response(self.representer(obj, request))

    def patch(self, request, pk=None, **kwargs):
        partenaire, obj = self._obj(pk)
        ser = self.serializer_gestion(obj, data=request.data, partial=True, context=self._contexte(partenaire))
        if not ser.is_valid():
            return Response({'erreur': True, 'details': ser.errors}, status=400)
        obj = ser.save()
        if self.acteur_role == 'admin':
            _journaliser_admin(request.user, partenaire, self.action_modif,
                               f'{self.libelle} « {obj.article.nom} » modifié par l\'admin.')
        return Response(self.representer(obj, request))

    def delete(self, request, pk=None, **kwargs):
        from django.db.models import ProtectedError
        partenaire, obj = self._obj(pk)
        nom = obj.article.nom
        try:
            obj.article.delete()
        except ProtectedError:
            return Response({'erreur': True, 'message': self.message_409}, status=409)
        if self.acteur_role == 'admin':
            _journaliser_admin(request.user, partenaire, self.action_modif,
                               f'{self.libelle} « {nom} » supprimé par l\'admin.')
        return Response(status=204)


class _DisponibiliteBase(_BienQuerysetMixin, APIView):
    """POST <id>/disponibilite/ {"disponibilite": <choix de la fiche>}
    (logement : disponible|reserve|loue ; véhicule : disponible|indisponible)."""

    def post(self, request, pk=None, **kwargs):
        partenaire = self.get_partenaire()
        obj = get_object_or_404(self._fiches(partenaire), article_id=pk)
        choix = dict(self.modele_fiche.Disponibilite.choices)
        valeur = request.data.get('disponibilite')
        if valeur not in choix:
            return Response({'erreur': True, 'details': {'disponibilite': [
                f'Valeur attendue parmi : {", ".join(choix)}.']}}, status=400)
        obj.disponibilite = valeur
        obj.modifie_par_role = self.acteur_role
        obj.modifie_par_nom = self.acteur_nom()
        obj.save(update_fields=['disponibilite', 'modifie_par_role', 'modifie_par_nom', 'updated_at'])
        if self.acteur_role == 'admin':
            _journaliser_admin(request.user, partenaire, self.action_dispo,
                               f'{self.libelle} « {obj.article.nom} » → {obj.get_disponibilite_display()} (admin).')
        return Response(self.representer(obj, request))


# ═══════════════════════════════════════════════════════════════════════
# IMAGES (même comportement que /catalogue/images/ existant : quota du
# plan, pas de bascule auto d'image principale).
# ═══════════════════════════════════════════════════════════════════════

class _BienArticleMixin:
    def _bien_article(self):
        return get_object_or_404(
            Article, pk=self.kwargs[self.kwarg_objet], partenaire=self.get_partenaire(),
            type=self.article_type)


class _ImagesListCreateBase(_BienArticleMixin, generics.ListCreateAPIView):
    serializer_class = ArticleImageSerializer

    def get_queryset(self):
        return self._bien_article().images.order_by('ordre')

    def perform_create(self, serializer):
        article = self._bien_article()
        maxi = article.partenaire.plan.nb_photos_par_article
        if maxi and article.images.count() >= maxi:
            raise PermissionDenied(
                f'Quota photos atteint ({maxi}/article pour le plan {article.partenaire.plan.libelle}).')
        serializer.save(article=article, est_active=True)


class _ImageDetailBase(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ArticleImageSerializer

    def get_queryset(self):
        return ArticleImage.objects.filter(
            article_id=self.kwargs[self.kwarg_objet], article__type=self.article_type,
            article__partenaire=self.get_partenaire())


# ═══════════════════════════════════════════════════════════════════════
# PANORAMAS (visite immersive / vue intérieure 360°) — même
# modèle/serializer que /catalogue/panoramas/.
# ═══════════════════════════════════════════════════════════════════════

class _PanoramasListCreateBase(_BienArticleMixin, generics.ListCreateAPIView):
    serializer_class = PanoramaSerializer

    def get_queryset(self):
        return self._bien_article().panoramas.order_by('ordre')

    def perform_create(self, serializer):
        serializer.save(article=self._bien_article(), est_active=True)


class _PanoramaDetailBase(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PanoramaSerializer

    def get_queryset(self):
        return Panorama.objects.filter(
            article_id=self.kwargs[self.kwarg_objet], article__type=self.article_type,
            article__partenaire=self.get_partenaire())


# ═══════════════════════════════════════════════════════════════════════
# FICHE ÉTABLISSEMENT (V2) — créée à la première lecture en gestion.
# ═══════════════════════════════════════════════════════════════════════

class _EtablissementBase(APIView):
    """GET/PATCH P/etablissement/"""

    def get(self, request, *args, **kwargs):
        fiche = services.fiche_etablissement(self.get_partenaire(), creer=True)
        return Response(services.etablissement_gestion_dict(fiche))

    def patch(self, request, *args, **kwargs):
        partenaire = self.get_partenaire()
        fiche = services.fiche_etablissement(partenaire, creer=True)
        ser = EtablissementGestionSerializer(fiche, data=request.data, partial=True, context={
            'acteur_role': self.acteur_role, 'acteur_nom': self.acteur_nom()})
        if not ser.is_valid():
            return Response({'erreur': True, 'details': ser.errors}, status=400)
        fiche = ser.save()
        if self.acteur_role == 'admin':
            _journaliser_admin(request.user, partenaire, 'loc_etablissement_modif',
                               f'Fiche établissement « {partenaire.nom_commerce} » modifiée par l\'admin.')
        return Response(services.etablissement_gestion_dict(fiche))


class MonEtablissementView(_BienHebergement, _PerimetreLoueurMixin, _EtablissementBase):
    """GET/PATCH /locations/mon-espace/etablissement/"""


class AdminEtablissementView(_BienHebergement, _PerimetreAdminMixin, _EtablissementBase):
    """GET/PATCH /locations/admin/<partenaire_id>/etablissement/"""


# ═══════════════════════════════════════════════════════════════════════
# Vues concrètes — logements (M1)
# ═══════════════════════════════════════════════════════════════════════

class MonLogementsView(_BienLogement, _PerimetreLoueurMixin, _BiensListCreateBase):
    """GET/POST /locations/mon-espace/logements/"""


class MonLogementDetailView(_BienLogement, _PerimetreLoueurMixin, _BienDetailBase):
    """GET/PATCH/DELETE /locations/mon-espace/logements/<id>/"""


class MonLogementDisponibiliteView(_BienLogement, _PerimetreLoueurMixin, _DisponibiliteBase):
    """POST /locations/mon-espace/logements/<id>/disponibilite/"""


class AdminLogementsView(_BienLogement, _PerimetreAdminMixin, _BiensListCreateBase):
    """GET/POST /locations/admin/<partenaire_id>/logements/"""


class AdminLogementDetailView(_BienLogement, _PerimetreAdminMixin, _BienDetailBase):
    """GET/PATCH/DELETE /locations/admin/<partenaire_id>/logements/<id>/"""


class AdminLogementDisponibiliteView(_BienLogement, _PerimetreAdminMixin, _DisponibiliteBase):
    """POST /locations/admin/<partenaire_id>/logements/<id>/disponibilite/"""


class MonLogementImagesView(_BienLogement, _PerimetreLoueurMixin, _ImagesListCreateBase):
    """GET/POST /locations/mon-espace/logements/<logement_id>/images/"""


class MonLogementImageDetailView(_BienLogement, _PerimetreLoueurMixin, _ImageDetailBase):
    """GET/PATCH/DELETE /locations/mon-espace/logements/<logement_id>/images/<id>/"""


class AdminLogementImagesView(_BienLogement, _PerimetreAdminMixin, _ImagesListCreateBase):
    """GET/POST /locations/admin/<partenaire_id>/logements/<logement_id>/images/"""


class AdminLogementImageDetailView(_BienLogement, _PerimetreAdminMixin, _ImageDetailBase):
    """GET/PATCH/DELETE /locations/admin/<partenaire_id>/logements/<logement_id>/images/<id>/"""


class MonLogementPanoramasView(_BienLogement, _PerimetreLoueurMixin, _PanoramasListCreateBase):
    """GET/POST /locations/mon-espace/logements/<logement_id>/panoramas/"""


class MonLogementPanoramaDetailView(_BienLogement, _PerimetreLoueurMixin, _PanoramaDetailBase):
    """GET/PATCH/DELETE /locations/mon-espace/logements/<logement_id>/panoramas/<id>/"""


class AdminLogementPanoramasView(_BienLogement, _PerimetreAdminMixin, _PanoramasListCreateBase):
    """GET/POST /locations/admin/<partenaire_id>/logements/<logement_id>/panoramas/"""


class AdminLogementPanoramaDetailView(_BienLogement, _PerimetreAdminMixin, _PanoramaDetailBase):
    """GET/PATCH/DELETE /locations/admin/<partenaire_id>/logements/<logement_id>/panoramas/<id>/"""


# ═══════════════════════════════════════════════════════════════════════
# Vues concrètes — véhicules (V1)
# ═══════════════════════════════════════════════════════════════════════

class MonVehiculesView(_BienVehicule, _PerimetreLoueurMixin, _BiensListCreateBase):
    """GET/POST /locations/mon-espace/vehicules/"""


class MonVehiculeDetailView(_BienVehicule, _PerimetreLoueurMixin, _BienDetailBase):
    """GET/PATCH/DELETE /locations/mon-espace/vehicules/<id>/"""


class MonVehiculeDisponibiliteView(_BienVehicule, _PerimetreLoueurMixin, _DisponibiliteBase):
    """POST /locations/mon-espace/vehicules/<id>/disponibilite/"""


class AdminVehiculesView(_BienVehicule, _PerimetreAdminMixin, _BiensListCreateBase):
    """GET/POST /locations/admin/<partenaire_id>/vehicules/"""


class AdminVehiculeDetailView(_BienVehicule, _PerimetreAdminMixin, _BienDetailBase):
    """GET/PATCH/DELETE /locations/admin/<partenaire_id>/vehicules/<id>/"""


class AdminVehiculeDisponibiliteView(_BienVehicule, _PerimetreAdminMixin, _DisponibiliteBase):
    """POST /locations/admin/<partenaire_id>/vehicules/<id>/disponibilite/"""


class MonVehiculeImagesView(_BienVehicule, _PerimetreLoueurMixin, _ImagesListCreateBase):
    """GET/POST /locations/mon-espace/vehicules/<vehicule_id>/images/"""


class MonVehiculeImageDetailView(_BienVehicule, _PerimetreLoueurMixin, _ImageDetailBase):
    """GET/PATCH/DELETE /locations/mon-espace/vehicules/<vehicule_id>/images/<id>/"""


class AdminVehiculeImagesView(_BienVehicule, _PerimetreAdminMixin, _ImagesListCreateBase):
    """GET/POST /locations/admin/<partenaire_id>/vehicules/<vehicule_id>/images/"""


class AdminVehiculeImageDetailView(_BienVehicule, _PerimetreAdminMixin, _ImageDetailBase):
    """GET/PATCH/DELETE /locations/admin/<partenaire_id>/vehicules/<vehicule_id>/images/<id>/"""


class MonVehiculePanoramasView(_BienVehicule, _PerimetreLoueurMixin, _PanoramasListCreateBase):
    """GET/POST /locations/mon-espace/vehicules/<vehicule_id>/panoramas/"""


class MonVehiculePanoramaDetailView(_BienVehicule, _PerimetreLoueurMixin, _PanoramaDetailBase):
    """GET/PATCH/DELETE /locations/mon-espace/vehicules/<vehicule_id>/panoramas/<id>/"""


class AdminVehiculePanoramasView(_BienVehicule, _PerimetreAdminMixin, _PanoramasListCreateBase):
    """GET/POST /locations/admin/<partenaire_id>/vehicules/<vehicule_id>/panoramas/"""


class AdminVehiculePanoramaDetailView(_BienVehicule, _PerimetreAdminMixin, _PanoramaDetailBase):
    """GET/PATCH/DELETE /locations/admin/<partenaire_id>/vehicules/<vehicule_id>/panoramas/<id>/"""


# ═══════════════════════════════════════════════════════════════════════
# Vues concrètes — hébergements (V2)
# ═══════════════════════════════════════════════════════════════════════

class MonHebergementsView(_BienHebergement, _PerimetreLoueurMixin, _BiensListCreateBase):
    """GET/POST /locations/mon-espace/hebergements/"""


class MonHebergementDetailView(_BienHebergement, _PerimetreLoueurMixin, _BienDetailBase):
    """GET/PATCH/DELETE /locations/mon-espace/hebergements/<id>/"""


class MonHebergementDisponibiliteView(_BienHebergement, _PerimetreLoueurMixin, _DisponibiliteBase):
    """POST /locations/mon-espace/hebergements/<id>/disponibilite/"""


class AdminHebergementsView(_BienHebergement, _PerimetreAdminMixin, _BiensListCreateBase):
    """GET/POST /locations/admin/<partenaire_id>/hebergements/"""


class AdminHebergementDetailView(_BienHebergement, _PerimetreAdminMixin, _BienDetailBase):
    """GET/PATCH/DELETE /locations/admin/<partenaire_id>/hebergements/<id>/"""


class AdminHebergementDisponibiliteView(_BienHebergement, _PerimetreAdminMixin, _DisponibiliteBase):
    """POST /locations/admin/<partenaire_id>/hebergements/<id>/disponibilite/"""


class MonHebergementImagesView(_BienHebergement, _PerimetreLoueurMixin, _ImagesListCreateBase):
    """GET/POST /locations/mon-espace/hebergements/<hebergement_id>/images/"""


class MonHebergementImageDetailView(_BienHebergement, _PerimetreLoueurMixin, _ImageDetailBase):
    """GET/PATCH/DELETE /locations/mon-espace/hebergements/<hebergement_id>/images/<id>/"""


class AdminHebergementImagesView(_BienHebergement, _PerimetreAdminMixin, _ImagesListCreateBase):
    """GET/POST /locations/admin/<partenaire_id>/hebergements/<hebergement_id>/images/"""


class AdminHebergementImageDetailView(_BienHebergement, _PerimetreAdminMixin, _ImageDetailBase):
    """GET/PATCH/DELETE /locations/admin/<partenaire_id>/hebergements/<hebergement_id>/images/<id>/"""


class MonHebergementPanoramasView(_BienHebergement, _PerimetreLoueurMixin, _PanoramasListCreateBase):
    """GET/POST /locations/mon-espace/hebergements/<hebergement_id>/panoramas/"""


class MonHebergementPanoramaDetailView(_BienHebergement, _PerimetreLoueurMixin, _PanoramaDetailBase):
    """GET/PATCH/DELETE /locations/mon-espace/hebergements/<hebergement_id>/panoramas/<id>/"""


class AdminHebergementPanoramasView(_BienHebergement, _PerimetreAdminMixin, _PanoramasListCreateBase):
    """GET/POST /locations/admin/<partenaire_id>/hebergements/<hebergement_id>/panoramas/"""


class AdminHebergementPanoramaDetailView(_BienHebergement, _PerimetreAdminMixin, _PanoramaDetailBase):
    """GET/PATCH/DELETE /locations/admin/<partenaire_id>/hebergements/<hebergement_id>/panoramas/<id>/"""
