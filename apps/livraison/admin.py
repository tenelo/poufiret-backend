from django.contrib import admin
from .models import Course


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('numero', 'statut', 'ville', 'livreur',
                    'description_colis', 'prix', 'cree_le')
    list_filter = ('statut', 'ville', 'type_demandeur')
    search_fields = ('numero', 'a_quartier', 'b_quartier',
                     'a_nom_contact', 'b_nom_contact')
    readonly_fields = ('numero', 'assignee_le', 'acceptee_le',
                       'colis_pris_le', 'livree_le', 'annulee_le')
    autocomplete_fields = ('demandeur', 'ville', 'livreur')
