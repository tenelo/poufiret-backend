"""Vues admin (CRUD complet) de la géographie — Région / Département /
Localité / Quartier.

Réservées à ADroitDe('gerer_geographie') (super-admin toujours autorisé via
le court-circuit déjà présent dans ADroitDe). Distinctes des vues publiques
(apps.geo.views, INCHANGÉES).

Convention : pagination standard du projet (DEFAULT_PAGINATION_CLASS,
generics.ListCreateAPIView), ?search= sur nom, ?actif=, filtre par parent,
export CSV via apps.core.exports.reponse_csv (mêmes filtres que la liste).
"""
from django.db.models import ProtectedError
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exports import reponse_csv
from apps.core.permissions import ADroitDe
from .admin_serializers import (
    DepartementAdminSerializer, LocaliteAdminSerializer,
    QuartierAdminSerializer, RegionAdminSerializer,
)
from .models import Departement, District, Localite, Quartier, Region

_PERMISSION = [permissions.IsAuthenticated, ADroitDe('gerer_geographie')]


def _vers_bool(valeur, defaut=None):
    if valeur is None:
        return defaut
    return str(valeur).strip().lower() in ('1', 'true', 'vrai', 'oui')


# ── District (lecture seule : options pour le select Région) ─────────

class DistrictOptionsView(APIView):
    """GET /districts/options/?actif= — id+nom pour la liste déroulante du
    formulaire de création d'une Région. Pas de CRUD District (hors
    périmètre) : District n'a pas de champ d'activation, ?actif= est donc
    ignoré et tous les districts sont renvoyés (même format que les autres
    endpoints .../options/)."""
    permission_classes = _PERMISSION

    def get(self, request):
        qs = District.objects.order_by('ordre', 'nom')
        return Response({'resultats': list(qs.values('id', 'nom'))})


# ── Région ──────────────────────────────────────────────────────────

def _regions_qs(request):
    qs = Region.objects.select_related('district').order_by('ordre', 'nom')
    p = request.query_params
    search = p.get('search')
    if search:
        qs = qs.filter(nom__icontains=search)
    actif = _vers_bool(p.get('actif'))
    if actif is not None:
        qs = qs.filter(est_actif=actif)
    district = p.get('district')
    if district:
        qs = qs.filter(district_id=district)
    return qs


class RegionAdminListCreateView(generics.ListCreateAPIView):
    serializer_class = RegionAdminSerializer
    permission_classes = _PERMISSION

    def get_queryset(self):
        return _regions_qs(self.request)


class RegionAdminDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = RegionAdminSerializer
    permission_classes = _PERMISSION
    queryset = Region.objects.all()

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        nb = obj.departements.count()
        if nb:
            return Response(
                {'erreur': True, 'message': (
                    f'Impossible de supprimer : {nb} département(s) y sont '
                    'rattachés. Désactivez-la à la place.')},
                status=409)
        try:
            obj.delete()
        except ProtectedError:
            return Response(
                {'erreur': True, 'message': (
                    'Impossible de supprimer : des éléments y sont '
                    'rattachés. Désactivez-la à la place.')},
                status=409)
        return Response(status=204)


class RegionAdminExportView(APIView):
    permission_classes = _PERMISSION

    def get(self, request):
        qs = _regions_qs(request)
        entetes = ['id', 'nom', 'actif', 'district', 'nb_departements',
                   'cree_le', 'modifie_le']
        lignes = [[
            r.id, r.nom, 'oui' if r.est_actif else 'non', r.district.nom,
            r.departements.count(),
            r.cree_le.strftime('%Y-%m-%d %H:%M:%S') if r.cree_le else '',
            r.modifie_le.strftime('%Y-%m-%d %H:%M:%S') if r.modifie_le else '',
        ] for r in qs]
        return reponse_csv('geo_regions', entetes, lignes)


class RegionOptionsView(APIView):
    """GET /regions/options/ — id+nom pour les listes déroulantes.
    Actifs seulement par défaut ; ?actif=0 pour voir aussi les inactifs."""
    permission_classes = _PERMISSION

    def get(self, request):
        qs = Region.objects.order_by('ordre', 'nom')
        actif = _vers_bool(request.query_params.get('actif'), defaut=True)
        if actif is not None:
            qs = qs.filter(est_actif=actif)
        return Response({'resultats': list(qs.values('id', 'nom'))})


