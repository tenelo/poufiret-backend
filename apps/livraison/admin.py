from django.contrib import admin

from .models import ParametresLivraison, IconeMotard, ProfilLivraison
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


@admin.register(ParametresLivraison)
class ParametresLivraisonAdmin(admin.ModelAdmin):
    list_display = ('prix_course',)

    def has_add_permission(self, request):
        # Singleton : pas d'ajout si une ligne existe deja.
        return not ParametresLivraison.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(IconeMotard)
class IconeMotardAdmin(admin.ModelAdmin):
    list_display = ('nom', 'role', 'est_active', 'apercu')
    list_filter = ('role', 'est_active')
    list_editable = ('est_active',)
    search_fields = ('nom',)
    readonly_fields = ('apercu',)

    @admin.display(description='apercu')
    def apercu(self, obj):
        from django.utils.html import format_html
        if obj.image:
            return format_html(
                '<img src="{}" style="height:48px;background:#ddd;'
                'border-radius:6px;padding:2px" />', obj.image.url)
        return '—'


@admin.register(ProfilLivraison)
class ProfilLivraisonAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'departement', 'nom_bureau', 'est_actif')
    list_filter = ('departement', 'est_actif')
    search_fields = ('user__telephone', 'user__username', 'nom_bureau')
    autocomplete_fields = ('user', 'departement')

    @admin.display(description='rôle')
    def role(self, obj):
        return obj.user.get_role_display()
