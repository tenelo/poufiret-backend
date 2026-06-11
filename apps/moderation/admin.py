"""
Configuration de l'admin Django pour l'app moderation.
"""
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import (
    SignalementArticle, SignalementCommercant,
    SignalementCommentaire, SignalementMessage,
    Notification,
)


# ═══════════════════════════════════════════════════════════════════════
# CLASSE DE BASE POUR LES SIGNALEMENTS
# ═══════════════════════════════════════════════════════════════════════

class SignalementBaseAdmin(admin.ModelAdmin):
    """Configuration commune aux 4 types de signalements."""
    list_filter = ('statut', 'motif')
    list_editable = ('statut',)
    readonly_fields = ('created_at', 'traite_le')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)


@admin.register(SignalementArticle)
class SignalementArticleAdmin(SignalementBaseAdmin):
    list_display = ('id', 'article', 'rapporteur', 'motif', 'statut',
                    'traite_par', 'created_at')
    search_fields = ('article__nom', 'rapporteur__telephone', 'description')
    autocomplete_fields = ('article', 'rapporteur', 'traite_par')


@admin.register(SignalementCommercant)
class SignalementCommercantAdmin(SignalementBaseAdmin):
    list_display = ('id', 'commercant', 'rapporteur', 'motif', 'statut',
                    'traite_par', 'created_at')
    search_fields = ('commercant__nom_commerce', 'rapporteur__telephone', 'description')
    autocomplete_fields = ('commercant', 'rapporteur', 'traite_par')


@admin.register(SignalementCommentaire)
class SignalementCommentaireAdmin(SignalementBaseAdmin):
    list_display = ('id', 'cible', 'rapporteur', 'motif', 'statut',
                    'traite_par', 'created_at')
    search_fields = ('rapporteur__telephone', 'description')
    autocomplete_fields = (
        'commentaire_article', 'commentaire_commercant',
        'rapporteur', 'traite_par',
    )

    def cible(self, obj):
        if obj.commentaire_article:
            return f"Article : {obj.commentaire_article}"
        if obj.commentaire_commercant:
            return f"Commerçant : {obj.commentaire_commercant}"
        return '—'
    cible.short_description = _('Cible')


@admin.register(SignalementMessage)
class SignalementMessageAdmin(SignalementBaseAdmin):
    list_display = ('id', 'message', 'rapporteur', 'motif', 'statut',
                    'traite_par', 'created_at')
    search_fields = ('message__contenu', 'rapporteur__telephone', 'description')
    autocomplete_fields = ('message', 'rapporteur', 'traite_par')


# ═══════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'type', 'titre', 'lu', 'created_at')
    list_filter = ('type', 'lu')
    search_fields = ('titre', 'contenu', 'user__telephone')
    autocomplete_fields = ('user',)
    readonly_fields = ('created_at', 'lu_le')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    list_editable = ('lu',)