"""
Modèles de l'app users.

Définit User, ProfilPartenaire, PlanAbonnement, HoraireOuverture, AdresseClient.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.gis.db import models as gis_models
from apps.core.models import ModeleBase
from apps.core.images import ImagesOptimiseesMixin


class TrancheAge(models.TextChoices):
    MOINS_18 = 'moins_18', 'Moins de 18 ans'
    DE_18_24 = '18_24', '18 - 24 ans'
    DE_25_34 = '25_34', '25 - 34 ans'
    DE_35_44 = '35_44', '35 - 44 ans'
    DE_45_54 = '45_54', '45 - 54 ans'
    PLUS_55 = '55_plus', '55 ans et plus'


class Sexe(models.TextChoices):
    HOMME = 'homme', 'Homme'
    FEMME = 'femme', 'Femme'
    NON_PRECISE = 'non_precise', 'Préfère ne pas préciser'


class User(AbstractUser):
    """
    Utilisateur de la plateforme Poufiret.

    Étend l'AbstractUser de Django :
    - L'identifiant principal devient le numéro de téléphone
    - Ajoute le rôle, le statut de vérification et le token FCM
    """

    class Role(models.TextChoices):
        CLIENT = 'client', _('Client')
        PARTENAIRE = 'partenaire', _('Partenaire')
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
    # Donnees pour le referencement et l'analyse (facultatives),
    # demandees dans un bloc separe a l'inscription.
    departement = models.ForeignKey(
        'geo.Departement', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='utilisateurs',
        verbose_name='departement',
    )
    tranche_age = models.CharField(
        'tranche age', max_length=10,
        choices=TrancheAge.choices, blank=True,
    )
    sexe = models.CharField(
        'sexe', max_length=12,
        choices=Sexe.choices, blank=True,
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



class Portee(models.TextChoices):
    """Etendue geographique de visibilite d'un partenaire.

    Ordonnee du plus restreint au plus large. Sert a la fois a la
    visibilite organique (liee au forfait) et, cote publicite, de socle
    minimum qu'une campagne peut etendre mais jamais reduire.
    """
    DEPARTEMENT = 'departement', 'Departement seulement'
    REGION = 'region', 'Toute la region'
    DISTRICT = 'district', 'Tout le district'

    @staticmethod
    def rang(valeur):
        """Rang numerique pour comparer deux portees (max = la plus large)."""
        ordre = {'departement': 0, 'region': 1, 'district': 2}
        return ordre.get(valeur, 0)


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
    nb_videos_par_article = models.IntegerField(
        _('vidéos par article'),
        default=0,
        help_text=_('0 = aucune vidéo autorisée pour ce plan.'),
    )
    peut_etre_mis_en_avant = models.BooleanField(
        _('éligible mise en avant'),
        default=False,
        help_text=_('Le commerçant peut apparaître dans les carrousels d\'accueil.'),
    )
    portee = models.CharField(
        _('portee geographique'),
        max_length=12,
        choices=Portee.choices,
        default=Portee.DEPARTEMENT,
        help_text=_('Jusqu\'ou les partenaires de ce plan sont visibles : '
                    'leur departement, leur region, ou tout le district.'),
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
    

class ProfilPartenaire(ImagesOptimiseesMixin, models.Model):
    """
    Profil étendu pour les utilisateurs ayant le rôle partenaire.

    Relation 1-1 avec User : un User avec role='partenaire' a UN profil
    partenaire. Ce modèle contient toutes les infos métier (nom, localisation,
    plan, statut admin) et les champs de contrôle qui permettent à l'admin
    de gérer la plateforme.
    """
    champs_images = ('logo', 'photo_couverture')

    class TypePartenaire(models.TextChoices):
        COMMERCANT = 'commercant', _('Commerçant')
        PHARMACIEN = 'pharmacien', _('Pharmacien')
        BOULANGER = 'boulanger', _('Boulanger')
        RESTAURATEUR = 'restaurateur', _('Restaurateur')
        COUTURIER = 'couturier', _('Couturier / Couturière')
        MENUISIER = 'menuisier', _('Menuisier')
        PLOMBIER = 'plombier', _('Plombier')
        ELECTRICIEN = 'electricien', _('Électricien')
        MACON = 'macon', _('Maçon')
        COIFFEUR = 'coiffeur', _('Coiffeur / Coiffeuse')
        LIBRAIRE = 'libraire', _('Libraire')
        HOTELIER = 'hotelier', _('Hôtelier')
        MECANICIEN = 'mecanicien', _('Mécanicien')
        LOUEUR_MAISON = 'loueur_maison', _('Loueur de maison')
        LOUEUR_VOITURE = 'loueur_voiture', _('Loueur de voiture')
        AUTRE = 'autre', _('Autre')

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
        related_name='profil_partenaire',
        verbose_name=_('compte utilisateur'),
    )

    # ── Type / appellation du partenaire ─────────────────────────────
    type_partenaire = models.CharField(
        _('type de partenaire'),
        max_length=20,
        choices=TypePartenaire.choices,
        default=TypePartenaire.COMMERCANT,
        help_text=_('Désigne l\'appellation du partenaire (commerçant, pharmacien, coiffeur, etc.).'),
    )

    # ── Identité du partenaire ───────────────────────────────────────
    nom_commerce = models.CharField(_('nom de l\'enseigne'), max_length=150)
    description = models.TextField(_('description'), blank=True)
    logo = models.ImageField(_('logo'), upload_to='partenaires/logos/', blank=True, null=True)
    photo_couverture = models.ImageField(
        _('photo de couverture'),
        upload_to='partenaires/couvertures/',
        blank=True, null=True,
    )

    # ── Localisation ─────────────────────────────────────────────────
    adresse = models.CharField(_('adresse'), max_length=255, blank=True)
    quartier = models.CharField(_('quartier'), max_length=100, blank=True)
    secteur = models.CharField(_('secteur'), max_length=100, blank=True)
    ville = models.CharField(_('ville'), max_length=100, default='Ferkessédougou')
    departement = models.ForeignKey(
        'geo.Departement', on_delete=models.PROTECT,
        null=True, blank=True, related_name='partenaires',
        verbose_name=_('département'),
        help_text=_('Département du commerce. Remplace progressivement le '
                    'champ texte « ville ».'),
    )
    description_acces = models.TextField(
        _('comment trouver le partenaire'),
        blank=True,
        help_text=_('Indications complémentaires pour les clients (ex: "à côté du marché central").'),
    )
    localisation = gis_models.PointField(
        _('position GPS'),
        geography=True,
        blank=True, null=True,
        help_text=_('Coordonnées GPS (optionnel, peut être ajouté plus tard).'),
    )

    # ── Contact professionnel ────────────────────────────────────────
    nb_vues = models.PositiveIntegerField(
        _('nombre de vues de la vitrine'), default=0,
    )
    telephone_pro = models.CharField(_('téléphone professionnel'), max_length=20, blank=True)
    whatsapp = models.CharField(_('numéro WhatsApp'), max_length=20, blank=True)
    email_pro = models.EmailField(_('email professionnel'), blank=True)

    # ── Plan & abonnement ────────────────────────────────────────────
    plan = models.ForeignKey(
        PlanAbonnement,
        on_delete=models.PROTECT,
        related_name='partenaires',
        verbose_name=_('plan d\'abonnement'),
    )
    abonnement_debut = models.DateField(_('début de l\'abonnement'), blank=True, null=True)
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
        help_text=_('Décocher pour masquer temporairement le partenaire sans le supprimer.'),
    )
    visibilite_jusquau = models.DateField(
        _('visibilité jusqu\'au'),
        blank=True, null=True,
        help_text=_('Si renseigné, le partenaire est auto-masqué après cette date.'),
    )

    paye_publicite = models.BooleanField(_('a payé la publicité'), default=False)
    pub_active_jusquau = models.DateField(_('publicité active jusqu\'au'), blank=True, null=True)

    score_priorite = models.IntegerField(
        _('score de priorité'),
        default=0,
        help_text=_('Boost manuel : plus c\'est haut, plus le partenaire remonte dans les listes.'),
    )

    badge_certifie = models.BooleanField(_('badge certifié'), default=False)
    taxes_communales_ok = models.BooleanField(_('taxes communales à jour'), default=False)
    date_verif_taxes = models.DateField(_('date de vérification des taxes'), blank=True, null=True)

    # Système de faveurs (visibilité offerte)
    est_faveur = models.BooleanField(
        _('en faveur'),
        default=False,
        help_text=_('Le partenaire bénéficie d\'avantages offerts sans paiement.'),
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

    notes_admin = models.TextField(
        _('notes internes admin'),
        blank=True,
        help_text=_('Commentaires non visibles par le partenaire.'),
    )
    derniere_verif = models.DateField(_('dernière vérification'), blank=True, null=True)

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
        verbose_name = _('profil partenaire')
        verbose_name_plural = _('profils partenaires')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['statut']),
            models.Index(fields=['ville']),
            models.Index(fields=['type_partenaire']),
        ]

    def __str__(self):
        return f"{self.nom_commerce} — {self.user.telephone}"

    @property
    def portee(self):
        """Portee organique effective du partenaire.

        Vient du plan. Un partenaire en faveur peut se voir accorder une
        portee superieure en changeant simplement son plan cote admin, la
        logique reste donc centralisee ici.
        """
        return self.plan.portee if self.plan_id else 'departement'

class HoraireOuverture(models.Model):
    """
    Horaires d'ouverture hebdomadaires d'un commerçant.

    Un commerçant a généralement 7 horaires (un par jour de la semaine).
    Permet de répondre à des requêtes type "qui est ouvert maintenant ?".
    """

    class Jour(models.IntegerChoices):
        LUNDI = 0, _('Lundi')
        MARDI = 1, _('Mardi')
        MERCREDI = 2, _('Mercredi')
        JEUDI = 3, _('Jeudi')
        VENDREDI = 4, _('Vendredi')
        SAMEDI = 5, _('Samedi')
        DIMANCHE = 6, _('Dimanche')

    partenaire = models.ForeignKey(
        ProfilPartenaire,
        on_delete=models.CASCADE,
        related_name='horaires',
        verbose_name=_('partenaire'),
    )
    jour_semaine = models.IntegerField(_('jour'), choices=Jour.choices)
    ouvert = models.BooleanField(_('ouvert ce jour'), default=True)

    heure_ouverture = models.TimeField(_('heure d\'ouverture'), blank=True, null=True)
    heure_fermeture = models.TimeField(_('heure de fermeture'), blank=True, null=True)

    # Pause méridienne (facultatif)
    pause_debut = models.TimeField(_('début de pause'), blank=True, null=True)
    pause_fin = models.TimeField(_('fin de pause'), blank=True, null=True)

    note = models.CharField(
        _('note'),
        max_length=200,
        blank=True,
        help_text=_('Ex: "Horaires Ramadan", "Fermé en cas de pluie"…'),
    )

    class Meta:
        verbose_name = _('horaire d\'ouverture')
        verbose_name_plural = _('horaires d\'ouverture')
        ordering = ['partenaire', 'jour_semaine']
        # Un seul horaire par couple (partenaire, jour)
        constraints = [
            models.UniqueConstraint(
                fields=['partenaire', 'jour_semaine'],
                name='unique_horaire_par_jour',
            ),
        ]

    def __str__(self):
        return f"{self.partenaire.nom_commerce} — {self.get_jour_semaine_display()}"


class AdresseClient(models.Model):
    """
    Adresses sauvegardées d'un client (pour commandes & livraisons).

    Un client peut avoir plusieurs adresses (maison, bureau, chez maman…).
    Évite de devoir retaper l'adresse à chaque commande.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='adresses',
        verbose_name=_('utilisateur'),
    )
    libelle = models.CharField(
        _('libellé'),
        max_length=50,
        help_text=_('Ex: "Maison", "Bureau", "Chez maman"…'),
    )
    adresse = models.CharField(_('adresse'), max_length=255)
    description_acces = models.TextField(
        _('comment trouver l\'adresse'),
        blank=True,
        help_text=_('Ex: "Porte verte, 1er étage, à droite de la pharmacie".'),
    )

    # GPS optionnel — comme pour les commerçants
    localisation = gis_models.PointField(
        _('position GPS'),
        geography=True,
        blank=True, null=True,
    )

    est_principale = models.BooleanField(
        _('adresse principale'),
        default=False,
        help_text=_('L\'adresse principale est sélectionnée par défaut au moment de commander.'),
    )
    est_active = models.BooleanField(_('adresse active'), default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('adresse client')
        verbose_name_plural = _('adresses clients')
        ordering = ['user', '-est_principale', '-updated_at']

    def __str__(self):
        return f"{self.libelle} — {self.user.telephone}"

class SessionAppareil(ModeleBase):
    """
    Trace des connexions par appareil (audit + déconnexion ciblée).

    Une ligne par appareil connecté. Permet de savoir qui s'est connecté,
    depuis quel appareil et quand, et de révoquer un appareil précis sans
    déconnecter les autres. Alimente aussi la future définition d'utilisateur
    actif (via derniere_activite_le).
    """

    class Plateforme(models.TextChoices):
        ANDROID = 'android', _('Android')
        IOS = 'ios', _('iOS')
        WEB = 'web', _('Web')
        AUTRE = 'autre', _('Autre')

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='sessions_appareils',
        verbose_name=_('utilisateur'),
    )
    appareil_nom = models.CharField(_('nom de l\'appareil'), max_length=150, blank=True)
    appareil_id = models.CharField(
        _('identifiant appareil'),
        max_length=255, blank=True,
        help_text=_('Identifiant unique fourni par le client (device id).'),
    )
    plateforme = models.CharField(
        _('plateforme'),
        max_length=10,
        choices=Plateforme.choices,
        default=Plateforme.AUTRE,
    )
    adresse_ip = models.GenericIPAddressField(_('adresse IP'), blank=True, null=True)

    derniere_activite_le = models.DateTimeField(_('dernière activité'), auto_now=True)
    est_active = models.BooleanField(_('session active'), default=True)
    revoque_le = models.DateTimeField(_('révoquée le'), blank=True, null=True)
    revoque_par = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='sessions_revoquees',
        verbose_name=_('révoquée par'),
    )

    class Meta:
        verbose_name = _('session appareil')
        verbose_name_plural = _('sessions appareils')
        ordering = ['-derniere_activite_le']
        indexes = [
            models.Index(fields=['user', 'est_active']),
        ]

    def __str__(self):
        return f"{self.user.telephone} — {self.appareil_nom or self.plateforme}"
