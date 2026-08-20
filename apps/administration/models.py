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
        ACCEPTER_PARTENAIRE = 'accepter_partenaire', 'Demande partenaire acceptée'
        REJETER_PARTENAIRE = 'rejeter_partenaire', 'Demande partenaire rejetée'
        CREER_PARTENAIRE = 'creer_partenaire', 'Création d\'un partenaire (démarcheur)'

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


class PermissionsAdmin(ModeleBase):
    """Permissions granulaires d'un compte admin (is_staff, non super-admin).

    Le super-admin (is_superuser) ignore ces cases : il peut tout.
    Un admin ne peut faire QUE ce qui est coché ici. Par défaut : rien.

    La modération de comptes se décline par rôle cible (client / partenaire
    / admin) : ex. un admin peut avoir le droit de suspendre des clients
    mais pas des admins.
    """
    admin = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='permissions_admin', verbose_name='compte admin',
    )

    # ── A. Modération de comptes (× client / partenaire / admin) ─────
    # suspendre
    suspendre_client = models.BooleanField('suspendre — clients', default=False)
    suspendre_partenaire = models.BooleanField('suspendre — partenaires', default=False)
    suspendre_admin = models.BooleanField('suspendre — admins', default=False)
    # reactiver
    reactiver_client = models.BooleanField('réactiver — clients', default=False)
    reactiver_partenaire = models.BooleanField('réactiver — partenaires', default=False)
    reactiver_admin = models.BooleanField('réactiver — admins', default=False)
    # bannir
    bannir_client = models.BooleanField('bannir — clients', default=False)
    bannir_partenaire = models.BooleanField('bannir — partenaires', default=False)
    bannir_admin = models.BooleanField('bannir — admins', default=False)
    # supprimer douce
    supprimer_soft_client = models.BooleanField('supprimer (douce) — clients', default=False)
    supprimer_soft_partenaire = models.BooleanField('supprimer (douce) — partenaires', default=False)
    supprimer_soft_admin = models.BooleanField('supprimer (douce) — admins', default=False)
    # supprimer definitive
    supprimer_hard_client = models.BooleanField('supprimer (définitive) — clients', default=False)
    supprimer_hard_partenaire = models.BooleanField('supprimer (définitive) — partenaires', default=False)
    supprimer_hard_admin = models.BooleanField('supprimer (définitive) — admins', default=False)
    # restaurer
    restaurer_client = models.BooleanField('restaurer — clients', default=False)
    restaurer_partenaire = models.BooleanField('restaurer — partenaires', default=False)
    restaurer_admin = models.BooleanField('restaurer — admins', default=False)

    # ── B. Partenaires ───────────────────────────────────────────────
    masquer_partenaire = models.BooleanField('masquer / afficher un partenaire', default=False)
    certifier_partenaire = models.BooleanField('donner / retirer le badge certifié', default=False)
    accorder_faveur = models.BooleanField('accorder / retirer une faveur', default=False)
    valider_devenir_partenaire = models.BooleanField('valider une demande « devenir partenaire »', default=False)
    creer_partenaire = models.BooleanField('créer un partenaire de A à Z (démarcheur)', default=False)

    # ── C. Publicités ────────────────────────────────────────────────
    valider_publicite = models.BooleanField('valider / rejeter une publicité', default=False)
    offrir_campagne = models.BooleanField('offrir / retirer une campagne', default=False)

    # ── D. Commandes & paiements ─────────────────────────────────────
    valider_commande = models.BooleanField('valider / rejeter une commande', default=False)
    valider_paiement = models.BooleanField('valider / rejeter un paiement', default=False)

    # ── E. Configuration ─────────────────────────────────────────────
    modifier_plans_formules = models.BooleanField('modifier les plans et formules', default=False)

    # ── F. Consultation & données ────────────────────────────────────
    voir_stats = models.BooleanField('voir les stats', default=False)
    voir_indicateurs = models.BooleanField('voir les indicateurs partenaires', default=False)
    lire_journal = models.BooleanField('lire le journal d\'audit', default=False)
    exporter_csv = models.BooleanField('exporter en CSV', default=False)

    # ── G. Gestion ────────────────────────────────────────────────────
    gerer_admins = models.BooleanField(
        'gérer les comptes admins (créer, éditer capacités, révoquer)',
        default=False,
    )

    class Meta:
        verbose_name = 'permissions admin'
        verbose_name_plural = 'permissions des admins'

    def __str__(self):
        return f'Permissions de {self.admin}'

