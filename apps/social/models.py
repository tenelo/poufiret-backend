"""
Modèles de l'app social.

Module 3 du modèle Poufiret. Gère les interactions sociales :
- Likes (❤️ rouge, publics)   : LikeArticle, LikePartenaire, LikeCommentaire
- Favoris (🤎 marron, privés) : FavoriArticle, FavoriPartenaire
- Commentaires                : CommentaireArticle, CommentairePartenaire
"""
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import Article
from apps.users.models import ProfilPartenaire, User


# ═══════════════════════════════════════════════════════════════════════
# LIKES ❤️ (publics, cœur rouge)
# ═══════════════════════════════════════════════════════════════════════

class LikeArticle(models.Model):
    """Like (❤️ rouge) public sur un article."""
    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='likes_articles', verbose_name=_('utilisateur'),
    )
    article = models.ForeignKey(
        Article, on_delete=models.CASCADE,
        related_name='likes', verbose_name=_('article'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('like d\'article')
        verbose_name_plural = _('likes d\'articles')
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'article'],
                name='unique_like_article',
            ),
        ]
        indexes = [
            models.Index(fields=['article', '-created_at']),
        ]

    def __str__(self):
        return f"{self.user.telephone} ❤️ {self.article.nom}"


class LikePartenaire(models.Model):
    """Like (❤️ rouge) public sur un commerçant."""
    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='likes_partenaires', verbose_name=_('utilisateur'),
    )
    partenaire = models.ForeignKey(
        ProfilPartenaire, on_delete=models.CASCADE,
        related_name='likes', verbose_name=_('commerçant'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('like de commerçant')
        verbose_name_plural = _('likes de commerçants')
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'partenaire'],
                name='unique_like_partenaire',
            ),
        ]
        indexes = [
            models.Index(fields=['partenaire', '-created_at']),
        ]

    def __str__(self):
        return f"{self.user.telephone} ❤️ {self.partenaire.nom_commerce}"


# ═══════════════════════════════════════════════════════════════════════
# FAVORIS 🤎 (privés, cœur marron)
# ═══════════════════════════════════════════════════════════════════════

class FavoriArticle(models.Model):
    """Article ajouté aux favoris privés d'un client (🤎 marron)."""
    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='favoris_articles', verbose_name=_('utilisateur'),
    )
    article = models.ForeignKey(
        Article, on_delete=models.CASCADE,
        related_name='favoris', verbose_name=_('article'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('favori - article')
        verbose_name_plural = _('favoris - articles')
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'article'],
                name='unique_favori_article',
            ),
        ]
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"{self.user.telephone} 🤎 {self.article.nom}"


class FavoriPartenaire(models.Model):
    """Commerçant ajouté aux favoris privés d'un client (🤎 marron)."""
    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='favoris_partenaires', verbose_name=_('utilisateur'),
    )
    partenaire = models.ForeignKey(
        ProfilPartenaire, on_delete=models.CASCADE,
        related_name='favoris', verbose_name=_('commerçant'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('favori - commerçant')
        verbose_name_plural = _('favoris - commerçants')
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'partenaire'],
                name='unique_favori_partenaire',
            ),
        ]
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"{self.user.telephone} 🤎 {self.partenaire.nom_commerce}"


# ═══════════════════════════════════════════════════════════════════════
# COMMENTAIRES 💬
# ═══════════════════════════════════════════════════════════════════════

class CommentaireArticle(models.Model):
    """
    Commentaire sur un article.
    Supporte 1 niveau de réponse (champ parent).
    """
    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='commentaires_articles', verbose_name=_('utilisateur'),
    )
    article = models.ForeignKey(
        Article, on_delete=models.CASCADE,
        related_name='commentaires', verbose_name=_('article'),
    )
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE,
        blank=True, null=True,
        related_name='reponses', verbose_name=_('réponse à'),
        help_text=_('Si renseigné, ce commentaire est une réponse.'),
    )

    contenu = models.TextField(_('contenu'))
    est_visible = models.BooleanField(
        _('visible'),
        default=True,
        help_text=_('Décocher pour masquer le commentaire (modération).'),
    )
    est_modifie = models.BooleanField(_('modifié'), default=False)
    nb_likes = models.IntegerField(_('nombre de likes'), default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('commentaire - article')
        verbose_name_plural = _('commentaires - articles')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['article', '-created_at']),
        ]

    def __str__(self):
        preview = self.contenu[:40] + ('…' if len(self.contenu) > 40 else '')
        return f"{self.user.telephone} : {preview}"


class CommentairePartenaire(models.Model):
    """
    Commentaire sur un commerçant (sur sa fiche, pas un article particulier).
    Supporte 1 niveau de réponse.
    """
    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='commentaires_partenaires', verbose_name=_('utilisateur'),
    )
    partenaire = models.ForeignKey(
        ProfilPartenaire, on_delete=models.CASCADE,
        related_name='commentaires', verbose_name=_('commerçant'),
    )
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE,
        blank=True, null=True,
        related_name='reponses', verbose_name=_('réponse à'),
    )

    contenu = models.TextField(_('contenu'))
    est_visible = models.BooleanField(_('visible'), default=True)
    est_modifie = models.BooleanField(_('modifié'), default=False)
    nb_likes = models.IntegerField(_('nombre de likes'), default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('commentaire - commerçant')
        verbose_name_plural = _('commentaires - commerçants')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['partenaire', '-created_at']),
        ]

    def __str__(self):
        preview = self.contenu[:40] + ('…' if len(self.contenu) > 40 else '')
        return f"{self.user.telephone} : {preview}"


