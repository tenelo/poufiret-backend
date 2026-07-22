from django.contrib import admin

from .models import ParametresAnalytics, ProfilNavigation, TempsSessionUtilisateur


@admin.register(TempsSessionUtilisateur)
class TempsSessionAdmin(admin.ModelAdmin):
    list_display = ('utilisateur', 'debut', 'dernier_ping', 'duree_secondes', 'source', 'est_active')
    list_filter = ('source', 'est_active')
    search_fields = ('utilisateur__telephone', 'utilisateur__username')
    date_hierarchy = 'debut'


@admin.register(ProfilNavigation)
class ProfilNavigationAdmin(admin.ModelAdmin):
    list_display = ('utilisateur', 'mois_reference', 'nb_articles_vus_mois', 'nb_vues_catalogue_mois',
                    'temps_cumule_secondes_mois', 'derniere_activite', 'est_client_actif')
    search_fields = ('utilisateur__telephone', 'utilisateur__username')

    @admin.display(boolean=True, description='client actif')
    def est_client_actif(self, obj):
        return obj.est_client_actif


@admin.register(ParametresAnalytics)
class ParametresAnalyticsAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'seuil_jours_connexion', 'seuil_articles_mois', 'seuil_minutes_mois')

    def has_add_permission(self, request):
        # Singleton : pas d'ajout si une ligne existe déjà
        return not ParametresAnalytics.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
