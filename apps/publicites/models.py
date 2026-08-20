from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import ModeleBase
from apps.core.images import ImagesOptimiseesMixin
from apps.users.models import Portee


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
    passages_par_type = models.JSONField(
        'passages par jour et par emplacement', default=dict, blank=True,
        help_text=(
            'Facultatif. Ex. {"carrousel": 6, "interstitiel": 3, '
            '"bandeau_bas": 4}. Vide = le quota global "passages par jour" '
            "s'applique à tous les emplacements confondus, et le carrousel "
            "peut alors épuiser la place réservée à l'interstitiel."
        ),
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


class Publicite(ImagesOptimiseesMixin, ModeleBase):
    """Campagne publicitaire d'un partenaire."""
    champs_images = ('image_couverture',)

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
    portee = models.CharField(
        'portée achetée', max_length=15,
        choices=Portee.choices, default=Portee.DEPARTEMENT,
        help_text=(
            "Étendue géographique achetée pour cette campagne. "
            "La portée réellement appliquée est le maximum entre "
            "cette valeur et la portée du forfait du partenaire "
            "(une pub ne descend jamais sous le forfait)."
        ),
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
    # ── Faveur (campagne offerte, geste commercial EstAdmin) ─────────
    est_faveur = models.BooleanField(
        'campagne offerte', default=False,
        help_text='Campagne diffusée gratuitement, sans paiement.',
    )
    faveur_accordee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='publicites_offertes',
        verbose_name='faveur accordée par',
    )
    faveur_motif = models.TextField(
        'motif de la faveur', blank=True,
        help_text='Ex: "Partenariat", "Lancement", "Compensation".',
    )

    class Meta:
        verbose_name = 'publicité'
        verbose_name_plural = 'publicités'
        ordering = ['-cree_le']
        indexes = [
            # _pubs_diffusables() filtre sur ces deux champs a chaque
            # affichage : c'est la requete la plus frequente de l'app.
            models.Index(fields=['statut', 'debut_diffusion']),
        ]

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

    @property
    def portee_effective(self):
        """Portée réellement appliquée : MAX(forfait, achetée).

        Une campagne peut étendre la visibilité au-delà du forfait mais
        jamais la réduire. Ex. un partenaire au forfait 'département' qui
        achète 'district' touche tout le district ; l'inverse (forfait
        'région', pub 'département') reste à 'région'.
        """
        plan = getattr(self.partenaire, 'plan', None)
        portee_forfait = getattr(plan, 'portee', Portee.DEPARTEMENT)
        if Portee.rang(self.portee) >= Portee.rang(portee_forfait):
            return self.portee
        return portee_forfait

    def __str__(self):
        return f'{self.titre} ({self.partenaire}) — {self.get_statut_display()}'


class ImagePublicite(ImagesOptimiseesMixin, ModeleBase):
    champs_images = ('image',)
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
    session = models.ForeignKey(
        'analytics.TempsSessionUtilisateur', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='impressions_publicites',
        verbose_name='session',
        help_text=(
            "Permet de ne compter qu'une impression par session et par "
            "emplacement : sans cela, un simple retour sur l'accueil "
            "regonfle artificiellement les compteurs."
        ),
    )
    cliquee = models.BooleanField('cliquée', default=False)

    class Meta:
        verbose_name = 'impression de publicité'
        verbose_name_plural = 'impressions de publicité'
        indexes = [
            models.Index(fields=['publicite', 'utilisateur']),
            models.Index(fields=['session', 'publicite', 'type_affichage']),
            # _passages_restants() compte les impressions du jour.
            models.Index(fields=['utilisateur', 'cree_le']),
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
    interstitiel_minute_min = models.PositiveIntegerField(
        'interstitiel : minute nominale', default=10,
        help_text='Minute a laquelle servir la pub aux sessions longues',
    )
    interstitiel_minute_max = models.PositiveIntegerField(
        'interstitiel : borne haute du creneau', default=15,
        help_text='Au-dela de cette duree moyenne, on utilise la minute nominale',
    )
    interstitiel_ratio_session_courte = models.PositiveIntegerField(
        'interstitiel : % de la session courte', default=70,
        help_text='Session courte : pub servie a ce pourcentage de la duree habituelle',
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


class CreditFormulePub(ModeleBase):
    """Crédit de formule publicitaire offert par un admin, en attente d'usage.

    Un admin peut offrir un crédit (formule) à un partenaire sans créer
    tout de suite la campagne : le partenaire (ou l'admin) le consomme
    ensuite pour créer une publicité, à usage unique.
    """

    class Statut(models.TextChoices):
        DISPONIBLE = 'disponible', 'Disponible'
        CONSOMME = 'consomme', 'Consommé'

    partenaire = models.ForeignKey(
        'users.ProfilPartenaire', on_delete=models.CASCADE,
        related_name='credits_pub', verbose_name='partenaire',
    )
    formule = models.ForeignKey(
        'publicites.FormulePublicite', on_delete=models.PROTECT,
        related_name='credits', verbose_name='formule',
    )
    statut = models.CharField(
        'statut', max_length=20,
        choices=Statut.choices, default=Statut.DISPONIBLE,
    )
    publicite_consommatrice = models.ForeignKey(
        'publicites.Publicite', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='credits_utilises',
        verbose_name='publicité consommatrice',
    )
    accorde_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name='credits_pub_accordes', verbose_name='accordé par',
    )
    motif = models.TextField('motif', blank=True)
    consomme_le = models.DateTimeField('consommé le', null=True, blank=True)

    class Meta:
        ordering = ['-cree_le']
        verbose_name = 'crédit de formule publicitaire'
        verbose_name_plural = 'crédits de formule publicitaire'

    def __str__(self):
        return f'{self.formule.nom} → {self.partenaire.nom_commerce} ({self.statut})'
