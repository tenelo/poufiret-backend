"""Invalidation du cache des disponibilités (apps.reservations.disponibilite) :
à chaque enregistrement ou suppression d'une demande (changement de statut
compris) et à chaque modification d'une fiche véhicule / hébergement
(nb_unites, disponibilité)."""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .disponibilite import invalider
from .models import DemandeReservation


@receiver([post_save, post_delete], sender=DemandeReservation)
def invalider_disponibilites_demande(sender, instance, **kwargs):
    invalider(instance.objet_id)


def _invalider_fiche(sender, instance, **kwargs):
    invalider(instance.article_id)


def connecter_fiches():
    from apps.catalog.models import Hebergement, Vehicule
    for modele in (Vehicule, Hebergement):
        post_save.connect(_invalider_fiche, sender=modele, dispatch_uid=f'dispo_fiche_{modele.__name__}')
        post_delete.connect(_invalider_fiche, sender=modele, dispatch_uid=f'dispo_fiche_del_{modele.__name__}')
