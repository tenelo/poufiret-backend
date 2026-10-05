"""Vues privées du module restaurants : fiche, horaires, téléphones, carte
(sections/plats réutilisent apps.catalog, inchangé) et menus programmés.

Mêmes vues et serializers pour les deux espaces (décision 6A) : chaque
ressource a une classe de base portant toute la logique, et deux
sous-classes minces qui ne différent que par `get_restaurant()` et les
permissions — restaurateur (son propre restaurant) ou admin
(`<partenaire_id>` de l'URL, capacité gerer_restaurants).
"""
from django.db.models import Prefetch
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import ADroitDe
from apps.users.models import HoraireOuverture, ProfilPartenaire

from . import services
from .models import ActeurRole, LigneMenu, MenuProgramme, ProfilRestaurant, TelephoneRestaurant
from .serializers import (
    HoraireOuvertureSerializer, LigneMenuSerializer, MenuProgrammeSerializer,
    ProfilRestaurantSerializer, TelephoneRestaurantSerializer,
)


def _journaliser_admin(acteur, partenaire, action, motif):
    try:
        from apps.administration.moderation import _journaliser
        _journaliser(acteur, partenaire.user, action, motif)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# Mixin de périmètre : résout le ProfilPartenaire cible + trace l'acteur
# ═══════════════════════════════════════════════════════════════════════

class _PerimetreRestaurateurMixin:
    """Le restaurateur gère son propre restaurant."""
    permission_classes = [permissions.IsAuthenticated]
    acteur_role = ActeurRole.RESTAURATEUR

    def get_partenaire(self):
        profil = getattr(self.request.user, 'profil_partenaire', None)
        if profil is None or profil.type_partenaire not in services.TYPES_RESTAURATION:
            raise PermissionDenied('Réservé aux restaurateurs.')
        return profil

    def acteur_nom(self):
        u = self.request.user
        return u.get_full_name() or u.username or u.telephone


class _PerimetreAdminMixin:
    """L'admin gère le restaurant d'un partenaire donné (<partenaire_id>)."""
    permission_classes = [permissions.IsAuthenticated, ADroitDe('gerer_restaurants')]
    acteur_role = ActeurRole.ADMIN

    def get_partenaire(self):
        partenaire = ProfilPartenaire.objects.filter(
            pk=self.kwargs['partenaire_id'],
            type_partenaire__in=services.TYPES_RESTAURATION).first()
        if partenaire is None:
            from django.http import Http404
            raise Http404('Restaurant introuvable.')
        return partenaire

    def acteur_nom(self):
        u = self.request.user
        return u.get_full_name() or u.username or u.telephone


def _get_or_create_fiche(partenaire):
    fiche, _cree = ProfilRestaurant.objects.get_or_create(partenaire=partenaire)
    return fiche


# ═══════════════════════════════════════════════════════════════════════
# FICHE
# ═══════════════════════════════════════════════════════════════════════

class _FicheRestaurantBase(generics.RetrieveUpdateAPIView):
    serializer_class = ProfilRestaurantSerializer

    def get_object(self):
        return _get_or_create_fiche(self.get_partenaire())

    def perform_update(self, serializer):
        fiche = serializer.save(modifie_par_role=self.acteur_role,
                                modifie_par_nom=self.acteur_nom())
        if self.acteur_role == ActeurRole.ADMIN:
            _journaliser_admin(
                self.request.user, fiche.partenaire, 'resto_fiche_modif',
                f'Fiche de « {fiche.partenaire.nom_commerce} » modifiée par l\'admin.')


class MonFicheRestaurantView(_PerimetreRestaurateurMixin, _FicheRestaurantBase):
    """GET/PATCH /restaurants/mon-restaurant/fiche/"""


class AdminFicheRestaurantView(_PerimetreAdminMixin, _FicheRestaurantBase):
    """GET/PATCH /restaurants/admin/<partenaire_id>/fiche/"""


# ═══════════════════════════════════════════════════════════════════════
# HORAIRES (remplacement complet de la semaine, upsert par jour_semaine)
# ═══════════════════════════════════════════════════════════════════════