# ═══════════════════════════════════════════════════════════════════════
# LIKES SUR COMMENTAIRES ❤️
# ═══════════════════════════════════════════════════════════════════════

class LikeCommentaire(models.Model):
    """
    Like sur un commentaire (article OU commerçant).
    Exactement un des deux champs commentaire_* doit être non NULL.
    """
    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='likes_commentaires', verbose_name=_('utilisateur'),
    )
    commentaire_article = models.ForeignKey(
        CommentaireArticle,
        on_delete=models.CASCADE,
        blank=True, null=True,
        related_name='likes',
        verbose_name=_('commentaire (article)'),
    )
    commentaire_partenaire = models.ForeignKey(
        CommentairePartenaire,
        on_delete=models.CASCADE,
        blank=True, null=True,
        related_name='likes',
        verbose_name=_('commentaire (commerçant)'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('like de commentaire')
        verbose_name_plural = _('likes de commentaires')
        constraints = [
            # Exactement un des deux champs commentaire_* est rempli
            models.CheckConstraint(
                check=(
                    models.Q(commentaire_article__isnull=False, commentaire_partenaire__isnull=True)
                    | models.Q(commentaire_article__isnull=True, commentaire_partenaire__isnull=False)
                ),
                name='like_commentaire_exclusif',
            ),
            # Pas deux fois la même paire user × commentaire d'article
            models.UniqueConstraint(
                fields=['user', 'commentaire_article'],
                condition=models.Q(commentaire_article__isnull=False),
                name='unique_like_commentaire_article',
            ),
            # Pas deux fois la même paire user × commentaire de commerçant
            models.UniqueConstraint(
                fields=['user', 'commentaire_partenaire'],
                condition=models.Q(commentaire_partenaire__isnull=False),
                name='unique_like_commentaire_partenaire',
            ),
        ]

    def __str__(self):
        cible = self.commentaire_article or self.commentaire_partenaire
        return f"{self.user.telephone} ❤️ commentaire #{cible.id}"

# ═══════════════════════════════════════════════════════════════════════
# AVIS ⭐ (note 1-5 + commentaire sur un objet terminé : commande, course,
# intervention, réservation). Règles métier dans apps.social.avis.
# ═══════════════════════════════════════════════════════════════════════

class Avis(models.Model):
    """Avis d'un client sur un objet qu'il a reçu (statut final positif).
    Un seul avis par (auteur, objet). La note moyenne du partenaire
    (ProfilPartenaire.note_moyenne / nb_avis) est recalculée à chaque
    création, modification ou masquage (avis visibles seulement)."""

    class TypeObjet(models.TextChoices):
        COMMANDE = 'commande', _('Commande')
        COURSE = 'course', _('Course (livraison)')
        INTERVENTION = 'intervention', _("Demande d'intervention")
        RESERVATION = 'reservation', _('Réservation (location)')

    auteur = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='avis_donnes', verbose_name=_('auteur'))
    objet_type = models.CharField(_("type d'objet"), max_length=20, choices=TypeObjet.choices)
    objet_id = models.CharField(
        _("id de l'objet"), max_length=64,
        help_text=_('Entier (commande, intervention, réservation) ou UUID (course).'))
    partenaire = models.ForeignKey(
        ProfilPartenaire, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='avis', verbose_name=_('partenaire noté'))
    livreur = models.ForeignKey(
        'livreurs.Livreur', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='avis', verbose_name=_('livreur (courses)'))
    note = models.PositiveSmallIntegerField(_('note (1 à 5)'))
    commentaire = models.TextField(_('commentaire'), max_length=1000, blank=True)
    est_visible = models.BooleanField(_('visible'), default=True)
    reponse_partenaire = models.TextField(_('réponse du partenaire'), max_length=1000, null=True, blank=True)
    repondu_le = models.DateTimeField(_('répondu le'), null=True, blank=True)
    cree_le = models.DateTimeField(_('créé le'), auto_now_add=True)
    modifie_le = models.DateTimeField(_('modifié le'), auto_now=True)

    class Meta:
        verbose_name = _('avis')
        verbose_name_plural = _('avis')
        ordering = ['-cree_le']
        constraints = [
            models.UniqueConstraint(fields=['auteur', 'objet_type', 'objet_id'], name='unique_avis_par_objet'),
            models.CheckConstraint(check=models.Q(note__gte=1, note__lte=5), name='avis_note_1_a_5'),
        ]
        indexes = [
            models.Index(fields=['partenaire', 'est_visible', '-cree_le'], name='avis_partenaire_idx'),
        ]

    def __str__(self):
        return f'{self.auteur} → {self.objet_type} {self.objet_id} : {self.note}/5'
