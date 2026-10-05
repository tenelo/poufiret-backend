"""Gestion de la carte (sections, plats, images, variantes, groupes
d'options) — mêmes vues et serializers pour restaurateur et admin (seul le
périmètre change, via les mixins de views_prive.py), réutilisant
intégralement apps.catalog (aucune duplication de modèle ni de logique).
"""
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import (
    Article, ArticleImage, Categorie, GroupeOption, OptionGroupe, SectionMenu, Variante,
)
from apps.catalog.serializers import (
    ArticleCarteGestionSerializer, ArticleImageSerializer, GroupeOptionSerializer,
    OptionGroupeSerializer, SectionMenuSerializer, VarianteSerializer,
)

from .models import ActeurRole
from .views_prive import _PerimetreAdminMixin, _PerimetreRestaurateurMixin, _journaliser_admin


def _slug_unique(partenaire, nom):
    base = slugify(nom)[:200] or 'plat'
    slug, n = base, 1
    while Article.objects.filter(partenaire=partenaire, slug=slug).exists():
        n += 1
        slug = f'{base}-{n}'[:220]
    return slug


def _categorie_par_defaut(partenaire):
    return Categorie.objects.filter(
        types_partenaire__contains=[partenaire.type_partenaire],
        types_articles__contains=['plat']).first()


# ═══════════════════════════════════════════════════════════════════════
# SECTIONS
# ═══════════════════════════════════════════════════════════════════════

class _SectionsListCreateBase(generics.ListCreateAPIView):
    serializer_class = SectionMenuSerializer

    def get_queryset(self):
        return self.get_partenaire().sections_menu.order_by('ordre', 'nom')

    def perform_create(self, serializer):
        partenaire = self.get_partenaire()
        section = serializer.save(partenaire=partenaire, modifie_par_role=self.acteur_role,
                                  modifie_par_nom=self.acteur_nom())
        if self.acteur_role == ActeurRole.ADMIN:
            _journaliser_admin(self.request.user, partenaire, 'resto_plat_modif',
                               f'Section « {section.nom} » créée par l\'admin.')


