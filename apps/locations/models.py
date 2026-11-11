"""Modèles propres au module locations (Phase V2).

ProfilEtablissement : fiche établissement (hôtel, résidence meublée…),
extension 1-1 de ProfilPartenaire — même principe que
apps.restaurants.ProfilRestaurant. Localisation, contacts, logo, couverture
et description restent ceux du partenaire (non dupliqués). Les chambres /
unités vendues sont des Article + catalog.Hebergement.
"""
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.images import ImagesOptimiseesMixin
from apps.core.models import ModeleBase
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


class ParametresLocations(ModeleBase):
    """Paramètres modifiables du module locations (ligne unique, obtenir())."""

    nb_max_images_vitrine = models.PositiveSmallIntegerField(
        "nombre maximum d'images de vitrine", default=10, validators=[MinValueValidator(1)],
        help_text="Carrousel d'un hôtel / d'une résidence. Baisser ce nombre ne supprime rien : "
                  "la page publique ne montre que les premières images.")

    class Meta:
        verbose_name = 'paramètres locations'
        verbose_name_plural = 'paramètres locations'

    def save(self, *args, **kwargs):
        # Singleton : on force une seule ligne
        self.pk = self.pk or self.__class__.objects.first() and self.__class__.objects.first().pk or None
        super().save(*args, **kwargs)

    @classmethod
    def obtenir(cls):
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj

    def __str__(self):
        return f'Paramètres locations (vitrine : {self.nb_max_images_vitrine} images max)'


class ImageVitrine(ImagesOptimiseesMixin, ModeleBase):
    """Élément de la vitrine d'un établissement (carrousel de sa page publique) :
    SOIT une photo existante d'un de ses hébergements (référence, sans copie de
    fichier), SOIT une photo propre à l'établissement (façade, piscine…).
    Photo de chambre supprimée → l'élément disparaît (CASCADE) ; désactivée (ou
    hébergement désactivé) → ignoré partout (voir services.vitrine_qs)."""
    champs_images = ('image',)

    etablissement = models.ForeignKey(
        ProfilEtablissement, on_delete=models.CASCADE, related_name='images_vitrine',
        verbose_name=_('établissement'))
    image_hebergement = models.ForeignKey(
        'catalog.ArticleImage', on_delete=models.CASCADE, null=True, blank=True,
        related_name='vitrines', verbose_name=_("photo d'hébergement"))
    image = models.ImageField(_('photo propre'), upload_to='vitrines/', blank=True)
    legende = models.CharField(_('légende'), max_length=200, blank=True)
    ordre = models.IntegerField(_('ordre'), default=0)

    class Meta:
        verbose_name = _('image de vitrine')
        verbose_name_plural = _('images de vitrine')
        ordering = ['etablissement', 'ordre', 'cree_le']
        constraints = [
            # Soit une photo d'hébergement, soit une photo propre — jamais les deux.
            models.CheckConstraint(
                check=(Q(image_hebergement__isnull=False) & Q(image=''))
                | (Q(image_hebergement__isnull=True) & ~Q(image='')),
                name='image_vitrine_une_seule_source'),
            # Une photo de chambre au plus une fois par vitrine.
            models.UniqueConstraint(
                fields=['etablissement', 'image_hebergement'],
                condition=Q(image_hebergement__isnull=False),
                name='unique_image_hebergement_par_vitrine'),
        ]

    def __str__(self):
        return f'Vitrine {self.etablissement.partenaire.nom_commerce} — {self.ordre}'
