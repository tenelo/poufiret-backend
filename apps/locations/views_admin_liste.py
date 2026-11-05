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
from .models import ProfilEtablissement

_TYPE_ETABLISSEMENT_DEFAUT = ProfilEtablissement._meta.get_field('type_etablissement').default
_LIBELLES_TYPE_ETABLISSEMENT = dict(ProfilEtablissement.TypeEtablissement.choices)


def _type_etablissement(partenaire):
    """Type d'établissement d'un hôtelier (fiche préchargée), None sinon. Hôtelier sans
    fiche (créée à la 1re ouverture de la gestion) : la valeur par défaut que cette fiche
    prendra, pour que liste et gestion concordent."""
    if partenaire.type_partenaire != ProfilPartenaire.TypePartenaire.HOTELIER:
        return None
    try:
        return partenaire.profil_etablissement.type_etablissement
    except ProfilEtablissement.DoesNotExist:
        return _TYPE_ETABLISSEMENT_DEFAUT


class LoueursAdminListeView(APIView):
    """GET /api/v1/locations/admin/?type_partenaire=&type_etablissement= — tous les
    loueurs (type dans TYPES_LOCATION : maisons, véhicules, hôteliers), avec
    type_partenaire, type_etablissement (hôteliers ; null sinon) et
    indicateurs génériques sur leurs biens (logements, véhicules ou
    hébergements — un hébergement compte pour 1 bien, quel que soit son
    nb_unites) : nb_biens, nb_disponibles, nb_indisponibles (véhicules,
    hébergements), nb_reserves /
    nb_loues (logements), demandes en attente."""
    permission_classes = [permissions.IsAuthenticated, ADroitDe('gerer_locations')]

    def get(self, request):
        p_ = request.query_params
        qs = ProfilPartenaire.objects.filter(type_partenaire__in=services.TYPES_LOCATION)
        type_partenaire = p_.get('type_partenaire')
        if type_partenaire:
            if type_partenaire not in services.TYPES_LOCATION:
                return Response({'erreur': True, 'message':
                                 f'Type de partenaire inconnu (ou non loueur) : {type_partenaire}.'}, status=400)
            qs = qs.filter(type_partenaire=type_partenaire)
        type_etablissement = p_.get('type_etablissement')
        if type_etablissement and type_etablissement not in _LIBELLES_TYPE_ETABLISSEMENT:
            return Response({'erreur': True, 'message':
                             f"Type d'établissement inconnu : {type_etablissement}."}, status=400)
        # profil_etablissement (1-1 inverse) dans la même requête : pas de N+1.
        partenaires = list(qs.select_related('departement', 'profil_etablissement').order_by('nom_commerce'))
        if type_etablissement:
            partenaires = [p for p in partenaires if _type_etablissement(p) == type_etablissement]
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
            type_etab = _type_etablissement(p)
            resultats.append({
                'id': p.id,
                'nom': p.nom_commerce,
                'type_partenaire': p.type_partenaire,
                'type_partenaire_libelle': p.get_type_partenaire_display(),
                'type_etablissement': type_etab,
                'type_etablissement_libelle': _LIBELLES_TYPE_ETABLISSEMENT.get(type_etab) if type_etab else None,
                'departement_nom': getattr(p.departement, 'nom', ''),
                'nb_biens': sum(d.values()),
                'nb_disponibles': d.get('disponible', 0),
                'nb_indisponibles': d.get('indisponible', 0),
                'nb_reserves': d.get('reserve', 0),
                'nb_loues': d.get('loue', 0),
                'demandes_en_attente': attentes.get(p.id, 0),
            })
        return Response({'resultats': resultats})
