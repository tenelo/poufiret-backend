"""Liste admin des loueurs avec indicateurs — pas d'équivalent côté loueur
(qui n'a que le sien), donc hors du pairing Mon*/Admin* de views_prive.py."""
from django.db.models import Count
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Article, Hebergement, Logement, Vehicule
from apps.core.permissions import ADroitDe
from apps.users.models import ProfilPartenaire

from . import services


class LoueursAdminListeView(APIView):
    """GET /api/v1/locations/admin/ — tous les loueurs (type dans
    TYPES_LOCATION : maisons, véhicules, hôteliers), avec type_partenaire et
    indicateurs génériques sur leurs biens (logements, véhicules ou
    hébergements — un hébergement compte pour 1 bien, quel que soit son
    nb_unites) : nb_biens, nb_disponibles, nb_indisponibles (véhicules,
    hébergements), nb_reserves /
    nb_loues (logements), demandes en attente."""
    permission_classes = [permissions.IsAuthenticated, ADroitDe('gerer_locations')]

    def get(self, request):
        partenaires = list(
            ProfilPartenaire.objects.filter(type_partenaire__in=services.TYPES_LOCATION)
            .select_related('departement').order_by('nom_commerce'))
        ids = [p.id for p in partenaires]

        compteurs = {}
        for modele, type_article in ((Logement, Article.Type.LOGEMENT), (Vehicule, Article.Type.VEHICULE),
                                     (Hebergement, Article.Type.HEBERGEMENT)):
            lignes = (modele.objects.filter(article__partenaire_id__in=ids, article__type=type_article)
                      .values('article__partenaire_id', 'disponibilite')
                      .annotate(n=Count('article_id')))
            for ligne in lignes:
                d = compteurs.setdefault(ligne['article__partenaire_id'], {})
                d[ligne['disponibilite']] = d.get(ligne['disponibilite'], 0) + ligne['n']

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
            d = compteurs.get(p.id, {})
            resultats.append({
                'id': p.id,
                'nom': p.nom_commerce,
                'type_partenaire': p.type_partenaire,
                'type_partenaire_libelle': p.get_type_partenaire_display(),
                'departement_nom': getattr(p.departement, 'nom', ''),
                'nb_biens': sum(d.values()),
                'nb_disponibles': d.get('disponible', 0),
                'nb_indisponibles': d.get('indisponible', 0),
                'nb_reserves': d.get('reserve', 0),
                'nb_loues': d.get('loue', 0),
                'demandes_en_attente': attentes.get(p.id, 0),
            })
        return Response({'resultats': resultats})
