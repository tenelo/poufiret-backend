"""
Configuration de l'admin Django pour l'app catalog.
"""
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import (
    Categorie, CommercantCategorie, SectionMenu, Article,
    Logement, Vehicule, ArticleImage, Panorama,
    Variante, Supplement, VueArticle,
)


# ═══════════════════════════════════════════════════════════════════════
# CATÉGORIES
# ═══════════════════════════════════════════════════════════════════════

@admin.register(Categorie)
class CategorieAdmin(admin.ModelAdmin):
    list_display = ('nom', 'parent', 'mode_transaction', 'module_flutter', 'ordre', 'est_active')
    list_filter = ('mode_transaction', 'est_active', 'parent')
    search_fields = ('nom', 'slug', 'description', 'module_flutter')
    list_editable = ('ordre', 'est_active')
    prepopulated_fields = {'slug': ('nom',)}
    autocomplete_fields = ('parent',)
    ordering = ('ordre', 'nom')

    fieldsets = (
        (None, {
            'fields': ('nom', 'slug', 'description', 'icone', 'image_couverture'),
        }),
        (_('Hiérarchie & comportement'), {
            'fields': ('parent', 'mode_transaction', 'module_flutter'),
        }),
        (_('Affichage'), {
            'fields': ('ordre', 'est_active'),
        }),
    )


@admin.register(CommercantCategorie)
class CommercantCategorieAdmin(admin.ModelAdmin):
    list_display = ('commercant', 'categorie', 'est_principale')
    list_filter = ('est_principale', 'categorie')
    search_fields = ('commercant__nom_commerce', 'categorie__nom')
    autocomplete_fields = ('commercant', 'categorie')
    list_editable = ('est_principale',)


# ═══════════════════════════════════════════════════════════════════════
# SECTIONS DE MENU
# ═══════════════════════════════════════════════════════════════════════

@admin.register(SectionMenu)
class SectionMenuAdmin(admin.ModelAdmin):
    list_display = ('nom', 'commercant', 'ordre', 'est_active')
    list_filter = ('est_active',)
    search_fields = ('nom', 'commercant__nom_commerce')
    autocomplete_fields = ('commercant',)
    list_editable = ('ordre', 'est_active')


# ═══════════════════════════════════════════════════════════════════════
# INLINES POUR ARTICLE
# ═══════════════════════════════════════════════════════════════════════

class ArticleImageInline(admin.TabularInline):
    model = ArticleImage
    extra = 1
    fields = ('image', 'legende', 'ordre', 'est_principale', 'est_active')


class PanoramaInline(admin.TabularInline):
    model = Panorama
    extra = 0
    fields = ('image', 'nom_piece', 'ordre', 'est_active')


class VarianteInline(admin.TabularInline):
    model = Variante
    extra = 0
    fields = ('nom', 'prix_supplement', 'est_par_defaut', 'ordre', 'est_active')


class SupplementInline(admin.TabularInline):
    model = Supplement
    extra = 0
    fields = ('nom', 'prix', 'est_optionnel', 'ordre', 'est_actif')


class LogementInline(admin.StackedInline):
    model = Logement
    can_delete = False
    fk_name = 'article'


class VehiculeInline(admin.StackedInline):
    model = Vehicule
    can_delete = False
    fk_name = 'article'


# ═══════════════════════════════════════════════════════════════════════
# ARTICLE
# ═══════════════════════════════════════════════════════════════════════