class _SectionDetailBase(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SectionMenuSerializer

    def get_queryset(self):
        return self.get_partenaire().sections_menu.all()

    def perform_update(self, serializer):
        partenaire = self.get_partenaire()
        section = serializer.save(modifie_par_role=self.acteur_role,
                                  modifie_par_nom=self.acteur_nom())
        if self.acteur_role == ActeurRole.ADMIN:
            _journaliser_admin(self.request.user, partenaire, 'resto_plat_modif',
                               f'Section « {section.nom} » modifiée par l\'admin.')


class MonSectionsCarteView(_PerimetreRestaurateurMixin, _SectionsListCreateBase):
    """GET/POST /restaurants/mon-restaurant/carte/sections/"""


class MonSectionCarteDetailView(_PerimetreRestaurateurMixin, _SectionDetailBase):
    """GET/PATCH/DELETE /restaurants/mon-restaurant/carte/sections/<id>/"""


class AdminSectionsCarteView(_PerimetreAdminMixin, _SectionsListCreateBase):
    """GET/POST /restaurants/admin/<partenaire_id>/carte/sections/"""


class AdminSectionCarteDetailView(_PerimetreAdminMixin, _SectionDetailBase):
    """GET/PATCH/DELETE /restaurants/admin/<partenaire_id>/carte/sections/<id>/"""


# ═══════════════════════════════════════════════════════════════════════
# PLATS
# ═══════════════════════════════════════════════════════════════════════

class _PlatsListCreateBase(generics.ListCreateAPIView):
    """GET ?section=&reserve_aux_menus= — vue de GESTION (tous les plats,
    y compris indisponibles/réservés aux menus — différent de la carte
    publique). POST crée un plat (categorie auto-résolue si omise)."""
    serializer_class = ArticleCarteGestionSerializer

    def get_queryset(self):
        qs = (Article.objects.filter(partenaire=self.get_partenaire(), type=Article.Type.PLAT)
              .select_related('section_menu')
              .prefetch_related('images', 'variantes', 'groupes_options__options'))
        p = self.request.query_params
        if p.get('section'):
            qs = qs.filter(section_menu_id=p['section'])
        reserve = p.get('reserve_aux_menus')
        if reserve is not None and reserve != '':
            qs = qs.filter(est_reserve_aux_menus=reserve in ('1', 'true', 'True'))
        return qs.order_by('ordre', 'nom')

    def _verifier_section(self, partenaire, section):
        if section is not None and section.partenaire_id != partenaire.id:
            raise ValidationError({'section_menu': "Cette section n'appartient pas à ce restaurant."})

    def perform_create(self, serializer):
        partenaire = self.get_partenaire()
        self._verifier_section(partenaire, serializer.validated_data.get('section_menu'))
        categorie = serializer.validated_data.get('categorie') or _categorie_par_defaut(partenaire)
        article = serializer.save(
            partenaire=partenaire, categorie=categorie, type=Article.Type.PLAT,
            slug=_slug_unique(partenaire, serializer.validated_data['nom']),
            modifie_par_role=self.acteur_role, modifie_par_nom=self.acteur_nom())
        if self.acteur_role == ActeurRole.ADMIN:
            _journaliser_admin(self.request.user, partenaire, 'resto_plat_modif',
                               f'Plat « {article.nom} » créé par l\'admin.')


class _PlatDetailBase(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ArticleCarteGestionSerializer

    def get_queryset(self):
        return (Article.objects.filter(partenaire=self.get_partenaire(), type=Article.Type.PLAT)
                .select_related('section_menu')
                .prefetch_related('images', 'variantes', 'groupes_options__options'))

    def perform_update(self, serializer):
        partenaire = self.get_partenaire()
        if 'section_menu' in serializer.validated_data:
            section = serializer.validated_data.get('section_menu')
            if section is not None and section.partenaire_id != partenaire.id:
                raise ValidationError(
                    {'section_menu': "Cette section n'appartient pas à ce restaurant."})
        article = serializer.save(modifie_par_role=self.acteur_role,
                                  modifie_par_nom=self.acteur_nom())
        if self.acteur_role == ActeurRole.ADMIN:
            _journaliser_admin(self.request.user, partenaire, 'resto_plat_modif',
                               f'Plat « {article.nom} » modifié par l\'admin.')


class MonPlatsCarteView(_PerimetreRestaurateurMixin, _PlatsListCreateBase):
    """GET/POST /restaurants/mon-restaurant/carte/plats/"""


class MonPlatCarteDetailView(_PerimetreRestaurateurMixin, _PlatDetailBase):
    """GET/PATCH/DELETE /restaurants/mon-restaurant/carte/plats/<id>/"""


class AdminPlatsCarteView(_PerimetreAdminMixin, _PlatsListCreateBase):
    """GET/POST /restaurants/admin/<partenaire_id>/carte/plats/"""


class AdminPlatCarteDetailView(_PerimetreAdminMixin, _PlatDetailBase):
    """GET/PATCH/DELETE /restaurants/admin/<partenaire_id>/carte/plats/<id>/"""


# ── Raccourci épuisé ────────────────────────────────────────────────────

class _PlatEpuiseBase(APIView):
    """POST .../plats/<id>/epuise/ {"epuise": bool} — bascule est_disponible
    (épuisé = indisponible), sans passer par un PATCH complet."""

    def post(self, request, *args, **kwargs):
        partenaire = self.get_partenaire()
        article = get_object_or_404(
            Article, pk=kwargs['pk'], partenaire=partenaire, type=Article.Type.PLAT)
        epuise = bool(request.data.get('epuise'))
        article.est_disponible = not epuise
        article.modifie_par_role = self.acteur_role
        article.modifie_par_nom = self.acteur_nom()
        article.save(update_fields=['est_disponible', 'modifie_par_role', 'modifie_par_nom', 'updated_at'])
        if self.acteur_role == ActeurRole.ADMIN:
            _journaliser_admin(
                request.user, partenaire, 'resto_plat_modif',
                f'Plat « {article.nom} » marqué '
                f'{"épuisé" if epuise else "disponible"} par l\'admin.')
        return Response(ArticleCarteGestionSerializer(article, context={'request': request}).data)


class MonPlatEpuiseView(_PerimetreRestaurateurMixin, _PlatEpuiseBase):
    """POST /restaurants/mon-restaurant/carte/plats/<id>/epuise/"""


class AdminPlatEpuiseView(_PerimetreAdminMixin, _PlatEpuiseBase):
    """POST /restaurants/admin/<partenaire_id>/carte/plats/<id>/epuise/"""


# ═══════════════════════════════════════════════════════════════════════
# IMAGES D'UN PLAT (comme /catalogue/images/ existant — même comportement,
# y compris le quota du plan et l'absence de bascule auto d'image
# principale : PATCH l'ancienne à est_principale=false avant d'en poser
# une nouvelle, comme pour /catalogue/).
# ═══════════════════════════════════════════════════════════════════════

class _PlatImagesListCreateBase(generics.ListCreateAPIView):
    serializer_class = ArticleImageSerializer

    def _plat(self):
        return get_object_or_404(
            Article, pk=self.kwargs['plat_id'], partenaire=self.get_partenaire(),
            type=Article.Type.PLAT)

    def get_queryset(self):
        return self._plat().images.order_by('ordre')

    def perform_create(self, serializer):
        plat = self._plat()
        maxi = plat.partenaire.plan.nb_photos_par_article
        if maxi and plat.images.count() >= maxi:
            raise PermissionDenied(
                f'Quota photos atteint ({maxi}/article pour le plan '
                f'{plat.partenaire.plan.libelle}).')
        serializer.save(article=plat, est_active=True)


class _PlatImageDetailBase(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ArticleImageSerializer

    def get_queryset(self):
        return ArticleImage.objects.filter(
            article_id=self.kwargs['plat_id'], article__partenaire=self.get_partenaire())


class MonPlatImagesView(_PerimetreRestaurateurMixin, _PlatImagesListCreateBase):
    """GET/POST /restaurants/mon-restaurant/carte/plats/<plat_id>/images/"""


class MonPlatImageDetailView(_PerimetreRestaurateurMixin, _PlatImageDetailBase):
    """GET/PATCH/DELETE /restaurants/mon-restaurant/carte/plats/<plat_id>/images/<id>/"""


class AdminPlatImagesView(_PerimetreAdminMixin, _PlatImagesListCreateBase):
    """GET/POST /restaurants/admin/<partenaire_id>/carte/plats/<plat_id>/images/"""


class AdminPlatImageDetailView(_PerimetreAdminMixin, _PlatImageDetailBase):
    """GET/PATCH/DELETE /restaurants/admin/<partenaire_id>/carte/plats/<plat_id>/images/<id>/"""


# ═══════════════════════════════════════════════════════════════════════
# VARIANTES (?plat=<id>) ET GROUPES D'OPTIONS (?plat=<id>) + OPTIONS (?groupe=<id>)
# Mêmes modèles/serializers que /catalogue/variantes|groupes-options|options/,
# périmètre restaurant à la place de « propriétaire connecté ».
# ═══════════════════════════════════════════════════════════════════════

class _SousRessourcePlatListCreateBase(generics.ListCreateAPIView):
    """Base pour variantes/groupes d'options : filtre ?plat=<id>, propriété
    vérifiée via le périmètre restaurant (pas via request.user)."""
    model = None

    def get_queryset(self):
        qs = self.model.objects.filter(article__partenaire=self.get_partenaire())
        plat_id = self.request.query_params.get('plat')
        return qs.filter(article_id=plat_id) if plat_id else qs

    def perform_create(self, serializer):
        article = serializer.validated_data.get('article')
        if article is None or article.partenaire_id != self.get_partenaire().id:
            raise ValidationError({'article': "Ce plat n'appartient pas à ce restaurant."})
        serializer.save()


class _SousRessourcePlatDetailBase(generics.RetrieveUpdateDestroyAPIView):
    model = None

    def get_queryset(self):
        return self.model.objects.filter(article__partenaire=self.get_partenaire())


class _VariantesListCreateBase(_SousRessourcePlatListCreateBase):
    model = Variante
    serializer_class = VarianteSerializer


class _VarianteDetailBase(_SousRessourcePlatDetailBase):
    model = Variante
    serializer_class = VarianteSerializer


class MonVariantesCarteView(_PerimetreRestaurateurMixin, _VariantesListCreateBase):
    """GET/POST /restaurants/mon-restaurant/carte/variantes/?plat=<id>"""


class MonVarianteCarteDetailView(_PerimetreRestaurateurMixin, _VarianteDetailBase):
    """GET/PATCH/DELETE /restaurants/mon-restaurant/carte/variantes/<id>/"""


class AdminVariantesCarteView(_PerimetreAdminMixin, _VariantesListCreateBase):
    """GET/POST /restaurants/admin/<partenaire_id>/carte/variantes/?plat=<id>"""


class AdminVarianteCarteDetailView(_PerimetreAdminMixin, _VarianteDetailBase):
    """GET/PATCH/DELETE /restaurants/admin/<partenaire_id>/carte/variantes/<id>/"""


class _GroupesOptionsListCreateBase(_SousRessourcePlatListCreateBase):
    model = GroupeOption
    serializer_class = GroupeOptionSerializer


class _GroupeOptionDetailBase(_SousRessourcePlatDetailBase):
    model = GroupeOption
    serializer_class = GroupeOptionSerializer


class MonGroupesOptionsCarteView(_PerimetreRestaurateurMixin, _GroupesOptionsListCreateBase):
    """GET/POST /restaurants/mon-restaurant/carte/groupes-options/?plat=<id>"""


class MonGroupeOptionCarteDetailView(_PerimetreRestaurateurMixin, _GroupeOptionDetailBase):
    """GET/PATCH/DELETE /restaurants/mon-restaurant/carte/groupes-options/<id>/"""


class AdminGroupesOptionsCarteView(_PerimetreAdminMixin, _GroupesOptionsListCreateBase):
    """GET/POST /restaurants/admin/<partenaire_id>/carte/groupes-options/?plat=<id>"""


class AdminGroupeOptionCarteDetailView(_PerimetreAdminMixin, _GroupeOptionDetailBase):
    """GET/PATCH/DELETE /restaurants/admin/<partenaire_id>/carte/groupes-options/<id>/"""


class _OptionsListCreateBase(generics.ListCreateAPIView):
    serializer_class = OptionGroupeSerializer

    def get_queryset(self):
        qs = OptionGroupe.objects.filter(groupe__article__partenaire=self.get_partenaire())
        groupe_id = self.request.query_params.get('groupe')
        return qs.filter(groupe_id=groupe_id) if groupe_id else qs

    def perform_create(self, serializer):
        groupe = serializer.validated_data.get('groupe')
        if groupe is None or groupe.article.partenaire_id != self.get_partenaire().id:
            raise ValidationError({'groupe': "Ce groupe n'appartient pas à ce restaurant."})
        serializer.save()


class _OptionDetailBase(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = OptionGroupeSerializer

    def get_queryset(self):
        return OptionGroupe.objects.filter(groupe__article__partenaire=self.get_partenaire())


class MonOptionsCarteView(_PerimetreRestaurateurMixin, _OptionsListCreateBase):
    """GET/POST /restaurants/mon-restaurant/carte/options/?groupe=<id>"""


class MonOptionCarteDetailView(_PerimetreRestaurateurMixin, _OptionDetailBase):
    """GET/PATCH/DELETE /restaurants/mon-restaurant/carte/options/<id>/"""


class AdminOptionsCarteView(_PerimetreAdminMixin, _OptionsListCreateBase):
    """GET/POST /restaurants/admin/<partenaire_id>/carte/options/?groupe=<id>"""


class AdminOptionCarteDetailView(_PerimetreAdminMixin, _OptionDetailBase):
    """GET/PATCH/DELETE /restaurants/admin/<partenaire_id>/carte/options/<id>/"""
