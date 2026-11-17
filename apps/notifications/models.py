"""Abonnements Web Push (admin web Angular, PWA ngsw) : un par navigateur /
appareil, liés à l'utilisateur. Le mobile Flutter (FCM) n'est pas concerné."""
from django.conf import settings
from django.db import models


class AbonnementPushWeb(models.Model):
    """PushSubscription d'un navigateur (endpoint + clés p256dh / auth).
    Un utilisateur peut en avoir plusieurs (PC, téléphone…). Un même
    navigateur (endpoint) n'appartient qu'à un compte : s'il est réabonné
    par un autre compte, il lui est rattaché. Supprimé sur réponse 404 / 410
    du service push, ou après MAX_ECHECS échecs consécutifs."""
    MAX_ECHECS = 5

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='abonnements_push_web', verbose_name='utilisateur')
    endpoint = models.CharField('endpoint', max_length=1000, unique=True)
    p256dh = models.CharField('clé p256dh', max_length=200)
    auth = models.CharField('clé auth', max_length=100)
    user_agent = models.CharField('navigateur', max_length=300, blank=True)
    cree_le = models.DateTimeField('créé le', auto_now_add=True)
    modifie_le = models.DateTimeField('modifié le', auto_now=True)
    dernier_envoi_ok = models.DateTimeField('dernier envoi réussi', null=True, blank=True)
    nb_echecs = models.PositiveSmallIntegerField('échecs consécutifs', default=0)

    class Meta:
        verbose_name = 'abonnement Web Push'
        verbose_name_plural = 'abonnements Web Push'
        ordering = ['-modifie_le']

    def __str__(self):
        return f'{self.user} — {self.user_agent[:40] or self.endpoint[:40]}'
