"""Modèle Paiement (Module 5). Traçabilité ; activation via flag waffle 'paiement_actif'."""
from django.db import models
from django.utils.translation import gettext_lazy as _
from apps.core.models import ModeleBase
from apps.users.models import User, ProfilPartenaire


class Paiement(ModeleBase):
    class Mode(models.TextChoices):
        CASH = 'cash', _('Espèces')
        ORANGE = 'orange_money', _('Orange Money')
        MTN = 'mtn_money', _('MTN Money')
        WAVE = 'wave', _('Wave')
        VIREMENT = 'virement', _('Virement bancaire')

    class Statut(models.TextChoices):
        EN_ATTENTE = 'en_attente', _('En attente')
        CONFIRME = 'confirme', _('Confirmé')
        REJETE = 'rejete', _('Rejeté')
        REMBOURSE = 'rembourse', _('Remboursé')

    class Objet(models.TextChoices):
        ABONNEMENT = 'abonnement', _('Abonnement')
        PUBLICITE = 'publicite', _('Publicité')
        COMMANDE = 'commande', _('Commande')
        AUTRE = 'autre', _('Autre')

    user = models.ForeignKey(User, on_delete=models.PROTECT,
        related_name='paiements', verbose_name=_('payeur'))
    partenaire = models.ForeignKey(ProfilPartenaire, on_delete=models.SET_NULL,
        blank=True, null=True, related_name='paiements', verbose_name=_('partenaire concerné'))

    type_objet = models.CharField(_('type d\'objet payé'), max_length=20,
        choices=Objet.choices, default=Objet.ABONNEMENT)
    objet_id = models.CharField(_('référence de l\'objet'), max_length=64, blank=True,
        help_text=_('ID libre de l\'élément payé (abonnement, commande, pub).'))

    montant = models.DecimalField(_('montant (FCFA)'), max_digits=12, decimal_places=0)
    mode = models.CharField(_('mode'), max_length=20, choices=Mode.choices, default=Mode.CASH)
    statut = models.CharField(_('statut'), max_length=20, choices=Statut.choices,
        default=Statut.EN_ATTENTE)

    reference_externe = models.CharField(_('référence opérateur'), max_length=128, blank=True,
        help_text=_('ID de transaction mobile money / banque (rempli à l\'intégration réelle).'))
    note = models.TextField(_('note'), blank=True)

    valide_par = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True,
        related_name='paiements_valides', verbose_name=_('validé par (admin)'))
    valide_le = models.DateTimeField(_('validé le'), blank=True, null=True)

    class Meta:
        verbose_name = _('paiement')
        verbose_name_plural = _('paiements')
        ordering = ['-cree_le']
        indexes = [
            models.Index(fields=['statut', '-cree_le']),
            models.Index(fields=['user', '-cree_le']),
            models.Index(fields=['type_objet', 'objet_id']),
        ]

    def __str__(self):
        return f"{self.montant} FCFA — {self.get_mode_display()} — {self.get_statut_display()}"
