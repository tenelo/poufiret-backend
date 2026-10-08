"""Demandes de visite / réservation, COMMUNES aux métiers de location
(maisons, véhicules ; chambres d'hôtel plus tard). App séparée
de apps.locations — même rôle transverse que apps.orders pour les
commandes catalogue (apps.orders ne dépend d'aucun vertical particulier ;
apps.reservations ne dépend pas de apps.locations non plus, seul
`objet` pointe vers un Article générique, quel que soit son type).
"""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class DemandeReservation(models.Model):
    """Une demande client, adressée à un partenaire, sur un objet (Article).
    L'admin est intermédiaire entre client et partenaire, comme pour les
    commandes (apps.orders.Commande)."""

    class Nature(models.TextChoices):
        VISITE = 'visite', _('Visite')
        RESERVATION = 'reservation', _('Réservation')

    class Statut(models.TextChoices):
        NOUVELLE = 'nouvelle', _('Nouvelle')
        EN_COURS = 'en_cours', _('En cours')
        CONFIRMEE = 'confirmee', _('Confirmée')
        REFUSEE = 'refusee', _('Refusée')
        ANNULEE = 'annulee', _('Annulée')
        TERMINEE = 'terminee', _('Terminée')

    numero = models.CharField(_('numéro'), max_length=30, unique=True)
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='demandes_reservation', verbose_name=_('client'),
    )
    partenaire = models.ForeignKey(
        'users.ProfilPartenaire', on_delete=models.PROTECT,
        related_name='demandes_reservation', verbose_name=_('partenaire'),
    )
    objet = models.ForeignKey(
        'catalog.Article', on_delete=models.PROTECT,
        related_name='demandes_reservation', verbose_name=_('objet (logement, véhicule…)'),
    )

    nature = models.CharField(_('nature'), max_length=15, choices=Nature.choices)
    date_souhaitee = models.DateTimeField(_('date souhaitée (visite)'), blank=True, null=True)
    date_debut = models.DateField(_('date de début (réservation)'), blank=True, null=True)
    date_fin = models.DateField(_('date de fin (réservation)'), blank=True, null=True)
    nb_personnes = models.PositiveIntegerField(_('nombre de personnes'), blank=True, null=True)
    message = models.TextField(_('message'), blank=True)
    telephone_contact = models.CharField(_('téléphone de contact'), max_length=20, blank=True)

    # Locations Phase V1 (véhicules) — null/vides pour les logements.
    avec_chauffeur = models.BooleanField(_('avec chauffeur'), blank=True, null=True)
    lieu_prise_en_charge = models.TextField(_('lieu de prise en charge'), blank=True)
    montant_estime = models.DecimalField(
        _('montant estimé (FCFA)'), max_digits=12, decimal_places=0, blank=True, null=True,
        help_text=_('Calculé à la création (jours × prix/jour).'))

    statut = models.CharField(
        _('statut'), max_length=12, choices=Statut.choices, default=Statut.NOUVELLE)
    raison_refus = models.TextField(_('raison du refus'), blank=True)
    annulee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        blank=True, null=True, related_name='demandes_annulees', verbose_name=_('annulée par'),
    )

    created_at = models.DateTimeField(_('créée le'), auto_now_add=True)
    confirmee_le = models.DateTimeField(_('confirmée le'), blank=True, null=True)
    terminee_le = models.DateTimeField(_('terminée le'), blank=True, null=True)
    updated_at = models.DateTimeField(_('modifiée le'), auto_now=True)

    class Meta:
        verbose_name = _('demande de visite/réservation')
        verbose_name_plural = _('demandes de visite/réservation')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['partenaire', 'statut', '-created_at']),
            models.Index(fields=['client', '-created_at']),
            models.Index(fields=['statut']),
        ]

    def __str__(self):
        return f'{self.numero} — {self.partenaire.nom_commerce}'


class HistoriqueDemande(models.Model):
    """Trace CHAQUE changement de statut, quel que soit le chemin (client,
    loueur, admin) — écrite depuis le point central
    apps.reservations.services.appliquer_transition_demande."""

    class ActeurRole(models.TextChoices):
        CLIENT = 'client', _('Client')
        LOUEUR = 'loueur', _('Loueur')
        ADMIN = 'admin', _('Admin')

    demande = models.ForeignKey(
        DemandeReservation, on_delete=models.CASCADE,
        related_name='historique', verbose_name=_('demande'),
    )
    statut = models.CharField(_('statut atteint'), max_length=12, choices=DemandeReservation.Statut.choices)
    acteur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        blank=True, null=True, related_name='+', verbose_name=_('acteur'),
    )
    acteur_role = models.CharField(_('rôle de l\'acteur'), max_length=10, choices=ActeurRole.choices)
    commentaire = models.TextField(_('commentaire'), blank=True)
    cree_le = models.DateTimeField(_('créé le'), auto_now_add=True)

    class Meta:
        verbose_name = _('historique de demande')
        verbose_name_plural = _('historiques de demande')
        ordering = ['cree_le']


class NoteAdminDemande(models.Model):
    """Note interne sur une demande, visible UNIQUEMENT par les admins
    habilités (jamais par le client ni le loueur)."""
    demande = models.ForeignKey(
        DemandeReservation, on_delete=models.CASCADE,
        related_name='notes_admin', verbose_name=_('demande'),
    )
    auteur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        blank=True, null=True, related_name='+', verbose_name=_('auteur'),
    )
    texte = models.TextField(_('texte'))
    cree_le = models.DateTimeField(_('créé le'), auto_now_add=True)

    class Meta:
        verbose_name = _('note admin de demande')
        verbose_name_plural = _('notes admin de demande')
        ordering = ['cree_le']
