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