"""
Modèles de l'app social.

Module 3 du modèle Poufiret. Gère les interactions sociales :
- Likes (❤️ rouge, publics)   : LikeArticle, LikeCommercant, LikeCommentaire
- Favoris (🤎 marron, privés) : FavoriArticle, FavoriCommercant
- Commentaires                : CommentaireArticle, CommentaireCommercant
"""
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import Article
from apps.users.models import ProfilCommercant, User


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


class LikeCommercant(models.Model):
    """Like (❤️ rouge) public sur un commerçant."""
    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='likes_commercants', verbose_name=_('utilisateur'),
    )
    commercant = models.ForeignKey(
        ProfilCommercant, on_delete=models.CASCADE,
        related_name='likes', verbose_name=_('commerçant'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('like de commerçant')
        verbose_name_plural = _('likes de commerçants')
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'commercant'],
                name='unique_like_commercant',
            ),
        ]
        indexes = [
            models.Index(fields=['commercant', '-created_at']),
        ]

    def __str__(self):
        return f"{self.user.telephone} ❤️ {self.commercant.nom_commerce}"


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


class FavoriCommercant(models.Model):
    """Commerçant ajouté aux favoris privés d'un client (🤎 marron)."""
    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='favoris_commercants', verbose_name=_('utilisateur'),
    )
    commercant = models.ForeignKey(
        ProfilCommercant, on_delete=models.CASCADE,
        related_name='favoris', verbose_name=_('commerçant'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('favori - commerçant')
        verbose_name_plural = _('favoris - commerçants')
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'commercant'],
                name='unique_favori_commercant',
            ),
        ]
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"{self.user.telephone} 🤎 {self.commercant.nom_commerce}"


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


class CommentaireCommercant(models.Model):
    """
    Commentaire sur un commerçant (sur sa fiche, pas un article particulier).
    Supporte 1 niveau de réponse.
    """
    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='commentaires_commercants', verbose_name=_('utilisateur'),
    )
    commercant = models.ForeignKey(
        ProfilCommercant, on_delete=models.CASCADE,
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
            models.Index(fields=['commercant', '-created_at']),
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
    commentaire_commercant = models.ForeignKey(
        CommentaireCommercant,
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
                    models.Q(commentaire_article__isnull=False, commentaire_commercant__isnull=True)
                    | models.Q(commentaire_article__isnull=True, commentaire_commercant__isnull=False)
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
                fields=['user', 'commentaire_commercant'],
                condition=models.Q(commentaire_commercant__isnull=False),
                name='unique_like_commentaire_commercant',
            ),
        ]

    def __str__(self):
        cible = self.commentaire_article or self.commentaire_commercant
        return f"{self.user.telephone} ❤️ commentaire #{cible.id}"