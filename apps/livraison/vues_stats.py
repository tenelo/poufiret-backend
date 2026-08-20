"""Statistiques TeneLivr, cloisonnées par niveau hiérarchique.

Réutilise la logique riche de apps.analytics.stats_livraison (déjà
utilisée par le tableau de bord admin, apps.analytics.views) : ce module
ne réimplémente aucun calcul, il choisit juste le bon `ville_id` à passer
selon qui appelle, et — pour le coordonnateur — ajoute la ventilation
inter-villes via `stats_par_ville`.

Regroupé dans apps/livraison/ pour rester avec le reste du module TeneLivr,
même si la logique de calcul elle-même vit dans apps.analytics (pas de
duplication : cf. la note d'isolation dans vues_bureau.py — ici on importe
volontairement `_bornes_periode`, seul point de couplage vers analytics,
demandé explicitement pour ne pas dupliquer le parsing de dates).
"""
from apps.analytics.stats_livraison import (_courses_periode, stats_par_ville,
                                            tableau_de_bord)
from apps.analytics.views import _bornes_periode
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import EstCoordonnateurLivraison, EstPersonnelLivraison
from .vues_bureau import _parser_ville


def _est_coordonnateur(user):
    return user.is_superuser or user.role == user.Role.COORDONNATEUR_LIVRAISON


class StatsBureauView(APIView):
    """GET /livraison/stats/bureau/?debut=&fin= — stats de la ville du
    personnel connecté (gestionnaire ou superviseur).

    La ville n'est jamais lue du body/query : elle est forcée à celle du
    profil_livraison de l'acteur. Un coordonnateur qui appelle cet
    endpoint reçoit les stats nationales (toutes villes) plutôt qu'une
    erreur — /livraison/stats/coordonnateur/ reste l'endpoint dédié pour
    la vue nationale enrichie (ventilation par ville).
    """
    permission_classes = [IsAuthenticated, EstPersonnelLivraison]

    def get(self, request):
        debut, fin, erreur = _bornes_periode(request)
        if erreur:
            return Response({'detail': 'Format de date invalide (attendu YYYY-MM-DD).'},
                            status=400)

        if _est_coordonnateur(request.user):
            ville_id = None
        else:
            ville_id = request.user.profil_livraison.departement_id

        return Response(tableau_de_bord(debut, fin, ville_id=ville_id), status=200)


class StatsCoordonnateurView(APIView):
    """GET /livraison/stats/coordonnateur/?debut=&fin=&ville=<id optionnel>

    Vue nationale (coordonnateur uniquement) :
    - ?ville=<id> fourni  -> stats de cette seule ville.
    - ?ville= absent      -> stats toutes villes + `ventilation_par_ville`
      (nb courses, CA par département) pour comparer les villes.
    """
    permission_classes = [IsAuthenticated, EstCoordonnateurLivraison]

    def get(self, request):
        debut, fin, erreur = _bornes_periode(request)
        if erreur:
            return Response({'detail': 'Format de date invalide (attendu YYYY-MM-DD).'},
                            status=400)

        ville_id, erreur_ville = _parser_ville(request)
        if erreur_ville:
            return Response({'erreur': True, 'message': erreur_ville}, status=400)

        if ville_id is not None:
            return Response(tableau_de_bord(debut, fin, ville_id=ville_id), status=200)

        resultat = tableau_de_bord(debut, fin, ville_id=None)
        resultat['ventilation_par_ville'] = stats_par_ville(
            _courses_periode(debut, fin))
        return Response(resultat, status=200)
