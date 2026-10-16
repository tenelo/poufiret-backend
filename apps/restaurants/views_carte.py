"""Gestion de la carte (sections, plats, images, variantes, groupes
d'options) — mêmes vues et serializers pour restaurateur et admin (seul le
périmètre change, via les mixins de views_prive.py), réutilisant
intégralement apps.catalog (aucune duplication de modèle ni de logique).
"""
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import (
    Article, ArticleImage, Categorie, GroupeOption, OptionGroupe, SectionMenu, Variante,
)
from apps.catalog.serializers import (
    ArticleCarteGestionSerializer, ArticleImageImbriqueeSerializer, GroupeOptionSerializer,
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


# ── Ordre des plats d'une section ───────────────────────────────────────

class _PlatsOrdreBase(APIView):
    """POST .../carte/plats/ordre/ {"section_id": <id>, "ordre": [ids des plats]}
    — réattribue ordre = 1..n aux plats listés, dans cet ordre. Les autres
    plats de la section (absents de la liste) suivent, n+1.., dans leur
    ordre actuel. 400 si la section ou un plat n'appartient pas au
    restaurant, ou si un plat n'est pas dans la section."""

    def post(self, request, *args, **kwargs):
        partenaire = self.get_partenaire()
        section_id, ids = request.data.get('section_id'), request.data.get('ordre')
        try:
            section_id = int(section_id)
            ids = [int(i) for i in ids]
        except (TypeError, ValueError):
            return Response({'erreur': True, 'message':
                             'section_id (entier) et ordre (liste d\'ids) sont requis.'}, status=400)
        if not ids or len(set(ids)) != len(ids):
            return Response({'erreur': True, 'message':
                             'ordre doit être une liste non vide, sans doublon.'}, status=400)
        section = SectionMenu.objects.filter(pk=section_id, partenaire=partenaire).first()
        if section is None:
            return Response({'erreur': True, 'message':
                             "Cette section n'appartient pas à ce restaurant."}, status=400)

        plats = {a.id: a for a in Article.objects.filter(
            partenaire=partenaire, type=Article.Type.PLAT, section_menu=section)}
        hors_section = [i for i in ids if i not in plats]
        if hors_section:
            return Response({'erreur': True, 'plats_invalides': hors_section, 'message':
                             "Plat(s) hors de cette section ou de ce restaurant : "
                             f"{', '.join(map(str, hors_section))}."}, status=400)

        listes = set(ids)
        restants = sorted((a for i, a in plats.items() if i not in listes),
                          key=lambda a: (a.ordre, a.nom.casefold(), a.id))
        maintenant, nom = timezone.now(), self.acteur_nom()
        modifies = []
        for rang, article in enumerate([plats[i] for i in ids] + restants, start=1):
            if article.ordre != rang:
                article.ordre = rang
                article.modifie_par_role, article.modifie_par_nom = self.acteur_role, nom
                article.updated_at = maintenant
                modifies.append(article)
        with transaction.atomic():
            Article.objects.bulk_update(
                modifies, ['ordre', 'modifie_par_role', 'modifie_par_nom', 'updated_at'])
        if self.acteur_role == ActeurRole.ADMIN and modifies:
            _journaliser_admin(request.user, partenaire, 'resto_plat_modif',
                               f'Ordre des plats de la section « {section.nom} » '
                               f'modifié par l\'admin.')
        qs = (Article.objects.filter(partenaire=partenaire, type=Article.Type.PLAT, section_menu=section)
              .select_related('section_menu')
              .prefetch_related('images', 'variantes', 'groupes_options__options')
              .order_by('ordre', 'nom'))
        return Response(ArticleCarteGestionSerializer(qs, many=True, context={'request': request}).data)


class MonPlatsOrdreView(_PerimetreRestaurateurMixin, _PlatsOrdreBase):
    """POST /restaurants/mon-restaurant/carte/plats/ordre/"""


class AdminPlatsOrdreView(_PerimetreAdminMixin, _PlatsOrdreBase):
    """POST /restaurants/admin/<partenaire_id>/carte/plats/ordre/"""


# ═══════════════════════════════════════════════════════════════════════
# IMAGES D'UN PLAT (comme /catalogue/images/ : quota du plan, pas de
# bascule auto d'image principale — PATCH l'ancienne à est_principale=false
# avant d'en poser une nouvelle). Le plat est celui de l'URL : champ
# "article" du corps facultatif (400 s'il diffère) ; quota dépassé → 400.
# ═══════════════════════════════════════════════════════════════════════

class _PlatImagesListCreateBase(generics.ListCreateAPIView):
    serializer_class = ArticleImageImbriqueeSerializer

    def _plat(self):
        if not hasattr(self, '_plat_cache'):
            self._plat_cache = get_object_or_404(
                Article.objects.select_related('partenaire__plan'), pk=self.kwargs['plat_id'],
                partenaire=self.get_partenaire(), type=Article.Type.PLAT)
        return self._plat_cache

    def get_queryset(self):
        return self._plat().images.order_by('ordre')

    def get_serializer_context(self):
        return {**super().get_serializer_context(), 'article': self._plat()}

    def perform_create(self, serializer):
        serializer.save(article=self._plat(), est_active=True)


class _PlatImageDetailBase(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ArticleImageImbriqueeSerializer

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
