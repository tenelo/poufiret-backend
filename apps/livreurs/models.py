"""Modeles de l'app livreurs : le livreur et sa position.

Module volontairement isole (reutilisable pour une app de livraison
autonome). La position peut venir de deux sources interchangeables
(telephone du livreur OU transpondeur materiel) — voir sources.py.
"""
from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.db import models
from apps.core.models import ModeleBase


class Livreur(ModeleBase):
    """Un livreur TeneLivr. Cree par l'admin (pas d'auto-inscription).
    Rattache a UNE ville (= Departement) pour l'instant."""

    class TypeVehicule(models.TextChoices):
        MOTO = 'moto', 'Moto (local)'
        VOITURE = 'voiture', 'Voiture (inter-regions)'

    class Statut(models.TextChoices):
        EN_LIGNE = 'en_ligne', 'En ligne'
        HORS_LIGNE = 'hors_ligne', 'Hors ligne'

    class SourcePosition(models.TextChoices):
        TELEPHONE = 'telephone', 'Telephone (app livreur)'
        TRANSPONDEUR = 'transpondeur', 'Transpondeur (boitier)'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profil_livreur',
        verbose_name='compte utilisateur',
    )
    ville = models.ForeignKey(
        'geo.Departement',
        on_delete=models.PROTECT,
        related_name='livreurs',
        verbose_name='ville de rattachement',
    )
    type_vehicule = models.CharField(
        max_length=10, choices=TypeVehicule.choices,
        default=TypeVehicule.MOTO,
    )
    statut = models.CharField(
        max_length=12, choices=Statut.choices,
        default=Statut.HORS_LIGNE,
    )
    source_position = models.CharField(
        max_length=12, choices=SourcePosition.choices,
        default=SourcePosition.TELEPHONE,
        help_text="D'ou vient la position : bascule telephone <-> transpondeur.",
    )
    # Identifiant du boitier transpondeur (rempli seulement si applicable).
    transpondeur_id = models.CharField(
        max_length=100, blank=True, default='',
        help_text='Identifiant materiel du transpondeur, si source = transpondeur.',
    )
    immatriculation = models.CharField(max_length=30, blank=True, default='')

    # Derniere position connue (quelle que soit la source).
    position = gis_models.PointField(
        geography=True, blank=True, null=True,
        verbose_name='derniere position GPS',
    )
    position_maj_le = models.DateTimeField(
        blank=True, null=True,
        verbose_name='position mise a jour le',
    )

    class Meta:
        verbose_name = 'livreur'
        verbose_name_plural = 'livreurs'

    def __str__(self):
        return f'{self.user} ({self.ville})'

    @property
    def est_disponible(self):
        """En ligne = peut recevoir des courses (la charge est geree par
        le nombre de courses actives + le refus, active plus tard)."""
        return self.statut == self.Statut.EN_LIGNE
