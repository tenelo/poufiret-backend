"""Modèles du bloc administration (G5).

Pour l'instant : le journal d'audit de la modération de comptes.
Chaque action de modération (suspension, bannissement, suppression,
réactivation) DOIT créer une entrée ici — traçabilité obligatoire
décidée avec Tenelo : qui, quand, quoi, sur qui, pourquoi.
"""
from django.conf import settings
from django.db import models

from apps.core.models import ModeleBase


class JournalModeration(ModeleBase):
    """Trace d'audit d'une action de modération sur un compte."""

    class Action(models.TextChoices):
        SUSPENDRE = 'suspendre', 'Suspension'
        REACTIVER = 'reactiver', 'Réactivation'
        BANNIR = 'bannir', 'Bannissement'
        SUPPRIMER_SOFT = 'supprimer_soft', 'Suppression douce'
        SUPPRIMER_HARD = 'supprimer_hard', 'Suppression définitive'
        RESTAURER = 'restaurer', 'Restauration (annule suppression douce)'
        ACCORDER_FAVEUR = 'accorder_faveur', 'Octroi d\'une faveur'
        RETIRER_FAVEUR = 'retirer_faveur', 'Retrait d\'une faveur'

    # Qui a agi (le super-admin). SET_NULL pour garder la trace même si
    # l'acteur est supprimé plus tard.
    acteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name='actions_moderation',
        verbose_name='acteur (super-admin)',
    )
    # Sur qui. Null=True car une suppression définitive efface la cible :
    # on conserve alors son identifiant en clair dans cible_identifiant.
    cible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='moderations_subies',
        verbose_name='cible',
    )
    cible_identifiant = models.CharField(
        'identifiant de la cible', max_length=150, blank=True,
        help_text='Téléphone/identifiant conservé en clair (surtout si la '
                  'cible est supprimée définitivement).',
    )
    cible_role = models.CharField('rôle de la cible', max_length=20, blank=True)
    action = models.CharField('action', max_length=20, choices=Action.choices)
    motif = models.CharField('motif', max_length=255, blank=True)

    class Meta:
        verbose_name = 'entrée de journal de modération'
        verbose_name_plural = 'journal de modération'
        ordering = ['-cree_le']
        indexes = [
            models.Index(fields=['cible', 'cree_le']),
            models.Index(fields=['action', 'cree_le']),
        ]

    def __str__(self):
        return (f'{self.get_action_display()} — {self.cible_identifiant} '
                f'par {self.acteur} ({self.cree_le:%d/%m/%Y %H:%M})')
