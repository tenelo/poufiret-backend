from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import ModeleBase


class TypeAffichage(models.TextChoices):
    CARROUSEL = 'carrousel', 'Carrousel (accueil)'
    INTERSTITIEL = 'interstitiel', 'Interstitiel (70-80% écran)'
    BANDEAU_BAS = 'bandeau_bas', 'Bandeau bas transparent'
    PAGE_PUBLICITES = 'page_publicites', 'Page Publicités'


class FormulePublicite(ModeleBase):
    """Forfait de publicité (500F, 3000F, 100 000F...), configurable en admin."""

    nom = models.CharField('nom', max_length=100)
    prix = models.PositiveIntegerField('prix (FCFA)')
    priorite = models.PositiveIntegerField(
        'priorité', default=0,
        help_text='Plus élevé = passe avant dans le carrousel',
    )
    est_active = models.BooleanField('formule active', default=True)
    # Diffusion
    duree_jours = models.PositiveIntegerField('durée (jours)', default=1)
    passages_par_jour = models.PositiveIntegerField('passages par jour', default=1)
    duree_affichage_secondes = models.PositiveIntegerField(
        'durée d\'un passage (s)', default=5,
    )
    quota_partenaires = models.PositiveIntegerField(
        'quota de partenaires simultanés', default=50,
        help_text='1 = exclusivité totale',
    )
    acces_heures_affluence = models.BooleanField(
        'accès aux heures d\'affluence', default=False,
    )
    types_affichage = models.JSONField(
        'types d\'affichage autorisés', default=list,
        help_text='Liste parmi : carrousel, interstitiel, bandeau_bas, page_publicites',
    )
    # Contenus autorisés
    nb_images_max = models.PositiveIntegerField('nombre d\'images max', default=1)
    video_autorisee = models.BooleanField('vidéo autorisée', default=False)
    duree_video_max_secondes = models.PositiveIntegerField(
        'durée vidéo max (s)', default=30,
    )
    # Garantie de couverture (formules chères)
    cible_pourcentage_actifs = models.PositiveIntegerField(
        'cible % clients actifs', null=True, blank=True,
        help_text='Ex. 80 : la pub reste active jusqu\'à toucher 80% des clients actifs. Vide = pas de garantie.',
    )

    class Meta:
        verbose_name = 'formule de publicité'
        verbose_name_plural = 'formules de publicité'
        ordering = ['-priorite', '-prix']

    def __str__(self):
        return f'{self.nom} — {self.prix} FCFA'


class Publicite(ModeleBase):
    """Campagne publicitaire d'un partenaire."""

    class Statut(models.TextChoices):
        BROUILLON = 'brouillon', 'Brouillon'
        EN_ATTENTE_PAIEMENT = 'en_attente_paiement', 'En attente de paiement'
        EN_ATTENTE_VALIDATION = 'en_attente_validation', 'En attente de validation'
        ACTIVE = 'active', 'Active'
        TERMINEE = 'terminee', 'Terminée'
        REJETEE = 'rejetee', 'Rejetée'

    partenaire = models.ForeignKey(
        'users.ProfilPartenaire', on_delete=models.CASCADE,
        related_name='publicites', verbose_name='partenaire',
    )
    formule = models.ForeignKey(
        FormulePublicite, on_delete=models.PROTECT,
        related_name='publicites', verbose_name='formule',
    )
    titre = models.CharField('titre', max_length=150)
    description = models.TextField('description', blank=True)
    image_couverture = models.ImageField(
        'image de couverture', upload_to='publicites/couvertures/',
        help_text='Flyer/affiche affichée dans le carrousel et les listes',
    )
    video = models.FileField(
        'vidéo', upload_to='publicites/videos/', null=True, blank=True,
    )
    statut = models.CharField(
        'statut', max_length=25,
        choices=Statut.choices, default=Statut.BROUILLON,
    )
    paiement = models.ForeignKey(
        'payments.Paiement', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='publicites',
    )
    debut_diffusion = models.DateTimeField('début de diffusion', null=True, blank=True)
    fin_diffusion = models.DateTimeField('fin de diffusion', null=True, blank=True)
    # Compteurs dénormalisés
    nb_personnes_touchees = models.PositiveIntegerField('personnes touchées', default=0)
    nb_impressions = models.PositiveIntegerField('impressions totales', default=0)
    nb_clics = models.PositiveIntegerField('clics', default=0)
    stats_visibles_partenaire = models.BooleanField(
        'stats visibles par le partenaire', default=False,
    )

    class Meta:
        verbose_name = 'publicité'
        verbose_name_plural = 'publicités'
        ordering = ['-cree_le']

    @property
    def cible_atteinte(self):
        """True si la cible % de clients actifs est atteinte (ou pas de cible)."""
        cible = self.formule.cible_pourcentage_actifs
        if not cible:
            return True
        from apps.analytics.models import ProfilNavigation
        profils = ProfilNavigation.objects.all()
        nb_actifs = sum(1 for p in profils if p.est_client_actif)
        if nb_actifs == 0:
            return False
        return (self.nb_personnes_touchees / nb_actifs) * 100 >= cible

    def __str__(self):
        return f'{self.titre} ({self.partenaire}) — {self.get_statut_display()}'


class ImagePublicite(ModeleBase):
    publicite = models.ForeignKey(
        Publicite, on_delete=models.CASCADE,
        related_name='images', verbose_name='publicité',
    )
    image = models.ImageField('image', upload_to='publicites/images/')
    ordre = models.PositiveIntegerField('ordre', default=0)

    class Meta:
        verbose_name = 'image de publicité'
        verbose_name_plural = 'images de publicité'
        ordering = ['ordre']

    def __str__(self):
        return f'Image {self.ordre} — {self.publicite.titre}'


class ImpressionPublicite(ModeleBase):
    publicite = models.ForeignKey(
        Publicite, on_delete=models.CASCADE,
        related_name='impressions', verbose_name='publicité',
    )
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='impressions_publicites',
    )
    type_affichage = models.CharField(
        'type d\'affichage', max_length=20,
        choices=TypeAffichage.choices, default=TypeAffichage.CARROUSEL,
    )
    minute_session = models.PositiveIntegerField('minute de session', null=True, blank=True)
    cliquee = models.BooleanField('cliquée', default=False)

    class Meta:
        verbose_name = 'impression de publicité'
        verbose_name_plural = 'impressions de publicité'
        indexes = [
            models.Index(fields=['publicite', 'utilisateur']),
        ]

    def __str__(self):
        return f'{self.publicite.titre} — {self.utilisateur or "anonyme"}'


class ParametresPublicite(ModeleBase):
    """Paramètres globaux de diffusion (ligne unique)."""

    affluence_debut = models.TimeField('début heures d\'affluence', default='18:00')
    affluence_fin = models.TimeField('fin heures d\'affluence', default='21:00')
    calcul_affluence_auto = models.BooleanField(
        'calcul automatique des heures d\'affluence (analytics)', default=False,
    )
    intervalle_min_interstitiel_secondes = models.PositiveIntegerField(
        'intervalle min entre 2 interstitiels (s)', default=300,
    )
    validation_auto = models.BooleanField(
        'validation automatique après paiement', default=False,
    )

    class Meta:
        verbose_name = 'paramètres publicité'
        verbose_name_plural = 'paramètres publicité'

    @classmethod
    def obtenir(cls):
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj

    def __str__(self):
        return 'Paramètres publicité'
