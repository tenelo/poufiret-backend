"""
Configuration de l'admin Django pour l'app social.
"""
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import (
    LikeArticle, LikePartenaire, LikeCommentaire,
    FavoriArticle, FavoriPartenaire,
    CommentaireArticle, CommentairePartenaire,
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