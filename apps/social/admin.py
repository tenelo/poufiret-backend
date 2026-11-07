"""
Configuration de l'admin Django pour l'app social.
"""
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import (
    LikeArticle, LikePartenaire, LikeCommentaire,
    FavoriArticle, FavoriPartenaire,
    CommentaireArticle, CommentairePartenaire, Avis,
)


# ═══════════════════════════════════════════════════════════════════════
# LIKES ❤️
# ═══════════════════════════════════════════════════════════════════════

@admin.register(LikeArticle)
class LikeArticleAdmin(admin.ModelAdmin):
    list_display = ('user', 'article', 'created_at')
    search_fields = ('user__telephone', 'article__nom')
    autocomplete_fields = ('user', 'article')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)


@admin.register(LikePartenaire)
class LikePartenaireAdmin(admin.ModelAdmin):
    list_display = ('user', 'partenaire', 'created_at')
    search_fields = ('user__telephone', 'partenaire__nom_commerce')
    autocomplete_fields = ('user', 'partenaire')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)


@admin.register(LikeCommentaire)
class LikeCommentaireAdmin(admin.ModelAdmin):
    list_display = ('user', 'commentaire_article', 'commentaire_partenaire', 'created_at')
    search_fields = ('user__telephone',)
    autocomplete_fields = ('user', 'commentaire_article', 'commentaire_partenaire')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)


# ═══════════════════════════════════════════════════════════════════════
# FAVORIS 🤎
# ═══════════════════════════════════════════════════════════════════════

@admin.register(FavoriArticle)
class FavoriArticleAdmin(admin.ModelAdmin):
    list_display = ('user', 'article', 'created_at')
    search_fields = ('user__telephone', 'article__nom')
    autocomplete_fields = ('user', 'article')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)


@admin.register(FavoriPartenaire)
class FavoriPartenaireAdmin(admin.ModelAdmin):
    list_display = ('user', 'partenaire', 'created_at')
    search_fields = ('user__telephone', 'partenaire__nom_commerce')
    autocomplete_fields = ('user', 'partenaire')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)


# ═══════════════════════════════════════════════════════════════════════
# COMMENTAIRES 💬
# ═══════════════════════════════════════════════════════════════════════

class ReponseArticleInline(admin.TabularInline):
    """Inline pour afficher les réponses sous un commentaire d'article."""
    model = CommentaireArticle
    fk_name = 'parent'
    extra = 0
    fields = ('user', 'contenu', 'est_visible', 'nb_likes', 'created_at')
    readonly_fields = ('user', 'created_at', 'nb_likes')


@admin.register(CommentaireArticle)
class CommentaireArticleAdmin(admin.ModelAdmin):
    list_display = ('user', 'article', 'preview', 'parent', 'est_visible',
                    'nb_likes', 'created_at')
    list_filter = ('est_visible',)
    search_fields = ('contenu', 'user__telephone', 'article__nom')
    list_editable = ('est_visible',)
    autocomplete_fields = ('user', 'article', 'parent')
    readonly_fields = ('nb_likes', 'created_at', 'updated_at', 'est_modifie')
    inlines = [ReponseArticleInline]
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    def preview(self, obj):
        return obj.contenu[:60] + ('…' if len(obj.contenu) > 60 else '')
    preview.short_description = _('Aperçu')


class ReponsePartenaireInline(admin.TabularInline):
    """Inline pour afficher les réponses sous un commentaire de commerçant."""
    model = CommentairePartenaire
    fk_name = 'parent'
    extra = 0
    fields = ('user', 'contenu', 'est_visible', 'nb_likes', 'created_at')
    readonly_fields = ('user', 'created_at', 'nb_likes')


@admin.register(CommentairePartenaire)
class CommentairePartenaireAdmin(admin.ModelAdmin):
    list_display = ('user', 'partenaire', 'preview', 'parent', 'est_visible',
                    'nb_likes', 'created_at')
    list_filter = ('est_visible',)
    search_fields = ('contenu', 'user__telephone', 'partenaire__nom_commerce')
    list_editable = ('est_visible',)
    autocomplete_fields = ('user', 'partenaire', 'parent')
    readonly_fields = ('nb_likes', 'created_at', 'updated_at', 'est_modifie')
    inlines = [ReponsePartenaireInline]
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    def preview(self, obj):
        return obj.contenu[:60] + ('…' if len(obj.contenu) > 60 else '')
    preview.short_description = _('Aperçu')

@admin.register(Avis)
class AvisAdmin(admin.ModelAdmin):
    """Consultation et filtres. Masquer / réafficher passe de préférence par
    l'API admin (/api/v1/avis/admin/<id>/), qui journalise et recalcule la note."""
    list_display = ('id', 'objet_type', 'objet_id', 'partenaire', 'auteur', 'note', 'est_visible',
                    'repondu_le', 'cree_le')
    list_filter = ('objet_type', 'note', 'est_visible')
    search_fields = ('commentaire', 'partenaire__nom_commerce', 'auteur__telephone', 'objet_id')
    date_hierarchy = 'cree_le'
    list_select_related = ('auteur', 'partenaire')
    raw_id_fields = ('auteur', 'partenaire', 'livreur')
    readonly_fields = ('auteur', 'objet_type', 'objet_id', 'partenaire', 'livreur', 'note', 'commentaire',
                       'est_visible', 'reponse_partenaire', 'repondu_le', 'cree_le', 'modifie_le')

    def has_add_permission(self, request):
        return False
