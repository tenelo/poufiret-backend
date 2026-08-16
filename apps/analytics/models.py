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
    nb_vues_catalogue_mois = models.PositiveIntegerField('vues de catalogue ce mois', default=0)
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

    # ── Scoring d'engagement ─────────────────────────────────────────
    SEUIL_JOURS_CONNEXION = 7
    SEUIL_ARTICLES_MOIS = 5
    SEUIL_MINUTES_MOIS = 15

    @property
    def est_client_actif(self):
        """Client actif = connecté sous 7 jours ET >=5 articles ce mois
        ET >=15 minutes cumulées ce mois (3 conditions cumulatives)."""
        if not self.derniere_activite:
            return False
        p = ParametresAnalytics.obtenir()
        recence_ok = (timezone.now() - self.derniere_activite).days < p.seuil_jours_connexion
        articles_ok = self.nb_articles_vus_mois >= p.seuil_articles_mois
        temps_ok = self.temps_cumule_secondes_mois >= p.seuil_minutes_mois * 60
        return recence_ok and articles_ok and temps_ok


class ParametresAnalytics(ModeleBase):
    """Paramètres modifiables du scoring d'engagement (ligne unique)."""

    seuil_jours_connexion = models.PositiveIntegerField(
        'seuil jours dernière connexion', default=7,
        help_text='Client actif si connecté il y a moins de N jours',
    )
    seuil_articles_mois = models.PositiveIntegerField(
        'seuil articles vus par mois', default=5,
    )
    seuil_minutes_mois = models.PositiveIntegerField(
        'seuil minutes cumulées par mois', default=15,
    )
    seuil_en_ligne_secondes = models.PositiveIntegerField(
        'seuil "en ligne maintenant" (secondes)', default=120,
        help_text=(
            'Un utilisateur est compté "en ligne" si son dernier ping '
            'date de moins de N secondes. Le ping est envoyé toutes les '
            '60 s ; garder ce seuil >= 60 (120 = 2 pings de marge).'
        ),
    )

    class Meta:
        verbose_name = 'paramètres analytics'
        verbose_name_plural = 'paramètres analytics'

    def save(self, *args, **kwargs):
        # Singleton : on force une seule ligne
        self.pk = self.pk or self.__class__.objects.first() and self.__class__.objects.first().pk or None
        super().save(*args, **kwargs)

    @classmethod
    def obtenir(cls):
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj

    def __str__(self):
        return f'Paramètres analytics ({self.seuil_jours_connexion}j / {self.seuil_articles_mois} art. / {self.seuil_minutes_mois} min)'


class VueVitrine(ModeleBase):
    """Trace chaque consultation de la vitrine d'un partenaire.

    Pendant du VueArticle du catalogue : indispensable pour les metiers de
    service (plombier, mecanicien...) ou le client ne consulte aucun article.
    """

    class Source(models.TextChoices):
        ANNUAIRE = 'annuaire', 'Liste de la categorie'
        RECHERCHE = 'recherche', 'Recherche'
        ARTICLE = 'article', 'Depuis une fiche article'
        FAVORIS = 'favoris', 'Liste des favoris'
        PUBLICITE = 'publicite', 'Depuis une publicite'
        AUTRE = 'autre', 'Autre'

    partenaire = models.ForeignKey(
        'users.ProfilPartenaire',
        on_delete=models.CASCADE,
        related_name='vues_vitrine',
        verbose_name='partenaire',
    )
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='vues_vitrines',
        verbose_name='utilisateur',
    )
    source = models.CharField(
        'source', max_length=15,
        choices=Source.choices, default=Source.AUTRE,
    )

    class Meta:
        verbose_name = 'vue de vitrine'
        verbose_name_plural = 'vues de vitrine'
        ordering = ['-cree_le']
        indexes = [
            models.Index(fields=['partenaire', 'cree_le']),
        ]

    def __str__(self):
        return f'{self.partenaire} — {self.utilisateur or "anonyme"}'



class VueServiceLivraison(ModeleBase):
    """Trace chaque ouverture de l'ecran/service livraison par un utilisateur,
    pour mesurer combien de personnes consultent la livraison (vs combien
    l'utilisent reellement en creant une course).
    """

    class Source(models.TextChoices):
        ONGLET = 'onglet', 'Onglet de la barre du bas'
        AUTRE = 'autre', 'Autre'

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='vues_service_livraison',
        verbose_name='utilisateur',
    )
    source = models.CharField(
        'source', max_length=15,
        choices=Source.choices, default=Source.ONGLET,
    )

    class Meta:
        verbose_name = 'vue du service livraison'
        verbose_name_plural = 'vues du service livraison'
        ordering = ['-cree_le']

    def __str__(self):
        return f'{self.utilisateur or "anonyme"} — {self.cree_le:%d/%m/%Y %H:%M}'
