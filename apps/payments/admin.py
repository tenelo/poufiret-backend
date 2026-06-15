from django.contrib import admin
from .models import Paiement


@admin.register(Paiement)
class PaiementAdmin(admin.ModelAdmin):
    list_display = ['montant', 'mode', 'statut', 'type_objet', 'user', 'cree_le', 'valide_le']
    list_filter = ['statut', 'mode', 'type_objet']
    search_fields = ['objet_id', 'reference_externe', 'user__telephone']
    readonly_fields = ['cree_le', 'modifie_le']