class _HorairesBase(APIView):
    """GET : liste (0=lundi..6=dimanche, HoraireOuverture, réutilisé).
    PUT {"horaires": [{jour_semaine, ouvert, heure_ouverture?, heure_fermeture?,
    pause_debut?, pause_fin?, note?}, ...]} — remplace l'intégralité de la
    semaine (upsert par jour_semaine, les jours absents de la liste ne sont
    PAS touchés — pour n'envoyer que les jours modifiés si besoin)."""

    def get(self, request, *args, **kwargs):
        partenaire = self.get_partenaire()
        qs = partenaire.horaires.order_by('jour_semaine')
        return Response(HoraireOuvertureSerializer(qs, many=True).data)

    def put(self, request, *args, **kwargs):
        partenaire = self.get_partenaire()
        lignes = request.data.get('horaires', [])
        resultat = []
        for ligne in lignes:
            jour = ligne.get('jour_semaine')
            if jour is None or not (0 <= int(jour) <= 6):
                return Response(
                    {'erreur': True, 'message': 'jour_semaine doit être entre 0 (lundi) et 6 (dimanche).'},
                    status=status.HTTP_400_BAD_REQUEST)
            horaire, _c = HoraireOuverture.objects.update_or_create(
                partenaire=partenaire, jour_semaine=jour,
                defaults={
                    'ouvert': ligne.get('ouvert', True),
                    'heure_ouverture': ligne.get('heure_ouverture'),
                    'heure_fermeture': ligne.get('heure_fermeture'),
                    'pause_debut': ligne.get('pause_debut'),
                    'pause_fin': ligne.get('pause_fin'),
                    'note': ligne.get('note', ''),
                })
            resultat.append(horaire)
        if self.acteur_role == ActeurRole.ADMIN and resultat:
            _journaliser_admin(
                request.user, partenaire, 'resto_fiche_modif',
                f'Horaires de « {partenaire.nom_commerce} » modifiés par l\'admin.')
        return Response(HoraireOuvertureSerializer(
            partenaire.horaires.order_by('jour_semaine'), many=True).data)


class MonHorairesRestaurantView(_PerimetreRestaurateurMixin, _HorairesBase):
    """GET/PUT /restaurants/mon-restaurant/horaires/"""


class AdminHorairesRestaurantView(_PerimetreAdminMixin, _HorairesBase):
    """GET/PUT /restaurants/admin/<partenaire_id>/horaires/"""


# ═══════════════════════════════════════════════════════════════════════
# TÉLÉPHONES
# ═══════════════════════════════════════════════════════════════════════

class _TelephonesListCreateBase(generics.ListCreateAPIView):
    serializer_class = TelephoneRestaurantSerializer

    def get_queryset(self):
        fiche = _get_or_create_fiche(self.get_partenaire())
        return fiche.telephones.order_by('ordre')

    def perform_create(self, serializer):
        fiche = _get_or_create_fiche(self.get_partenaire())
        serializer.save(restaurant=fiche)


