"""Liste admin des loueurs avec indicateurs — pas d'équivalent côté loueur
(qui n'a que le sien), donc hors du pairing Mon*/Admin* de views_prive.py."""
from django.db.models import Count
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Article, Logement
from apps.core.permissions import ADroitDe
from apps.users.models import ProfilPartenaire

from . import services


class LoueursAdminListeView(APIView):
    """GET /api/v1/locations/admin/ — tous les loueurs (type dans
    TYPES_LOCATION), avec indicateurs : logements disponibles/réservés/
    loués, demandes en attente."""
    permission_classes = [permissions.IsAuthenticated, ADroitDe('gerer_locations')]

    def get(self, request):
        partenaires = list(
            ProfilPartenaire.objects.filter(type_partenaire__in=services.TYPES_LOCATION)
            .select_related('departement').order_by('nom_commerce'))
        ids = [p.id for p in partenaires]

        dispo_brut = (Logement.objects.filter(article__partenaire_id__in=ids, article__type=Article.Type.LOGEMENT)
                      .values('article__partenaire_id', 'disponibilite')
                      .annotate(n=Count('article_id')))
        dispo = {}
        for ligne in dispo_brut:
            d = dispo.setdefault(ligne['article__partenaire_id'], {'disponible': 0, 'reserve': 0, 'loue': 0})
            d[ligne['disponibilite']] = ligne['n']

        attentes = {}
        try:
            from apps.reservations.models import DemandeReservation
            attentes = dict(
                DemandeReservation.objects.filter(partenaire_id__in=ids, statut__in=['nouvelle', 'en_cours'])
                .values('partenaire_id').annotate(n=Count('id')).values_list('partenaire_id', 'n'))
        except Exception:
            pass

        resultats = []
        for p in partenaires:
            d = dispo.get(p.id, {'disponible': 0, 'reserve': 0, 'loue': 0})
            resultats.append({
                'id': p.id,
                'nom': p.nom_commerce,
                'departement_nom': getattr(p.departement, 'nom', ''),
                'nb_disponibles': d['disponible'],
                'nb_reserves': d['reserve'],
                'nb_loues': d['loue'],
                'demandes_en_attente': attentes.get(p.id, 0),
            })
        return Response({'resultats': resultats})
