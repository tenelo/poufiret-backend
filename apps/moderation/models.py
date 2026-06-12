"""
Modèles de l'app moderation.

Module 7 — final — du modèle Poufiret :
- 4 tables de signalement (une par type d'objet — évite le polymorphisme)
- 1 table de notifications in-app persistantes (en complément des push FCM)
"""
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import Article
from apps.messaging.models import Message
from apps.social.models import CommentaireArticle, CommentairePartenaire
from apps.users.models import ProfilPartenaire, User


# ═══════════════════════════════════════════════════════════════════════
# CLASSES ABSTRAITES PARTAGÉES
# ═══════════════════════════════════════════════════════════════════════

class SignalementBase(models.Model):
    """
    Champs communs à tous les types de signalement.
    Classe abstraite — pas de table créée pour celle-ci.
    """

    class Motif(models.TextChoices):
        SPAM = 'spam', _('Spam ou publicité abusive')
        ARNAQUE = 'arnaque', _('Arnaque, tentative d\'escroquerie')
        CONTENU_INAPPROPRIE = 'contenu_inapproprie', _('Contenu inapproprié')
        FAUSSES_INFOS = 'fausses_infos', _('Fausses informations')
        HARCELEMENT = 'harcelement', _('Harcèlement, insultes')
        AUTRE = 'autre', _('Autre')

    class Statut(models.TextChoices):
        NOUVEAU = 'nouveau', _('Nouveau')
        EN_EXAMEN = 'en_examen', _('En cours d\'examen')
        TRAITE = 'traite', _('Traité')
        REJETE = 'rejete', _('Rejeté (non fondé)')

    motif = models.CharField(
        _('motif'),
        max_length=30, choices=Motif.choices, default=Motif.AUTRE,
    )
    description = models.TextField(
        _('description'),
        blank=True,
        help_text=_('Détails complémentaires fournis par le rapporteur.'),
    )
    statut = models.CharField(
        _('statut'),
        max_length=20, choices=Statut.choices, default=Statut.NOUVEAU,
    )
    action_prise = models.TextField(
        _('action prise'),
        blank=True,
        help_text=_('Notes de l\'admin sur l\'action effectuée.'),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    traite_le = models.DateTimeField(_('traité le'), blank=True, null=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']


# ═══════════════════════════════════════════════════════════════════════
# SIGNALEMENTS — un modèle par type d'objet signalable
# ═══════════════════════════════════════════════════════════════════════

class SignalementArticle(SignalementBase):
    """Signalement portant sur un article."""

    rapporteur = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='signalements_articles',
        verbose_name=_('rapporteur'),
    )
    article = models.ForeignKey(
        Article, on_delete=models.CASCADE,
        related_name='signalements',
        verbose_name=_('article signalé'),
    )
    traite_par = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='signalements_articles_traites',
        verbose_name=_('traité par'),
    )

    class Meta(SignalementBase.Meta):
        verbose_name = _('signalement — article')
        verbose_name_plural = _('signalements — articles')

    def __str__(self):
        return f"#{self.id} {self.get_motif_display()} → {self.article.nom}"


class SignalementPartenaire(SignalementBase):
    """Signalement portant sur un commerçant entier."""

    rapporteur = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='signalements_partenaires',
        verbose_name=_('rapporteur'),
    )
    partenaire = models.ForeignKey(
        ProfilPartenaire, on_delete=models.CASCADE,
        related_name='signalements',
        verbose_name=_('commerçant signalé'),
    )
    traite_par = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='signalements_partenaires_traites',
        verbose_name=_('traité par'),
    )

    class Meta(SignalementBase.Meta):
        verbose_name = _('signalement — commerçant')
        verbose_name_plural = _('signalements — commerçants')

    def __str__(self):
        return f"#{self.id} {self.get_motif_display()} → {self.partenaire.nom_commerce}"