# ── Département ─────────────────────────────────────────────────────

def _departements_qs(request):
    qs = Departement.objects.select_related('region__district').order_by('ordre', 'nom')
    p = request.query_params
    search = p.get('search')
    if search:
        qs = qs.filter(nom__icontains=search)
    actif = _vers_bool(p.get('actif'))
    if actif is not None:
        qs = qs.filter(est_actif=actif)
    region = p.get('region')
    if region:
        qs = qs.filter(region_id=region)
    return qs


class DepartementAdminListCreateView(generics.ListCreateAPIView):
    serializer_class = DepartementAdminSerializer
    permission_classes = _PERMISSION

    def get_queryset(self):
        return _departements_qs(self.request)


class DepartementAdminDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = DepartementAdminSerializer
    permission_classes = _PERMISSION
    queryset = Departement.objects.all()

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        nb = obj.localites.count()
        if nb:
            return Response(
                {'erreur': True, 'message': (
                    f'Impossible de supprimer : {nb} localité(s) y sont '
                    'rattachées. Désactivez-le à la place.')},
                status=409)
        try:
            obj.delete()
        except ProtectedError:
            return Response(
                {'erreur': True, 'message': (
                    'Impossible de supprimer : des éléments (comptes, '
                    'partenaires, livraison...) y sont rattachés. '
                    'Désactivez-le à la place.')},
                status=409)
        return Response(status=204)


class DepartementAdminExportView(APIView):
    permission_classes = _PERMISSION

    def get(self, request):
        qs = _departements_qs(request)
        entetes = ['id', 'nom', 'actif', 'region', 'district', 'nb_localites',
                   'cree_le', 'modifie_le']
        lignes = [[
            d.id, d.nom, 'oui' if d.est_actif else 'non', d.region.nom,
            d.region.district.nom, d.localites.count(),
            d.cree_le.strftime('%Y-%m-%d %H:%M:%S') if d.cree_le else '',
            d.modifie_le.strftime('%Y-%m-%d %H:%M:%S') if d.modifie_le else '',
        ] for d in qs]
        return reponse_csv('geo_departements', entetes, lignes)


class DepartementOptionsView(APIView):
    """GET /departements/options/?region=<id> — id+nom, filtrable par région."""
    permission_classes = _PERMISSION

    def get(self, request):
        qs = Departement.objects.order_by('ordre', 'nom')
        actif = _vers_bool(request.query_params.get('actif'), defaut=True)
        if actif is not None:
            qs = qs.filter(est_actif=actif)
        region = request.query_params.get('region')
        if region:
            qs = qs.filter(region_id=region)
        return Response({'resultats': list(qs.values('id', 'nom'))})


# ── Localité ────────────────────────────────────────────────────────

def _localites_qs(request):
    qs = Localite.objects.select_related(
        'departement__region__district').order_by('ordre', 'nom')
    p = request.query_params
    search = p.get('search')
    if search:
        qs = qs.filter(nom__icontains=search)
    actif = _vers_bool(p.get('actif'))
    if actif is not None:
        qs = qs.filter(est_actif=actif)
    departement = p.get('departement')
    if departement:
        qs = qs.filter(departement_id=departement)
    return qs


class LocaliteAdminListCreateView(generics.ListCreateAPIView):
    serializer_class = LocaliteAdminSerializer
    permission_classes = _PERMISSION

    def get_queryset(self):
        return _localites_qs(self.request)


class LocaliteAdminDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = LocaliteAdminSerializer
    permission_classes = _PERMISSION
    queryset = Localite.objects.all()

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        nb = obj.quartiers.count()
        if nb:
            return Response(
                {'erreur': True, 'message': (
                    f'Impossible de supprimer : {nb} quartier(s) y sont '
                    'rattachés. Désactivez-la à la place.')},
                status=409)
        try:
            obj.delete()
        except ProtectedError:
            return Response(
                {'erreur': True, 'message': (
                    'Impossible de supprimer : des éléments y sont '
                    'rattachés. Désactivez-la à la place.')},
                status=409)
        return Response(status=204)


