from django.contrib import admin

from .models import JournalModeration


@admin.register(JournalModeration)
class JournalModerationAdmin(admin.ModelAdmin):
    list_display = ('cree_le', 'action', 'cible_identifiant', 'cible_role',
                    'acteur', 'motif')
    list_filter = ('action', 'cible_role', 'cree_le')
    search_fields = ('cible_identifiant', 'motif')
    readonly_fields = ('acteur', 'cible', 'cible_identifiant', 'cible_role',
                       'action', 'motif', 'cree_le', 'modifie_le')

    def has_add_permission(self, request):
        # Le journal se remplit uniquement via les actions de modération.
        return False

    def has_delete_permission(self, request, obj=None):
        # Audit : on ne supprime pas les entrées.
        return False
