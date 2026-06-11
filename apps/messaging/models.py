"""
Modèles de l'app messaging.

Fusionne les Modules 5 (Interventions) et 6 (Communication) :
- Conversation + Message  → chat client ↔ commerçant en temps réel
- DemandeIntervention      → formulaire structuré pour plombier, électricien,
                             maçon, menuisier sur mesure. Chaque demande crée
                             automatiquement une Conversation pour la négociation.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import Article
from apps.users.models import AdresseClient, ProfilCommercant, User


# ═══════════════════════════════════════════════════════════════════════
# CONVERSATION & MESSAGE (chat en temps réel)
# ═══════════════════════════════════════════════════════════════════════

class Conversation(models.Model):
    """
    Conversation entre un client et un commerçant.
    Peut être liée à un article précis (contexte de la discussion :
    "le client te contacte au sujet de tel modèle de boubou").
    """
    client = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='conversations_client',
        verbose_name=_('client'),
    )
    commercant = models.ForeignKey(
        ProfilCommercant, on_delete=models.CASCADE,
        related_name='conversations',
        verbose_name=_('commerçant'),
    )
    article = models.ForeignKey(
        Article, on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='conversations',
        verbose_name=_('article'),
        help_text=_('Contexte facultatif : article concerné par la discussion.'),
    )

    derniere_activite = models.DateTimeField(_('dernière activité'), auto_now=True)
    est_archivee = models.BooleanField(_('archivée'), default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('conversation')
        verbose_name_plural = _('conversations')
        ordering = ['-derniere_activite']
        indexes = [
            models.Index(fields=['client', '-derniere_activite']),
            models.Index(fields=['commercant', '-derniere_activite']),
        ]

    def __str__(self):
        contexte = f" à propos de {self.article.nom}" if self.article else ''
        return f"{self.client.telephone} ↔ {self.commercant.nom_commerce}{contexte}"


class Message(models.Model):
    """Message dans une conversation."""

    class Type(models.TextChoices):
        TEXTE = 'texte', _('Texte')
        IMAGE = 'image', _('Image')
        AUDIO = 'audio', _('Audio')
        SYSTEME = 'systeme', _('Message système')

    class Statut(models.TextChoices):
        ENVOYE = 'envoye', _('Envoyé')
        LIVRE = 'livre', _('Livré')
        LU = 'lu', _('Lu')

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE,
        related_name='messages', verbose_name=_('conversation'),
    )
    expediteur = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='messages_envoyes',
        verbose_name=_('expéditeur'),
        help_text=_('Null pour les messages système.'),
    )

    type = models.CharField(
        _('type'),
        max_length=10, choices=Type.choices, default=Type.TEXTE,
    )
    contenu = models.TextField(_('contenu'), blank=True)
    media_url = models.CharField(
        _('URL du média'),
        max_length=500, blank=True,
        help_text=_('Pour les messages de type image ou audio.'),
    )

    statut = models.CharField(
        _('statut'),
        max_length=10, choices=Statut.choices, default=Statut.ENVOYE,
    )
    lu_le = models.DateTimeField(_('lu le'), blank=True, null=True)
    est_supprime = models.BooleanField(_('supprimé'), default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('message')
        verbose_name_plural = _('messages')
        ordering = ['conversation', 'created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
        ]

    def __str__(self):
        qui = self.expediteur.telephone if self.expediteur else 'SYSTÈME'
        preview = (self.contenu[:40] + '…') if len(self.contenu) > 40 else self.contenu
        return f"{qui} : {preview}"


# ═══════════════════════════════════════════════════════════════════════
# DEMANDE D'INTERVENTION (plombier, électricien, maçon, menuisier sur mesure)
# ═══════════════════════════════════════════════════════════════════════

class DemandeIntervention(models.Model):
    """
    Demande structurée d'intervention auprès d'un artisan.
    Crée automatiquement une Conversation pour la négociation.
    """

    class Type(models.TextChoices):
        REPARATION = 'reparation', _('Réparation')
        INSTALLATION = 'installation', _('Installation')
        DEPANNAGE = 'depannage_urgent', _('Dépannage urgent')
        DEVIS = 'devis', _('Demande de devis')
        AUTRE = 'autre', _('Autre')

    class Urgence(models.TextChoices):
        URGENT = 'urgent', _('Urgent (dans la journée)')
        SEMAINE = 'cette_semaine', _('Cette semaine')
        FLEXIBLE = 'flexible', _('Flexible')

    class Disponibilite(models.TextChoices):
        MATIN = 'matin', _('Matin')
        APREM = 'aprem', _('Après-midi')
        SOIR = 'soir', _('Soir')
        INDIFFERENT = 'indifferent', _('Indifférent')

    class Statut(models.TextChoices):
        EN_ATTENTE = 'en_attente', _('En attente')
        ACCEPTEE = 'acceptee', _('Acceptée')
        REFUSEE = 'refusee', _('Refusée')
        EN_COURS = 'en_cours', _('En cours')
        TERMINEE = 'terminee', _('Terminée')
        ANNULEE = 'annulee', _('Annulée')

    # ── Identité ─────────────────────────────────────────────────────
    numero = models.CharField(
        _('numéro'), max_length=30, unique=True,
        help_text=_('Ex: INT-2026-00042'),
    )
    user = models.ForeignKey(
        User, on_delete=models.PROTECT,
        related_name='demandes_intervention',
        verbose_name=_('client'),
    )
    artisan = models.ForeignKey(
        ProfilCommercant, on_delete=models.PROTECT,
        related_name='interventions_recues',
        verbose_name=_('artisan'),
    )

    # ── Détails de la demande ────────────────────────────────────────
    type_intervention = models.CharField(
        _('type d\'intervention'),
        max_length=30, choices=Type.choices, default=Type.REPARATION,
    )
    type_libre = models.CharField(
        _('précision (si type = autre)'),
        max_length=200, blank=True,
    )
    description = models.TextField(_('description du problème'))
    urgence = models.CharField(
        _('urgence'),
        max_length=20, choices=Urgence.choices, default=Urgence.FLEXIBLE,
    )

    # ── Lieu ─────────────────────────────────────────────────────────
    adresse = models.ForeignKey(
        AdresseClient,
        on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='demandes_intervention',
        verbose_name=_('adresse de l\'intervention'),
    )
    adresse_snapshot = models.CharField(
        _('adresse (snapshot)'),
        max_length=500, blank=True,
    )
    description_acces = models.TextField(_('comment trouver le lieu'), blank=True)

    # ── Disponibilité ────────────────────────────────────────────────
    disponibilite_preferee = models.CharField(
        _('disponibilité préférée'),
        max_length=20, choices=Disponibilite.choices, default=Disponibilite.INDIFFERENT,
    )

    # ── Workflow ─────────────────────────────────────────────────────
    statut = models.CharField(
        _('statut'),
        max_length=20, choices=Statut.choices, default=Statut.EN_ATTENTE,
    )
    date_proposee = models.DateTimeField(
        _('date proposée par l\'artisan'),
        blank=True, null=True,
    )
    prix_propose = models.DecimalField(
        _('prix proposé (FCFA)'),
        max_digits=12, decimal_places=0,
        blank=True, null=True,
    )
    raison_refus = models.TextField(_('raison du refus'), blank=True)

    # ── Lien chat ────────────────────────────────────────────────────
    conversation = models.OneToOneField(
        Conversation,
        on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='demande_intervention',
        verbose_name=_('conversation associée'),
        help_text=_('Conversation créée automatiquement pour la négociation.'),
    )

    # ── Dates clés ───────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)
    acceptee_le = models.DateTimeField(_('acceptée le'), blank=True, null=True)
    terminee_le = models.DateTimeField(_('terminée le'), blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('demande d\'intervention')
        verbose_name_plural = _('demandes d\'intervention')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['artisan', 'statut', '-created_at']),
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"{self.numero} — {self.get_type_intervention_display()} chez {self.artisan.nom_commerce}"


class DemandeInterventionPhoto(models.Model):
    """Photo illustrant une demande d'intervention (problème à montrer, lieu, etc.)."""

    demande = models.ForeignKey(
        DemandeIntervention,
        on_delete=models.CASCADE,
        related_name='photos',
        verbose_name=_('demande d\'intervention'),
    )
    image = models.ImageField(_('photo'), upload_to='interventions/')
    legende = models.CharField(_('légende'), max_length=200, blank=True)
    ordre = models.IntegerField(_('ordre'), default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('photo de demande d\'intervention')
        verbose_name_plural = _('photos de demandes d\'intervention')
        ordering = ['demande', 'ordre']

    def __str__(self):
        return f"Photo #{self.ordre} de {self.demande.numero}"