class LocaliteAdminExportView(APIView):
    permission_classes = _PERMISSION

    def get(self, request):
        qs = _localites_qs(request)
        entetes = ['id', 'nom', 'actif', 'departement', 'region', 'nb_quartiers',
                   'cree_le', 'modifie_le']
        lignes = [[
            l.id, l.nom, 'oui' if l.est_actif else 'non', l.departement.nom,
            l.departement.region.nom, l.quartiers.count(),
            l.cree_le.strftime('%Y-%m-%d %H:%M:%S') if l.cree_le else '',
            l.modifie_le.strftime('%Y-%m-%d %H:%M:%S') if l.modifie_le else '',
        ] for l in qs]
        return reponse_csv('geo_localites', entetes, lignes)


class LocaliteOptionsView(APIView):
    """GET /localites/options/?departement=<id> — id+nom, filtrable."""
    permission_classes = _PERMISSION

    def get(self, request):
        qs = Localite.objects.order_by('ordre', 'nom')
        actif = _vers_bool(request.query_params.get('actif'), defaut=True)
        if actif is not None:
            qs = qs.filter(est_actif=actif)
        departement = request.query_params.get('departement')
        if departement:
            qs = qs.filter(departement_id=departement)
        return Response({'resultats': list(qs.values('id', 'nom'))})


# ── Quartier ────────────────────────────────────────────────────────

def _quartiers_qs(request):
    qs = Quartier.objects.select_related(
        'localite__departement__region__district').order_by('ordre', 'nom')
    p = request.query_params
    search = p.get('search')
    if search:
        qs = qs.filter(nom__icontains=search)
    actif = _vers_bool(p.get('actif'))
    if actif is not None:
        qs = qs.filter(est_actif=actif)
    localite = p.get('localite')
    if localite:
        qs = qs.filter(localite_id=localite)
    return qs


class QuartierAdminListCreateView(generics.ListCreateAPIView):
    serializer_class = QuartierAdminSerializer
    permission_classes = _PERMISSION

    def get_queryset(self):
        return _quartiers_qs(self.request)


class QuartierAdminDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = QuartierAdminSerializer
    permission_classes = _PERMISSION
    queryset = Quartier.objects.all()

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        # Niveau le plus fin : jamais d'enfants, seul un ProtectedError
        # externe imprevu pourrait bloquer.
        try:
            obj.delete()
        except ProtectedError:
            return Response(
                {'erreur': True, 'message': (
                    'Impossible de supprimer : des éléments y sont '
                    'rattachés. Désactivez-le à la place.')},
                status=409)
        return Response(status=204)


class QuartierAdminExportView(APIView):
    permission_classes = _PERMISSION

    def get(self, request):
        qs = _quartiers_qs(request)
        entetes = ['id', 'nom', 'actif', 'localite', 'departement', 'region',
                   'cree_le', 'modifie_le']
        lignes = [[
            q.id, q.nom, 'oui' if q.est_actif else 'non', q.localite.nom,
            q.localite.departement.nom, q.localite.departement.region.nom,
            q.cree_le.strftime('%Y-%m-%d %H:%M:%S') if q.cree_le else '',
            q.modifie_le.strftime('%Y-%m-%d %H:%M:%S') if q.modifie_le else '',
        ] for q in qs]
        return reponse_csv('geo_quartiers', entetes, lignes)


class QuartierOptionsView(APIView):
    """GET /quartiers/options/?localite=<id> — id+nom, filtrable."""
    permission_classes = _PERMISSION

    def get(self, request):
        qs = Quartier.objects.order_by('ordre', 'nom')
        actif = _vers_bool(request.query_params.get('actif'), defaut=True)
        if actif is not None:
            qs = qs.filter(est_actif=actif)
        localite = request.query_params.get('localite')
        if localite:
            qs = qs.filter(localite_id=localite)
        return Response({'resultats': list(qs.values('id', 'nom'))})