class _TelephoneDetailBase(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TelephoneRestaurantSerializer

    def get_queryset(self):
        fiche = _get_or_create_fiche(self.get_partenaire())
        return fiche.telephones.all()


class MonTelephonesRestaurantView(_PerimetreRestaurateurMixin, _TelephonesListCreateBase):
    """GET/POST /restaurants/mon-restaurant/telephones/"""


class MonTelephoneRestaurantDetailView(_PerimetreRestaurateurMixin, _TelephoneDetailBase):
    """GET/PATCH/DELETE /restaurants/mon-restaurant/telephones/<id>/"""


class AdminTelephonesRestaurantView(_PerimetreAdminMixin, _TelephonesListCreateBase):
    """GET/POST /restaurants/admin/<partenaire_id>/telephones/"""


class AdminTelephoneRestaurantDetailView(_PerimetreAdminMixin, _TelephoneDetailBase):
    """GET/PATCH/DELETE /restaurants/admin/<partenaire_id>/telephones/<id>/"""


# ═══════════════════════════════════════════════════════════════════════
# MENUS PROGRAMMÉS
# ═══════════════════════════════════════════════════════════════════════

class _MenusListCreateBase(generics.ListCreateAPIView):
    """GET ?nature=&service=&publie= — liste des menus du restaurant.
    POST crée un menu."""
    serializer_class = MenuProgrammeSerializer

    def get_queryset(self):
        fiche = _get_or_create_fiche(self.get_partenaire())
        qs = fiche.menus.prefetch_related(
            Prefetch('lignes', queryset=LigneMenu.objects.select_related('plat')
                     .prefetch_related('plat__images')))
        p = self.request.query_params
        if p.get('nature'):
            qs = qs.filter(nature=p['nature'])
        if p.get('service'):
            qs = qs.filter(service=p['service'])
        if p.get('publie') is not None and p.get('publie') != '':
            qs = qs.filter(publie=p.get('publie') in ('1', 'true', 'True'))
        return qs

    def perform_create(self, serializer):
        fiche = _get_or_create_fiche(self.get_partenaire())
        menu = serializer.save(restaurant=fiche, modifie_par_role=self.acteur_role,
                               modifie_par_nom=self.acteur_nom())
        if self.acteur_role == ActeurRole.ADMIN:
            _journaliser_admin(self.request.user, fiche.partenaire, 'resto_menu_modif',
                              f'Menu créé pour « {fiche.partenaire.nom_commerce} » par l\'admin.')


class _MenuDetailBase(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = MenuProgrammeSerializer

    def get_queryset(self):
        fiche = _get_or_create_fiche(self.get_partenaire())
        return fiche.menus.prefetch_related('lignes__plat__images')

    def perform_update(self, serializer):
        menu = serializer.save(modifie_par_role=self.acteur_role,
                               modifie_par_nom=self.acteur_nom())
        if self.acteur_role == ActeurRole.ADMIN:
            _journaliser_admin(self.request.user, menu.restaurant.partenaire, 'resto_menu_modif',
                              f'Menu « {menu} » modifié par l\'admin.')


class MonMenusRestaurantView(_PerimetreRestaurateurMixin, _MenusListCreateBase):
    """GET/POST /restaurants/mon-restaurant/menus/"""


class MonMenuRestaurantDetailView(_PerimetreRestaurateurMixin, _MenuDetailBase):
    """GET/PATCH/DELETE /restaurants/mon-restaurant/menus/<id>/"""


class AdminMenusRestaurantView(_PerimetreAdminMixin, _MenusListCreateBase):
    """GET/POST /restaurants/admin/<partenaire_id>/menus/"""


class AdminMenuRestaurantDetailView(_PerimetreAdminMixin, _MenuDetailBase):
    """GET/PATCH/DELETE /restaurants/admin/<partenaire_id>/menus/<id>/"""


# ── Lignes de menu ────────────────────────────────────────────────────

class _LignesMenuListCreateBase(generics.ListCreateAPIView):
    """GET/POST ?menu=<id> — lignes d'un menu (plats + prix + stock)."""
    serializer_class = LigneMenuSerializer

    def get_queryset(self):
        fiche = _get_or_create_fiche(self.get_partenaire())
        qs = LigneMenu.objects.filter(menu__restaurant=fiche).select_related('plat', 'menu')
        menu_id = self.request.query_params.get('menu')
        return qs.filter(menu_id=menu_id) if menu_id else qs

    def perform_create(self, serializer):
        ligne = serializer.save(modifie_par_role=self.acteur_role,
                                modifie_par_nom=self.acteur_nom())
        if self.acteur_role == ActeurRole.ADMIN:
            _journaliser_admin(
                self.request.user, ligne.menu.restaurant.partenaire, 'resto_plat_modif',
                f'Plat « {ligne.plat.nom} » ajouté au menu « {ligne.menu} » par l\'admin.')


class _LigneMenuDetailBase(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = LigneMenuSerializer

    def get_queryset(self):
        fiche = _get_or_create_fiche(self.get_partenaire())
        return LigneMenu.objects.filter(menu__restaurant=fiche).select_related('plat', 'menu')

    def perform_update(self, serializer):
        ligne = serializer.save(modifie_par_role=self.acteur_role,
                                modifie_par_nom=self.acteur_nom())
        if self.acteur_role == ActeurRole.ADMIN:
            _journaliser_admin(
                self.request.user, ligne.menu.restaurant.partenaire, 'resto_plat_modif',
                f'Ligne de menu « {ligne.plat.nom} » modifiée par l\'admin.')


class MonLignesMenuView(_PerimetreRestaurateurMixin, _LignesMenuListCreateBase):
    """GET/POST /restaurants/mon-restaurant/lignes-menu/?menu=<id>"""


class MonLigneMenuDetailView(_PerimetreRestaurateurMixin, _LigneMenuDetailBase):
    """GET/PATCH/DELETE /restaurants/mon-restaurant/lignes-menu/<id>/"""


class AdminLignesMenuView(_PerimetreAdminMixin, _LignesMenuListCreateBase):
    """GET/POST /restaurants/admin/<partenaire_id>/lignes-menu/?menu=<id>"""


class AdminLigneMenuDetailView(_PerimetreAdminMixin, _LigneMenuDetailBase):
    """GET/PATCH/DELETE /restaurants/admin/<partenaire_id>/lignes-menu/<id>/"""


# ── Actions : dupliquer / copier la semaine ───────────────────────────

class _DupliquerMenuBase(APIView):
    """POST /.../menus/<id>/dupliquer/ {"vers_date": "YYYY-MM-DD"} ou
    {"vers_jour_semaine": 1-7} — crée une copie non publiée."""

    def post(self, request, *args, **kwargs):
        fiche = _get_or_create_fiche(self.get_partenaire())
        menu = fiche.menus.filter(pk=kwargs['pk']).first()
        if menu is None:
            return Response({'erreur': True, 'message': 'Menu introuvable.'}, status=404)
        vers_date = request.data.get('vers_date') or None
        vers_jour = request.data.get('vers_jour_semaine') or None
        if bool(vers_date) == bool(vers_jour):
            return Response(
                {'erreur': True, 'message': 'Fournir exactement un de vers_date ou vers_jour_semaine.'},
                status=400)
        nouveau = services.dupliquer_menu(
            menu, vers_date=vers_date, vers_jour_semaine=vers_jour,
            acteur_role=self.acteur_role, acteur_nom=self.acteur_nom())
        if self.acteur_role == ActeurRole.ADMIN:
            _journaliser_admin(request.user, fiche.partenaire, 'resto_menu_modif',
                              f'Menu « {menu} » dupliqué par l\'admin.')
        return Response(MenuProgrammeSerializer(nouveau, context={'request': request}).data,
                        status=201)


class MonDupliquerMenuView(_PerimetreRestaurateurMixin, _DupliquerMenuBase):
    pass


class AdminDupliquerMenuView(_PerimetreAdminMixin, _DupliquerMenuBase):
    pass


class _CopierSemaineBase(APIView):
    """POST /.../menus/copier-semaine/ — complète les jours manquants de
    chaque service hebdomadaire à partir du premier menu existant."""

    def post(self, request, *args, **kwargs):
        fiche = _get_or_create_fiche(self.get_partenaire())
        crees = services.copier_semaine(
            fiche, acteur_role=self.acteur_role, acteur_nom=self.acteur_nom())
        if self.acteur_role == ActeurRole.ADMIN and crees:
            _journaliser_admin(request.user, fiche.partenaire, 'resto_menu_modif',
                              f'Semaine type copiée ({len(crees)} menu(s)) par l\'admin.')
        return Response(MenuProgrammeSerializer(crees, many=True, context={'request': request}).data,
                        status=201)


class MonCopierSemaineView(_PerimetreRestaurateurMixin, _CopierSemaineBase):
    pass


class AdminCopierSemaineView(_PerimetreAdminMixin, _CopierSemaineBase):
    pass
