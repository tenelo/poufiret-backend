from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import ModeleBase


class TempsSessionUtilisateur(ModeleBase):
    """Session d'utilisation de l'application, mesurée par heartbeat.

    Flutter appelle demarrer/ à l'ouverture, puis ping/ toutes les 60s.
    La durée réelle = dernier_ping - debut.
    """

    class Source(models.TextChoices):
        MOBILE = 'mobile', 'Application mobile'
        WEB = 'web', 'Web'

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sessions_app',
        verbose_name='utilisateur',
    )
    debut = models.DateTimeField('début', default=timezone.now)
    dernier_ping = models.DateTimeField('dernier ping', default=timezone.now)
    source = models.CharField(
        'source', max_length=10,
        choices=Source.choices, default=Source.MOBILE,
    )
    est_active = models.BooleanField('active', default=True)

    class Meta:
        verbose_name = 'temps de session utilisateur'
        verbose_name_plural = 'temps de sessions utilisateurs'
        ordering = ['-debut']
        indexes = [
            models.Index(fields=['utilisateur', 'debut']),
        ]

    @property
    def duree_secondes(self):
        return int((self.dernier_ping - self.debut).total_seconds())

    @property
    def minute_session(self):
        """Minute courante de la session (pour la pub ultima)."""
        return self.duree_secondes // 60

    def __str__(self):
        return f'{self.utilisateur} — {self.debut:%d/%m/%Y %H:%M} ({self.duree_secondes}s)'


class ProfilNavigation(ModeleBase):
    """Agrégat des habitudes de navigation d'un utilisateur.

    Mis à jour au fil de l'eau (vues d'articles, fins de session).
    Remis à zéro chaque mois pour les compteurs mensuels.
    """

    utilisateur = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profil_navigation',
        verbose_name='utilisateur',
    )
    # Compteurs du mois courant
    mois_reference = models.DateField('mois de référence')
    nb_articles_vus_mois = models.PositiveIntegerField('articles vus ce mois', default=0)
    temps_cumule_secondes_mois = models.PositiveIntegerField('temps cumulé ce mois (s)', default=0)
    # Habitudes (cumulées, tous mois confondus)
    categories_consultees = models.JSONField(
        'catégories consultées', default=dict, blank=True,
        help_text='{"slug_categorie": nombre_de_vues}',
    )
    derniere_activite = models.DateTimeField('dernière activité', null=True, blank=True)

    class Meta:
        verbose_name = 'profil de navigation'
        verbose_name_plural = 'profils de navigation'

    def __str__(self):
        return f'Profil navigation — {self.utilisateur}'
