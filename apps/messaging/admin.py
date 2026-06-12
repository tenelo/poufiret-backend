"""
Configuration de l'admin Django pour l'app messaging.
"""
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import (
    Conversation, Message,
    DemandeIntervention, DemandeInterventionPhoto,
)


# ═══════════════════════════════════════════════════════════════════════
# CONVERSATION & MESSAGE
# ═══════════════════════════════════════════════════════════════════════

class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ('expediteur', 'type', 'contenu', 'statut', 'created_at')
    readonly_fields = ('expediteur', 'type', 'contenu', 'statut', 'created_at')
    can_delete = False
    ordering = ('-created_at',)
    max_num = 30  # limite l'affichage aux 30 derniers messages

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('client', 'partenaire', 'article', 'nb_messages',
                    'est_archivee', 'derniere_activite')
    list_filter = ('est_archivee',)
    search_fields = (
        'client__telephone', 'client__first_name',
        'partenaire__nom_commerce', 'article__nom',
    )
    autocomplete_fields = ('client', 'partenaire', 'article')
    readonly_fields = ('created_at', 'derniere_activite')
    inlines = [MessageInline]
    date_hierarchy = 'derniere_activite'
    ordering = ('-derniere_activite',)

    def nb_messages(self, obj):
        return obj.messages.count()
    nb_messages.short_description = _('Messages')


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'expediteur', 'type', 'preview',
                    'statut', 'created_at')
    list_filter = ('type', 'statut', 'est_supprime')
    search_fields = ('contenu', 'expediteur__telephone')
    autocomplete_fields = ('conversation', 'expediteur')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    def preview(self, obj):
        return (obj.contenu[:60] + '…') if len(obj.contenu) > 60 else obj.contenu
    preview.short_description = _('Aperçu')


# ═══════════════════════════════════════════════════════════════════════
# DEMANDE D'INTERVENTION
# ═══════════════════════════════════════════════════════════════════════

class DemandeInterventionPhotoInline(admin.TabularInline):
    model = DemandeInterventionPhoto
    extra = 1
    fields = ('image', 'legende', 'ordre')


@admin.register(DemandeIntervention)
class DemandeInterventionAdmin(admin.ModelAdmin):
    list_display = (
        'numero', 'user', 'artisan', 'type_intervention',
        'urgence', 'statut', 'prix_propose', 'created_at',
    )
    list_filter = ('statut', 'type_intervention', 'urgence', 'disponibilite_preferee')
    search_fields = (
        'numero', 'description', 'user__telephone',
        'artisan__nom_commerce', 'type_libre',
    )
    list_editable = ('statut',)
    autocomplete_fields = ('user', 'artisan', 'adresse', 'conversation')
    readonly_fields = ('numero', 'created_at', 'updated_at',
                       'acceptee_le', 'terminee_le')
    inlines = [DemandeInterventionPhotoInline]
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    fieldsets = (
        (None, {
            'fields': ('numero', 'user', 'artisan', 'statut', 'raison_refus'),
        }),
        (_('Description'), {
            'fields': ('type_intervention', 'type_libre', 'description', 'urgence'),
        }),
        (_('Lieu'), {
            'fields': ('adresse', 'adresse_snapshot', 'description_acces'),
        }),
        (_('Disponibilité & devis'), {
            'fields': ('disponibilite_preferee', 'date_proposee', 'prix_propose'),
        }),
        (_('Lien chat'), {
            'fields': ('conversation',),
        }),
        (_('Dates clés'), {
            'fields': ('created_at', 'acceptee_le', 'terminee_le', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


@admin.register(DemandeInterventionPhoto)
class DemandeInterventionPhotoAdmin(admin.ModelAdmin):
    list_display = ('demande', 'legende', 'ordre', 'created_at')
    search_fields = ('demande__numero', 'legende')
    autocomplete_fields = ('demande',)
    list_editable = ('ordre',)