@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = (
        'nom', 'commercant', 'categorie', 'type', 'prix',
        'est_actif', 'est_disponible', 'nb_vues', 'nb_likes', 'created_at',
    )
    list_filter = ('type', 'est_actif', 'est_disponible', 'est_en_promotion', 'categorie')
    search_fields = ('nom', 'slug', 'description', 'commercant__nom_commerce')
    list_editable = ('est_actif', 'est_disponible')
    autocomplete_fields = ('commercant', 'categorie', 'section_menu')
    prepopulated_fields = {'slug': ('nom',)}
    readonly_fields = ('nb_vues', 'nb_likes', 'nb_commentaires', 'nb_favoris',
                       'created_at', 'updated_at')
    inlines = [ArticleImageInline, PanoramaInline, VarianteInline, SupplementInline]
    ordering = ('-created_at',)

    fieldsets = (
        (None, {
            'fields': ('commercant', 'categorie', 'type', 'nom', 'slug', 'description'),
        }),
        (_('Tarif'), {
            'fields': ('prix', 'prix_promotion', 'unite', 'est_en_promotion'),
        }),
        (_('Détails spécifiques (JSON)'), {
            'fields': ('details',),
            'classes': ('collapse',),
        }),
        (_('Spécifique resto / fast-food'), {
            'fields': ('section_menu', 'temps_preparation_min'),
            'classes': ('collapse',),
        }),
        (_('État'), {
            'fields': ('est_actif', 'est_disponible'),
        }),
        (_('Statistiques'), {
            'fields': ('nb_vues', 'nb_likes', 'nb_commentaires', 'nb_favoris',
                       'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


# ═══════════════════════════════════════════════════════════════════════
# EXTENSIONS LOGEMENT / VÉHICULE (standalone)
# ═══════════════════════════════════════════════════════════════════════

@admin.register(Logement)
class LogementAdmin(admin.ModelAdmin):
    list_display = ('article', 'nb_chambres', 'nb_sdb', 'surface_m2', 'meuble')
    list_filter = ('meuble',)
    search_fields = ('article__nom', 'article__commercant__nom_commerce')
    autocomplete_fields = ('article',)


@admin.register(Vehicule)
class VehiculeAdmin(admin.ModelAdmin):
    list_display = ('article', 'marque', 'modele', 'annee', 'kilometrage', 'mode')
    list_filter = ('mode', 'carburant', 'boite_vitesse')
    search_fields = ('marque', 'modele', 'article__nom')
    autocomplete_fields = ('article',)


# ═══════════════════════════════════════════════════════════════════════
# PHOTOS, PANORAMAS, VARIANTES, SUPPLÉMENTS (standalone)
# ═══════════════════════════════════════════════════════════════════════

@admin.register(ArticleImage)
class ArticleImageAdmin(admin.ModelAdmin):
    list_display = ('article', 'legende', 'ordre', 'est_principale', 'est_active')
    list_filter = ('est_principale', 'est_active')
    search_fields = ('article__nom',)
    autocomplete_fields = ('article',)
    list_editable = ('ordre', 'est_principale', 'est_active')


@admin.register(Panorama)
class PanoramaAdmin(admin.ModelAdmin):
    list_display = ('article', 'nom_piece', 'ordre', 'est_active')
    list_filter = ('est_active',)
    search_fields = ('article__nom', 'nom_piece')
    autocomplete_fields = ('article',)


@admin.register(Variante)
class VarianteAdmin(admin.ModelAdmin):
    list_display = ('article', 'nom', 'prix_supplement', 'est_par_defaut', 'est_active')
    list_filter = ('est_par_defaut', 'est_active')
    search_fields = ('nom', 'article__nom')
    autocomplete_fields = ('article',)


@admin.register(Supplement)
class SupplementAdmin(admin.ModelAdmin):
    list_display = ('article', 'nom', 'prix', 'est_optionnel', 'est_actif')
    list_filter = ('est_optionnel', 'est_actif')
    search_fields = ('nom', 'article__nom')
    autocomplete_fields = ('article',)


# ═══════════════════════════════════════════════════════════════════════
# TRACKING (VueArticle — lecture seule en admin)
# ═══════════════════════════════════════════════════════════════════════

@admin.register(VueArticle)
class VueArticleAdmin(admin.ModelAdmin):
    list_display = ('article', 'user', 'source', 'duree_secondes', 'date_vue')
    list_filter = ('source', 'date_vue')
    search_fields = ('article__nom', 'user__telephone')
    autocomplete_fields = ('article', 'user')
    readonly_fields = ('article', 'user', 'date_vue', 'source', 'duree_secondes')
    date_hierarchy = 'date_vue'
    ordering = ('-date_vue',)

    def has_add_permission(self, request):
        # Pas de création manuelle, les vues sont enregistrées par l'app
        return False