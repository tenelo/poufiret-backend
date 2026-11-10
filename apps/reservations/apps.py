from django.apps import AppConfig


class ReservationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.reservations'

    def ready(self):
        # Invalidation du cache des disponibilités (demandes, fiches véhicule / hébergement).
        from . import signals
        signals.connecter_fiches()
