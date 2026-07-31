from django.contrib import admin

from .models import Departement, District, Region


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ('nom', 'ordre')
    list_editable = ('ordre',)


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ('nom', 'district', 'ordre')
    list_filter = ('district',)
    list_editable = ('ordre',)


@admin.register(Departement)
class DepartementAdmin(admin.ModelAdmin):
    list_display = ('nom', 'region', 'district_affiche', 'ordre', 'est_actif')
    list_filter = ('region__district', 'region', 'est_actif')
    list_editable = ('ordre', 'est_actif')
    search_fields = ('nom',)

    @admin.display(description='district')
    def district_affiche(self, obj):
        return obj.region.district.nom
