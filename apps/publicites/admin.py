from django.contrib import admin

from .models import (
    FormulePublicite, ImagePublicite, ImpressionPublicite,
    ParametresPublicite, Publicite,
)


@admin.register(FormulePublicite)
class FormuleAdmin(admin.ModelAdmin):
    list_display = ('nom', 'prix', 'priorite', 'duree_jours', 'passages_par_jour',
                    'quota_partenaires', 'acces_heures_affluence',
                    'cible_pourcentage_actifs', 'est_active')
    list_filter = ('est_active', 'acces_heures_affluence', 'video_autorisee')


class ImagePubliciteInline(admin.TabularInline):
    model = ImagePublicite
    extra = 0


@admin.register(Publicite)
class PubliciteAdmin(admin.ModelAdmin):
    list_display = ('titre', 'partenaire', 'formule', 'statut',
                    'nb_personnes_touchees', 'nb_impressions', 'nb_clics',
                    'stats_visibles_partenaire', 'debut_diffusion', 'fin_diffusion')
    list_filter = ('statut', 'formule', 'stats_visibles_partenaire')
    search_fields = ('titre', 'partenaire__nom_commerce')
    inlines = [ImagePubliciteInline]


@admin.register(ImpressionPublicite)
class ImpressionAdmin(admin.ModelAdmin):
    list_display = ('publicite', 'utilisateur', 'type_affichage', 'minute_session', 'cliquee', 'cree_le')
    list_filter = ('type_affichage', 'cliquee')


@admin.register(ParametresPublicite)
class ParametresPubliciteAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'affluence_debut', 'affluence_fin',
                    'calcul_affluence_auto', 'validation_auto',
                    'interstitiel_minute_min', 'interstitiel_minute_max',
                    'interstitiel_ratio_session_courte')

    def has_add_permission(self, request):
        return not ParametresPublicite.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
