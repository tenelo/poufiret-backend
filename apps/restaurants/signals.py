from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.users.models import ProfilPartenaire

from . import services


@receiver(post_save, sender=ProfilPartenaire)
def creer_fiche_restaurant(sender, instance, **kwargs):
    if instance.type_partenaire in services.TYPES_RESTAURATION:
        services.fiche_de(instance)
