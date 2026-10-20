"""Liste admin des restaurants avec indicateurs — pas d'équivalent côté
restaurateur (qui n'a que le sien), donc hors du pairing Mon*/Admin* de
views_prive.py."""
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import ADroitDe
from apps.orders.models import Commande
from apps.users.models import ProfilPartenaire

from . import gabarits, services
from .models import ProfilRestaurant


class RestaurantsAdminListeView(APIView):
    """GET /api/v1/restaurants/admin/?gabarit= — tous les établissements du
    moteur (type dans TYPES_MOTEUR : restaurants, fast-foods, boulangeries,
    pharmacies, mode, librairies), avec type_partenaire, gabarit et
    indicateurs : commandes du jour, menu du jour publié ou non, ouvert ou
    fermé."""
    permission_classes = [permissions.IsAuthenticated, ADroitDe('gerer_restaurants')]

    def get(self, request):
        types = services.TYPES_MOTEUR
        gabarit = request.query_params.get('gabarit')
        if gabarit:
            types = [t for t in types if gabarits.gabarit_de_type(t) == gabarit]
        partenaires = list(
            ProfilPartenaire.objects.filter(type_partenaire__in=types)
            .select_related('profil_restaurant', 'departement').order_by('nom_commerce'))
        aujourdhui = timezone.localdate()
        commandes_jour = dict(
            Commande.objects.filter(
                partenaire_id__in=[p.id for p in partenaires],
                created_at__date=aujourdhui,
            ).values('partenaire_id').annotate(n=Count('id')).values_list('partenaire_id', 'n'))

        resultats = []
        for p in partenaires:
            fiche = getattr(p, 'profil_restaurant', None)
            menu_publie = False
            ouvert = False
            if fiche is not None:
                menu_publie = any(services.menus_du_jour(fiche).values())
                ouvert = services.est_ouvert(fiche)
            resultats.append({
                'id': p.id,
                'nom': p.nom_commerce,
                'type_partenaire': p.type_partenaire,
                'gabarit': gabarits.gabarit_de(p),
                'departement_nom': getattr(p.departement, 'nom', ''),
                'a_une_fiche': fiche is not None,
                'ouvert': ouvert,
                'menu_du_jour_publie': menu_publie,
                'commandes_du_jour': commandes_jour.get(p.id, 0),
            })
        return Response({'resultats': resultats})
