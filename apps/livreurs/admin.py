from django.contrib import admin
from .models import Livreur


@admin.register(Livreur)
class LivreurAdmin(admin.ModelAdmin):
    list_display = ('user', 'ville', 'type_vehicule', 'statut',
                    'source_position', 'position_maj_le')
    list_filter = ('statut', 'type_vehicule', 'source_position', 'ville')
    search_fields = ('user__telephone', 'user__first_name', 'user__last_name',
                     'immatriculation', 'transpondeur_id')
    autocomplete_fields = ('user', 'ville')
    readonly_fields = ('position', 'position_maj_le')
