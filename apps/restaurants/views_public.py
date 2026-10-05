"""Lecture publique (préparation Flutter R2). AllowAny — même mur
d'inscription que le reste du catalogue (apps.catalog.views) : on donne
envie avant de demander de s'enregistrer, aucune règle nouvelle."""
from django.db.models import Prefetch
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Article, SectionMenu
from apps.geo.models import Departement
from apps.geo.portee import filtre_visibilite
from apps.users.models import ProfilPartenaire

from . import services
from .serializers import RestaurantDetailPubliqueSerializer, RestaurantListeSerializer, _resume_menu_du_jour


def _departement_demande(request):
    """Département de ?departement=, ou None si absent, non numérique ou
    inconnu — dans ces cas la lecture reste ouverte à tous (règle geo)."""
    brut = request.query_params.get('departement')
    try:
        pk = int(brut)
    except (TypeError, ValueError):
        return None
    return Departement.objects.filter(pk=pk).select_related('region').first()


def _partenaires_restaurants(request):
    qs = (ProfilPartenaire.objects
          .filter(type_partenaire__in=services.TYPES_RESTAURATION,
                  statut=ProfilPartenaire.Statut.ACTIF, est_visible=True)
          .select_related('departement__region', 'localite', 'quartier_geo')
          .filter(filtre_visibilite(_departement_demande(request))))
    partenaires = list(qs)
    fiches = services.fiches_de(partenaires)
    for p in partenaires:
        p.fiche = fiches[p.id]
    return partenaires


class RestaurantsListeView(APIView):
    """GET /api/v1/restaurants/?departement= — liste publique."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        donnees = RestaurantListeSerializer(
            _partenaires_restaurants(request), many=True, context={'request': request}).data
        return Response({'resultats': donnees})


class RestaurantDetailPublicView(APIView):
    """GET /api/v1/restaurants/<id>/ — fiche + menus en vigueur + carte
    complète, en une seule réponse."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk=None):
        partenaire = (ProfilPartenaire.objects
                      .filter(pk=pk, type_partenaire__in=services.TYPES_RESTAURATION)
                      .select_related('departement', 'localite', 'quartier_geo')
                      .prefetch_related('horaires',
                                        Prefetch('sections_menu', queryset=SectionMenu.objects.filter(est_active=True)
                                                 .prefetch_related(Prefetch('articles', queryset=Article.objects.filter(
                                                     est_actif=True).prefetch_related(
                                                         'images', 'variantes', 'groupes_options__options')))))
                      .first())
        if partenaire is None:
            return Response({'erreur': True, 'message': 'Restaurant introuvable.'}, status=404)
        partenaire.fiche = services.fiche_de(partenaire)
        donnees = RestaurantDetailPubliqueSerializer(partenaire, context={'request': request}).data
        return Response(donnees)


class MenusDuJourView(APIView):
    """GET /api/v1/restaurants/menus-du-jour/?departement= — flux « Menus
    du jour » pour l'accueil : un restaurant par entrée, son menu en
    vigueur maintenant s'il y en a un, sinon celui du jour. Restaurants
    sans menu publié du jour : non inclus."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        donnees = []
        for p in _partenaires_restaurants(request):
            resume = _resume_menu_du_jour(p.fiche)
            if resume:
                donnees.append({
                    'partenaire_id': p.id, 'nom': p.nom_commerce,
                    'ville': p.ville, 'menu': resume,
                    **services.statut(p.fiche),
                })
        return Response({'resultats': donnees})