class SignalementCommentaire(SignalementBase):
    """
    Signalement portant sur un commentaire (article OU commerçant).
    Exactement un des deux champs commentaire_* doit être renseigné.
    """
    rapporteur = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='signalements_commentaires',
        verbose_name=_('rapporteur'),
    )
    commentaire_article = models.ForeignKey(
        CommentaireArticle, on_delete=models.CASCADE,
        blank=True, null=True,
        related_name='signalements',
        verbose_name=_('commentaire (article)'),
    )
    commentaire_partenaire = models.ForeignKey(
        CommentairePartenaire, on_delete=models.CASCADE,
        blank=True, null=True,
        related_name='signalements',
        verbose_name=_('commentaire (commerçant)'),
    )
    traite_par = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='signalements_commentaires_traites',
        verbose_name=_('traité par'),
    )

    class Meta(SignalementBase.Meta):
        verbose_name = _('signalement — commentaire')
        verbose_name_plural = _('signalements — commentaires')
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(commentaire_article__isnull=False, commentaire_partenaire__isnull=True)
                    | models.Q(commentaire_article__isnull=True, commentaire_partenaire__isnull=False)
                ),
                name='signalement_commentaire_exclusif',
            ),
        ]

    def __str__(self):
        cible_id = (self.commentaire_article or self.commentaire_partenaire).id
        return f"#{self.id} {self.get_motif_display()} → commentaire #{cible_id}"


class SignalementMessage(SignalementBase):
    """Signalement portant sur un message de chat."""

    rapporteur = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='signalements_messages',
        verbose_name=_('rapporteur'),
    )
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE,
        related_name='signalements',
        verbose_name=_('message signalé'),
    )
    traite_par = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='signalements_messages_traites',
        verbose_name=_('traité par'),
    )

    class Meta(SignalementBase.Meta):
        verbose_name = _('signalement — message')
        verbose_name_plural = _('signalements — messages')

    def __str__(self):
        return f"#{self.id} {self.get_motif_display()} → message #{self.message_id}"


# ═══════════════════════════════════════════════════════════════════════
# NOTIFICATIONS IN-APP
# ═══════════════════════════════════════════════════════════════════════

class Notification(models.Model):
    """
    Notification in-app persistante pour un utilisateur.
    En complément des push FCM (qui, eux, sont envoyés mais pas stockés).
    """

    class Type(models.TextChoices):
        COMMANDE_NOUVELLE = 'commande_nouvelle', _('Nouvelle commande')
        COMMANDE_ACCEPTEE = 'commande_acceptee', _('Commande acceptée')
        COMMANDE_REFUSEE = 'commande_refusee', _('Commande refusée')
        COMMANDE_PRETE = 'commande_prete', _('Commande prête')
        COMMANDE_LIVREE = 'commande_livree', _('Commande livrée')
        NOUVEAU_MESSAGE = 'nouveau_message', _('Nouveau message')
        DEMANDE_INTERVENTION = 'demande_intervention', _('Demande d\'intervention')
        INTERVENTION_ACCEPTEE = 'intervention_acceptee', _('Intervention acceptée')
        NOUVEAU_COMMENTAIRE = 'nouveau_commentaire', _('Nouveau commentaire')
        NOUVEAU_LIKE = 'nouveau_like', _('Nouveau like')
        FAVEUR_ACCORDEE = 'faveur_accordee', _('Faveur accordée')
        ABONNEMENT_EXPIRE = 'abonnement_expire', _('Abonnement expirant')
        SIGNALEMENT_TRAITE = 'signalement_traite', _('Signalement traité')
        SYSTEME = 'systeme', _('Message système')

    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name=_('destinataire'),
    )
    type = models.CharField(
        _('type'),
        max_length=40, choices=Type.choices,
    )
    titre = models.CharField(_('titre'), max_length=200)
    contenu = models.TextField(_('contenu'))

    data = models.JSONField(
        _('données contextuelles'),
        default=dict, blank=True,
        help_text=_('Données pour le deep-linking (ex: {"article_id": 42, "commande_id": 7}).'),
    )

    lu = models.BooleanField(_('lue'), default=False)
    lu_le = models.DateTimeField(_('lue le'), blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('notification')
        verbose_name_plural = _('notifications')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'lu', '-created_at']),
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        statut = '✓' if self.lu else '●'
        return f"{statut} {self.user.telephone} — {self.titre}"