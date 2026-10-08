"""Modèles propres au module locations (Phase V2).

ProfilEtablissement : fiche établissement (hôtel, résidence meublée…),
extension 1-1 de ProfilPartenaire — même principe que
apps.restaurants.ProfilRestaurant. Localisation, contacts, logo, couverture
et description restent ceux du partenaire (non dupliqués). Les chambres /
unités vendues sont des Article + catalog.Hebergement.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.users.models import ProfilPartenaire


class ProfilEtablissement(models.Model):

    class TypeEtablissement(models.TextChoices):
        HOTEL = 'hotel', _('Hôtel')
        RESIDENCE_MEUBLEE = 'residence_meublee', _('Résidence meublée')
        AUBERGE = 'auberge', _('Auberge')
        MOTEL = 'motel', _('Motel')
        AUTRE = 'autre', _('Autre')

    class PetitDejeuner(models.TextChoices):
        INCLUS = 'inclus', _('Inclus')
        EN_OPTION = 'en_option', _('En option')
        NON = 'non', _('Non proposé')

    partenaire = models.OneToOneField(
        ProfilPartenaire, on_delete=models.CASCADE,
        related_name='profil_etablissement', verbose_name=_('partenaire'))
    type_etablissement = models.CharField(
        _('type d\'établissement'), max_length=20, choices=TypeEtablissement.choices,
        default=TypeEtablissement.HOTEL)
    etoiles = models.PositiveSmallIntegerField(_('étoiles (0-5)'), blank=True, null=True)
    heure_arrivee = models.TimeField(_('heure d\'arrivée (check-in)'), blank=True, null=True)
    heure_depart = models.TimeField(_('heure de départ (check-out)'), blank=True, null=True)
    equipements = models.JSONField(
        _('équipements de l\'établissement'), default=list, blank=True,
        help_text=_('Liste parmi apps.locations.services.EQUIPEMENTS_ETABLISSEMENT_LIBELLES.'))
    petit_dejeuner = models.CharField(
        _('petit-déjeuner'), max_length=10, choices=PetitDejeuner.choices, default=PetitDejeuner.NON)
    prix_petit_dejeuner = models.DecimalField(
        _('prix du petit-déjeuner (FCFA)'), max_digits=12, decimal_places=0, blank=True, null=True)
    politique_annulation = models.TextField(_('politique d\'annulation'), blank=True)
    conditions = models.TextField(
        _('conditions'), blank=True, help_text=_('Caution, pièces exigées…'))

    # Traçabilité (hôtelier, ou admin à sa place) — même convention que Logement.
    modifie_par_role = models.CharField(_('modifié par (rôle)'), max_length=20, blank=True)
    modifie_par_nom = models.CharField(_('modifié par (nom)'), max_length=150, blank=True)
    created_at = models.DateTimeField(_('créé le'), auto_now_add=True)
    updated_at = models.DateTimeField(_('modifié le'), auto_now=True)

    class Meta:
        verbose_name = _('fiche établissement')
        verbose_name_plural = _('fiches établissement')

    def __str__(self):
        return f'Fiche établissement — {self.partenaire.nom_commerce}'
