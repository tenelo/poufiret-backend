"""Liste admin paginée des publicités, compteurs par statut et vue par
partenaire (admin Angular, plusieurs milliers de pubs).

GET /api/v1/publicites/admin/liste/       liste paginée + compteurs_statut
GET /api/v1/publicites/admin/compteurs/   compteurs par statut seuls
GET /api/v1/publicites/admin/partenaires/ partenaires ayant au moins une pub

Mêmes filtres que admin/stats/ (_publicites_admin_qs) : statut, formule,
partenaire, search, portee, date_debut, date_fin, origine. Brouillons
toujours exclus. Droit voir_stats (super-admin toujours autorisé).
admin/stats/ reste inchangé (liste complète, format historique).

Aucune requête par ligne : lignes construites par stats.lignes_admin
(reconduction annotée, impressions par type groupées en une requête).
"""
from django.db.models import Count, F, Max, Q, Sum
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import StandardPagination
from apps.core.permissions import ADroitDe

from .models import Publicite
from .services import annoter_reconduction
from .stats import _compteurs_statut, _publicites_admin_qs, lignes_admin

STATUTS_ADMIN = [v for v, _ in Publicite.Statut.choices if v != Publicite.Statut.BROUILLON]

# ?ordre= public -> champ (préfixe - : descendant)
ORDRES_LISTE = {
    'cree_le': 'cree_le',
    'debut_diffusion': 'debut_diffusion',
    'fin_diffusion': 'fin_diffusion',
    'affichages': 'nb_impressions',
    'clics': 'nb_clics',
    'partenaire': 'partenaire__nom_commerce',
    'titre': 'titre',
}
ORDRES_PARTENAIRES = {
    'nom': 'nom_commerce',
    'nb_publicites': 'nb_publicites',
    'affichages': 'total_affichages',
    'clics': 'total_clics',
    'derniere_pub': 'derniere_pub_le',
}


class PaginationListeAdmin(StandardPagination):
    """25 par défaut, ?page_size= jusqu'à 100 ; format DRF (count, next,
    previous, results)."""
    page_size = 25


def _erreur(message):
    return Response({'erreur': True, 'message': message}, status=status.HTTP_400_BAD_REQUEST)


def _tri(request, ordres, defaut, departage):
    """(liste d'expressions order_by, erreur). Valeurs vides en dernier
    (dans les deux sens) ; `departage` rend l'ordre stable entre les pages."""
    brut = (request.query_params.get('ordre') or defaut).strip()
    desc = brut.startswith('-')
    cle = brut.lstrip('-')
    if cle not in ordres:
        return None, (f'Ordre inconnu : « {brut} ». Valeurs possibles : '
                      f'{", ".join(ordres)} (préfixe - pour décroissant).')
    champ = F(ordres[cle])
    expr = champ.desc(nulls_last=True) if desc else champ.asc(nulls_last=True)
    return [expr, departage], None


class ListePublicitesAdminView(APIView):
    """GET admin/liste/?page=&page_size=&ordre=&statut=&partenaire=&search=
    &date_debut=&date_fin=&formule=&origine=&portee=

    ordre : cree_le, debut_diffusion, fin_diffusion, affichages, clics,
    partenaire, titre (préfixe - : décroissant ; défaut -cree_le ; dates
    vides en dernier ; départage par id). Ordre inconnu -> 400.
    Réponse : {count, next, previous, results: [lignes de admin/stats/],
    compteurs_statut} ; compteurs_statut ignore le filtre statut.
    """
    permission_classes = [permissions.IsAuthenticated, ADroitDe('voir_stats')]

    def get(self, request):
        pubs, erreur = _publicites_admin_qs(request)
        if erreur:
            return _erreur(erreur)
        ordre, erreur = _tri(request, ORDRES_LISTE, '-cree_le', 'id')
        if erreur:
            return _erreur(erreur)
        pubs = annoter_reconduction(pubs.order_by(*ordre))
        paginateur = PaginationListeAdmin()
        page = list(paginateur.paginate_queryset(pubs, request, view=self))
        reponse = paginateur.get_paginated_response(lignes_admin(page, request))
        reponse.data['compteurs_statut'] = _compteurs_statut(request)
        return reponse


class CompteursPublicitesAdminView(APIView):
    """GET admin/compteurs/ (mêmes filtres que admin/liste/, statut ignoré)
    -> {compteurs_statut: {<statut>: n, ..., total}} pour les badges des
    onglets, sans recharger la liste. 1 requête."""
    permission_classes = [permissions.IsAuthenticated, ADroitDe('voir_stats')]

    def get(self, request):
        _, erreur = _publicites_admin_qs(request, avec_statut=False)
        if erreur:
            return _erreur(erreur)
        return Response({'compteurs_statut': _compteurs_statut(request)})


class PartenairesPublicitesAdminView(APIView):
    """GET admin/partenaires/?page=&page_size=&search=<nom>&ordre=
    &formule=&date_debut=&date_fin=&origine=&portee=

    Partenaires ayant au moins une pub (hors brouillons) correspondant aux
    filtres ; search = nom du commerce. ordre : nom, nb_publicites,
    affichages, clics, derniere_pub (préfixe - ; défaut -derniere_pub).
    Ligne : {partenaire_id, nom_commerce, telephone, nb_publicites,
    par_statut, total_affichages, total_clics, derniere_pub_le}.
    1 requête agrégée (+ le comptage de la pagination).
    """
    permission_classes = [permissions.IsAuthenticated, ADroitDe('voir_stats')]

    def get(self, request):
        pubs, erreur = _publicites_admin_qs(request, avec_statut=False, avec_search=False)
        if erreur:
            return _erreur(erreur)
        ordre, erreur = _tri(request, ORDRES_PARTENAIRES, '-derniere_pub', 'partenaire_id')
        if erreur:
            return _erreur(erreur)
        search = (request.query_params.get('search') or '').strip()
        if search:
            pubs = pubs.filter(partenaire__nom_commerce__icontains=search)
        lignes = (pubs.order_by()
                  .values('partenaire_id')
                  .annotate(nom_commerce=F('partenaire__nom_commerce'),
                            telephone=F('partenaire__user__telephone'),
                            nb_publicites=Count('id'),
                            total_affichages=Sum('nb_impressions'),
                            total_clics=Sum('nb_clics'),
                            derniere_pub_le=Max('cree_le'),
                            **{f'n_{s}': Count('id', filter=Q(statut=s)) for s in STATUTS_ADMIN})
                  .order_by(*ordre))
        paginateur = PaginationListeAdmin()
        page = paginateur.paginate_queryset(lignes, request, view=self)
        return paginateur.get_paginated_response([{
            'partenaire_id': x['partenaire_id'],
            'nom_commerce': x['nom_commerce'],
            'telephone': x['telephone'],
            'nb_publicites': x['nb_publicites'],
            'par_statut': {s: x[f'n_{s}'] for s in STATUTS_ADMIN},
            'total_affichages': x['total_affichages'] or 0,
            'total_clics': x['total_clics'] or 0,
            'derniere_pub_le': x['derniere_pub_le'],
        } for x in page])
