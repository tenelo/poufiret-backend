"""
Modèles de l'app users.

Définit User, ProfilCommercant, PlanAbonnement, HoraireOuverture, AdresseClient.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """
    Utilisateur de la plateforme Poufiret.

    Étend l'AbstractUser de Django :
    - L'identifiant principal devient le numéro de téléphone
    - Ajoute le rôle, le statut de vérification et le token FCM
    """

    class Role(models.TextChoices):
        CLIENT = 'client', _('Client')
        COMMERCANT = 'commercant', _('Commerçant')
        LIVREUR = 'livreur', _('Livreur')
        ADMIN = 'admin', _('Administrateur')

    # Téléphone obligatoire et unique : c'est l'identifiant principal
    telephone = models.CharField(
        _('téléphone'),
        max_length=20,
        unique=True,
        help_text=_('Numéro de téléphone au format international (+225...)'),
    )

    # Le rôle détermine ce que l'utilisateur peut faire
    role = models.CharField(
        _('rôle'),
        max_length=20,
        choices=Role.choices,
        default=Role.CLIENT,
    )

    # Pour le MVP, la vérification se fait par SMS (étape future)
    est_verifie = models.BooleanField(
        _('téléphone vérifié'),
        default=False,
        help_text=_('Le téléphone a été vérifié via un code OTP par SMS.'),
    )

    # Pour les notifications push (Firebase Cloud Messaging)
    token_fcm = models.CharField(
        _('token FCM'),
        max_length=255,
        blank=True,
        null=True,
        help_text=_('Token Firebase Cloud Messaging pour les notifications push.'),
    )

    langue_preferee = models.CharField(
        _('langue préférée'),
        max_length=10,
        default='fr',
    )

    # On utilise le téléphone pour la connexion, plus le username
    USERNAME_FIELD = 'telephone'
    # Champs requis lors de createsuperuser (en plus de USERNAME_FIELD et password)
    REQUIRED_FIELDS = ['username']

    class Meta:
        verbose_name = _('utilisateur')
        verbose_name_plural = _('utilisateurs')
        ordering = ['-date_joined']

    def __str__(self):
        nom_complet = self.get_full_name()
        return f"{nom_complet} ({self.telephone})" if nom_complet else self.telephone



class PlanAbonnement(models.Model):
    """
    Paliers d'abonnement pour les commerçants.

    Chaque plan a un prix et une durée en jours. On peut donc avoir
    plusieurs variantes d'un même palier (ex: Premium 24h, Premium 30j, Premium 1 an).
    L'inscription par défaut se fait au plan Basique gratuit (durée illimitée).
    """

    class Code(models.TextChoices):
        BASIQUE = 'basique', _('Basique')
        STANDARD = 'standard', _('Standard')
        PREMIUM = 'premium', _('Premium')
        VIP = 'vip', _('VIP')

    code = models.CharField(
        _('code interne'),
        max_length=20,
        choices=Code.choices,
        help_text=_('Identifiant technique du palier (basique, standard, premium, vip).'),
    )
    libelle = models.CharField(
        _('libellé'),
        max_length=50,
        help_text=_('Nom affiché dans l\'app (ex: "Premium 30 jours").'),
    )
    description = models.TextField(
        _('description'),
        blank=True,
        help_text=_('Détails du plan, avantages, à destination des commerçants.'),
    )

    # ── Tarif et durée ────────────────────────────────────────────
    prix = models.DecimalField(
        _('prix (FCFA)'),
        max_digits=10,
        decimal_places=0,
        default=0,
    )
    duree_jours = models.IntegerField(
        _('durée (en jours)'),
        default=30,
        help_text=_('Durée de validité. 1 = 24h, 7 = 1 semaine, 30 = 1 mois, 365 = 1 an. -1 pour illimité.'),
    )

    # ── Limites ───────────────────────────────────────────────────
    nb_articles_max = models.IntegerField(
        _('nombre max d\'articles'),
        default=10,
        help_text=_('-1 pour illimité.'),
    )
    nb_photos_par_article = models.IntegerField(
        _('photos par article'),
        default=1,
    )

    # ── Avantages ─────────────────────────────────────────────────
    peut_publier_video = models.BooleanField(
        _('peut publier des vidéos'),
        default=False,
    )
    peut_etre_mis_en_avant = models.BooleanField(
        _('éligible mise en avant'),
        default=False,
        help_text=_('Le commerçant peut apparaître dans les carrousels d\'accueil.'),
    )
    boost_visibilite = models.IntegerField(
        _('boost de visibilité'),
        default=0,
        help_text=_('Multiplicateur appliqué au tri (0 = aucun, plus = remonte).'),
    )

    # ── Affichage ─────────────────────────────────────────────────
    ordre = models.IntegerField(
        _('ordre d\'affichage'),
        default=0,
    )
    est_actif = models.BooleanField(
        _('plan actif'),
        default=True,
        help_text=_('Décocher pour retirer le plan de la liste des choix possibles.'),
    )

    class Meta:
        verbose_name = _('plan d\'abonnement')
        verbose_name_plural = _('plans d\'abonnement')
        ordering = ['ordre', 'prix']
        # Unique sur la combinaison code + durée : on peut avoir
        # plusieurs Premium (24h, 30j, 1 an) mais pas deux Premium 30j.
        constraints = [
            models.UniqueConstraint(
                fields=['code', 'duree_jours'],
                name='unique_plan_code_duree',
            ),
        ]

    def __str__(self):
        duree = "illimité" if self.duree_jours == -1 else f"{self.duree_jours}j"
        return f"{self.libelle} — {self.prix:.0f} FCFA / {duree}"