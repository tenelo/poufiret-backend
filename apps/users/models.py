"""
Modèles de l'app users.

Définit User, ProfilCommercant, PlanAbonnement, HoraireOuverture, AdresseClient.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.gis.db import models as gis_models


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
    


class ProfilCommercant(models.Model):
    """
    Profil étendu pour les utilisateurs ayant le rôle commerçant.

    Relation 1-1 avec User : un User avec role='commercant' a UN profil
    commerçant. Ce modèle contient toutes les infos métier (nom du commerce,
    localisation, plan, statut admin) et les champs de contrôle qui
    permettent à l'admin de gérer la plateforme.
    """

    class Statut(models.TextChoices):
        EN_ATTENTE = 'en_attente', _('En attente de validation')
        ACTIF = 'actif', _('Actif')
        SUSPENDU = 'suspendu', _('Suspendu')
        BANNI = 'banni', _('Banni')

    class SourceInscription(models.TextChoices):
        SELF = 'self', _('Auto-inscription via l\'app')
        KOBO = 'kobo', _('Import Kobo Toolbox')
        ADMIN = 'admin', _('Créé par un admin')

    # ── Lien vers le User (1-1) ──────────────────────────────────────
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profil_commercant',
        verbose_name=_('compte utilisateur'),
    )

    # ── Identité du commerce ─────────────────────────────────────────
    nom_commerce = models.CharField(_('nom du commerce'), max_length=150)
    description = models.TextField(_('description'), blank=True)
    logo = models.ImageField(_('logo'), upload_to='commercants/logos/', blank=True, null=True)
    photo_couverture = models.ImageField(
        _('photo de couverture'),
        upload_to='commercants/couvertures/',
        blank=True, null=True,
    )

    # ── Localisation ─────────────────────────────────────────────────
    adresse = models.CharField(_('adresse'), max_length=255, blank=True)
    quartier = models.CharField(_('quartier'), max_length=100, blank=True)
    secteur = models.CharField(_('secteur'), max_length=100, blank=True)
    ville = models.CharField(_('ville'), max_length=100, default='Ferkessédougou')
    description_acces = models.TextField(
        _('comment trouver le commerce'),
        blank=True,
        help_text=_('Indications complémentaires pour les clients (ex: "à côté du marché central").'),
    )
    # GPS optionnel — peut être ajouté plus tard
    localisation = gis_models.PointField(
        _('position GPS'),
        geography=True,
        blank=True, null=True,
        help_text=_('Coordonnées GPS du commerce (optionnel, peut être ajouté plus tard).'),
    )

    # ── Contact professionnel ────────────────────────────────────────
    telephone_pro = models.CharField(_('téléphone professionnel'), max_length=20, blank=True)
    whatsapp = models.CharField(_('numéro WhatsApp'), max_length=20, blank=True)
    email_pro = models.EmailField(_('email professionnel'), blank=True)

    # ── Plan & abonnement ────────────────────────────────────────────
    plan = models.ForeignKey(
        PlanAbonnement,
        on_delete=models.PROTECT,
        related_name='commercants',
        verbose_name=_('plan d\'abonnement'),
    )
    abonnement_debut = models.DateField(
        _('début de l\'abonnement'),
        blank=True, null=True,
    )
    abonnement_fin = models.DateField(
        _('fin de l\'abonnement'),
        blank=True, null=True,
        help_text=_('Date au-delà de laquelle le plan repasse en Basique.'),
    )

    # ── Champs de contrôle admin ─────────────────────────────────────
    statut = models.CharField(
        _('statut'),
        max_length=20,
        choices=Statut.choices,
        default=Statut.EN_ATTENTE,
    )
    est_visible = models.BooleanField(
        _('visible dans l\'app'),
        default=True,
        help_text=_('Décocher pour masquer temporairement le commerce sans le supprimer.'),
    )
    visibilite_jusquau = models.DateField(
        _('visibilité jusqu\'au'),
        blank=True, null=True,
        help_text=_('Si renseigné, le commerce est auto-masqué après cette date.'),
    )

    # Publicité payante
    paye_publicite = models.BooleanField(_('a payé la publicité'), default=False)
    pub_active_jusquau = models.DateField(
        _('publicité active jusqu\'au'),
        blank=True, null=True,
    )

    # Boost de visibilité manuel par l'admin
    score_priorite = models.IntegerField(
        _('score de priorité'),
        default=0,
        help_text=_('Boost manuel : plus c\'est haut, plus le commerce remonte dans les listes.'),
    )

    # Badge de certification et taxes
    badge_certifie = models.BooleanField(_('badge certifié'), default=False)
    taxes_communales_ok = models.BooleanField(_('taxes communales à jour'), default=False)
    date_verif_taxes = models.DateField(_('date de vérification des taxes'), blank=True, null=True)

    # Système de faveurs (visibilité offerte)
    est_faveur = models.BooleanField(
        _('en faveur'),
        default=False,
        help_text=_('Le commerçant bénéficie d\'avantages offerts sans paiement.'),
    )
    faveur_accordee_par = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='faveurs_accordees',
        verbose_name=_('faveur accordée par'),
        help_text=_('Admin qui a accordé la faveur.'),
    )
    faveur_motif = models.TextField(
        _('motif de la faveur'),
        blank=True,
        help_text=_('Ex: "Partenariat", "Structure interne", "Bon client historique"…'),
    )

    # Notes internes à l'admin
    notes_admin = models.TextField(
        _('notes internes admin'),
        blank=True,
        help_text=_('Commentaires non visibles par le commerçant.'),
    )
    derniere_verif = models.DateField(
        _('dernière vérification'),
        blank=True, null=True,
    )

    # ── Traçabilité (recensement Kobo) ───────────────────────────────
    source_inscription = models.CharField(
        _('source d\'inscription'),
        max_length=20,
        choices=SourceInscription.choices,
        default=SourceInscription.SELF,
    )
    id_kobo = models.CharField(
        _('ID Kobo'),
        max_length=100,
        blank=True,
        help_text=_('Référence du formulaire Kobo Toolbox pour réconciliation.'),
    )

    # ── Timestamps ───────────────────────────────────────────────────
    created_at = models.DateTimeField(_('créé le'), auto_now_add=True)
    updated_at = models.DateTimeField(_('mis à jour le'), auto_now=True)

    class Meta:
        verbose_name = _('profil commerçant')
        verbose_name_plural = _('profils commerçants')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['statut']),
            models.Index(fields=['ville']),
        ]

    def __str__(self):
        return f"{self.nom_commerce} — {self.user.telephone}"