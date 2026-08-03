from django.contrib import admin

from .models import ControleVersion


@admin.register(ControleVersion)
class ControleVersionAdmin(admin.ModelAdmin):
    list_display = ('version_min_obligatoire', 'version_conseillee',
                    'lien_store_android', 'lien_store_ios')

    def has_add_permission(self, request):
        # Singleton : on n'ajoute pas une 2e ligne si une existe deja.
        return not ControleVersion.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
