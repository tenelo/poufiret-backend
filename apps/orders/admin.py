"""
Configuration de l'admin Django pour l'app orders.
"""
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import Panier, LignePanier, Commande, LigneCommande


# ═══════════════════════════════════════════════════════════════════════
# PANIER
# ═══════════════════════════════════════════════════════════════════════

class LignePanierInline(admin.TabularInline):
    model = LignePanier
    extra = 0
    fields = ('article', 'quantite', 'prix_unitaire', 'note_speciale')
    autocomplete_fields = ('article',)
    readonly_fields = ('created_at',)


@admin.register(Panier)
class PanierAdmin(admin.ModelAdmin):
    list_display = ('user', 'commercant', 'nb_lignes', 'updated_at', 'created_at')
    search_fields = ('user__telephone', 'commercant__nom_commerce')
    autocomplete_fields = ('user', 'commercant')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [LignePanierInline]
    ordering = ('-updated_at',)

    def nb_lignes(self, obj):
        return obj.lignes.count()
    nb_lignes.short_description = _('Articles')


# ═══════════════════════════════════════════════════════════════════════
# COMMANDE
# ═══════════════════════════════════════════════════════════════════════

class LigneCommandeInline(admin.TabularInline):
    model = LigneCommande
    extra = 0
    fields = ('nom_article', 'variante_nom', 'quantite',
              'prix_unitaire', 'prix_ligne', 'note_speciale')
    readonly_fields = ('nom_article', 'variante_nom', 'quantite',
                       'prix_unitaire', 'prix_ligne', 'note_speciale')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Commande)
class CommandeAdmin(admin.ModelAdmin):
    list_display = (
        'numero', 'user', 'commercant', 'statut',
        'mode_livraison', 'total', 'created_at',
    )
    list_filter = ('statut', 'mode_livraison', 'mode_paiement')
    search_fields = (
        'numero', 'user__telephone', 'user__first_name',
        'commercant__nom_commerce',
    )
    list_editable = ('statut',)
    autocomplete_fields = ('user', 'commercant', 'adresse', 'annulee_par')
    readonly_fields = (
        'numero', 'created_at', 'acceptee_le', 'prete_le',
        'livree_le', 'updated_at',
    )
    inlines = [LigneCommandeInline]
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    fieldsets = (
        (None, {
            'fields': ('numero', 'user', 'commercant', 'statut', 'raison_refus'),
        }),
        (_('Livraison'), {
            'fields': ('mode_livraison', 'adresse', 'adresse_snapshot', 'heure_souhaitee'),
        }),
        (_('Montants'), {
            'fields': ('sous_total', 'frais_livraison', 'total', 'mode_paiement'),
        }),
        (_('Notes & annulation'), {
            'fields': ('notes_client', 'notes_commercant', 'annulee_par'),
            'classes': ('collapse',),
        }),
        (_('Dates clés'), {
            'fields': ('created_at', 'acceptee_le', 'prete_le', 'livree_le', 'updated_at'),
            'classes': ('collapse',),
        }),
    )