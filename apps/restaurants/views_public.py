"""Lecture publique (préparation Flutter R2). AllowAny — même mur
d'inscription que le reste du catalogue (apps.catalog.views) : on donne
envie avant de demander de s'enregistrer, aucune règle nouvelle."""
from django.db.models import Count, Prefetch, Q, prefetch_related_objects
from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Article, SectionMenu
from apps.geo.models import Departement
from apps.geo.portee import filtre_visibilite
from apps.users.models import ProfilPartenaire

from . import gabarits, services
from .serializers import (
    ProduitDetailPubliqueSerializer, ProduitPubliqueSerializer, RestaurantDetailPubliqueSerializer,
    RestaurantListeSerializer, _resume_menu_du_jour,
)


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


_PRODUITS_PREFETCH = ('images', 'variantes', 'groupes_options__options')

# Produits visibles du public : actifs, hors « réservés aux menus ».
_FILTRE_PRODUIT_PUBLIC = Q(est_actif=True, est_reserve_aux_menus=False)


class RestaurantDetailPublicView(APIView):
    """GET /api/v1/restaurants/<id>/ — fiche + menus en vigueur + carte
    complète, en une seule réponse. Tous les types du moteur (gabarits) ;
    pour un gabarit à pagination publique, la carte ne contient que les
    sections (+ nb_produits) : produits sur /restaurants/<id>/produits/."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk=None):
        partenaire = (ProfilPartenaire.objects
                      .filter(pk=pk, type_partenaire__in=services.TYPES_MOTEUR)
                      .select_related('departement', 'localite', 'quartier_geo').first())
        if partenaire is None:
            return Response({'erreur': True, 'message': 'Restaurant introuvable.'}, status=404)
        sections = SectionMenu.objects.filter(est_active=True)
        if gabarits.definition(gabarits.gabarit_de(partenaire))['pagination_publique']:
            sections = sections.annotate(nb_produits=Count(
                'articles', filter=Q(articles__est_actif=True, articles__est_reserve_aux_menus=False)))
        else:
            sections = sections.prefetch_related(Prefetch(
                'articles', queryset=Article.objects.filter(est_actif=True)
                .prefetch_related(*_PRODUITS_PREFETCH)))
        prefetch_related_objects([partenaire], 'horaires', Prefetch('sections_menu', queryset=sections))
        partenaire.fiche = services.fiche_de(partenaire)
        donnees = RestaurantDetailPubliqueSerializer(partenaire, context={'request': request}).data
        return Response(donnees)


class _PaginationProduits(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


def _produits_publics():
    """Produits publics des partenaires du moteur : actifs, hors « réservés
    aux menus », sans section ou dans une section active ; relations
    préchargées (requêtes constantes)."""
    return (Article.objects.filter(_FILTRE_PRODUIT_PUBLIC,
                                   partenaire__type_partenaire__in=services.TYPES_MOTEUR)
            .filter(Q(section_menu__isnull=True) | Q(section_menu__est_active=True))
            .select_related('partenaire', 'section_menu')
            .prefetch_related(*_PRODUITS_PREFETCH))


class ProduitsPublicView(APIView):
    """GET /api/v1/restaurants/<id>/produits/?section=&q=&page=&page_size=20
    → {count, next, previous, results}. q : nom, description et champs texte
    de fiche_specifique (auteur, isbn, marque, laboratoire, dosage).
    Requêtes constantes (relations préchargées)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk=None):
        partenaire = get_object_or_404(
            ProfilPartenaire, pk=pk, type_partenaire__in=services.TYPES_MOTEUR)
        qs = _produits_publics().filter(partenaire=partenaire)
        p = request.query_params
        if p.get('section'):
            try:
                qs = qs.filter(section_menu_id=int(p['section']))
            except ValueError:
                return Response({'erreur': True, 'message': 'section invalide.'}, status=400)
        terme = (p.get('q') or '').strip()
        if terme:
            filtre = Q(nom__icontains=terme) | Q(description__icontains=terme)
            for cle in gabarits.CHAMPS_RECHERCHE:
                filtre |= Q(**{f'fiche_specifique__{cle}__icontains': terme})
            qs = qs.filter(filtre)
        qs = qs.order_by('section_menu__ordre', 'ordre', 'nom', 'id')
        pagination = _PaginationProduits()
        page = pagination.paginate_queryset(qs, request, view=self)
        contexte = {'request': request, 'gabarit': gabarits.gabarit_de(partenaire)}
        return pagination.get_paginated_response(
            ProduitPubliqueSerializer(page, many=True, context=contexte).data)


class ProduitDetailPublicView(APIView):
    """GET /api/v1/restaurants/produits/<id>/ — produit complet + images
    (principale en premier) + autres_produits (6 au plus, même section)."""
    permission_classes = [permissions.AllowAny]
    NB_AUTRES = 6

    def get(self, request, pk=None):
        produit = _produits_publics().filter(pk=pk).first()
        if produit is None:
            return Response({'erreur': True, 'message': 'Produit introuvable.'}, status=404)
        contexte = {'request': request, 'gabarit': gabarits.gabarit_de(produit.partenaire)}
        donnees = ProduitDetailPubliqueSerializer(produit, context=contexte).data
        autres = []
        if produit.section_menu_id:
            autres = list(_produits_publics().filter(
                partenaire_id=produit.partenaire_id, section_menu_id=produit.section_menu_id)
                .exclude(pk=produit.pk).order_by('ordre', 'nom', 'id')[:self.NB_AUTRES])
        donnees['autres_produits'] = ProduitPubliqueSerializer(autres, many=True, context=contexte).data
        return Response(donnees)


class MetaGabaritsView(APIView):
    """GET /api/v1/restaurants/meta/gabarits/ — définition de chaque
    gabarit (source unique apps.restaurants.gabarits.GABARITS)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response(gabarits.GABARITS)


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
