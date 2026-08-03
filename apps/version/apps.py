from django.apps import AppConfig


class VersionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.version'
    verbose_name = 'Contrôle de version'
