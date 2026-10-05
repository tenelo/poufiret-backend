from django.db.models.signals import post_init, post_save
from django.dispatch import receiver

from apps.users.models import ProfilPartenaire

from .correspondances import appliquer_correspondance


@receiver(post_init, sender=ProfilPartenaire)
def memoriser_type_charge(sender, instance, **kwargs):
    instance._type_charge = instance.type_partenaire


@receiver(post_save, sender=ProfilPartenaire)
def rattacher_categorie_du_type(sender, instance, created, **kwargs):
    if created or instance.type_partenaire != instance._type_charge:
        appliquer_correspondance(instance)
    instance._type_charge = instance.type_partenaire
