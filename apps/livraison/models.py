"""Modeles de l'app livraison : la Course (course directe A -> B).

Une course = un point de retrait (A) + un point de livraison (B) + un
demandeur. Chaque point porte TOUJOURS quartier + nom + contact, et
EN PLUS des coordonnees GPS si disponibles (obligatoires si c'est la
position du demandeur lui-meme).
"""
from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.db import models
from apps.core.models import ModeleBase


class Course(ModeleBase):
    """Course de livraison directe, dans une ville (= Departement)."""

    class Statut(models.TextChoices):
        DEMANDEE = 'demandee', 'Demandee'
        ASSIGNEE = 'assignee', 'Assignee a un livreur'
        ACCEPTEE = 'acceptee', 'Acceptee'
        VERS_A = 'vers_a', 'En route vers le retrait'
        COLIS_PRIS = 'colis_pris', 'Colis recupere'
        VERS_B = 'vers_b', 'En route vers la livraison'
        LIVREE = 'livree', 'Livree'
        REFUSEE = 'refusee', 'Refusee par le livreur'
        ANNULEE = 'annulee', 'Annulee'

    numero = models.CharField(max_length=30, unique=True, editable=False)

    demandeur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='courses_demandees',
        verbose_name='demandeur',
    )
    # Type conserve pour l'analytics uniquement (invisible cote UI).
    type_demandeur = models.CharField(
        max_length=12, blank=True, default='',
        help_text='client / partenaire — pour analytics seulement.',
    )
    ville = models.ForeignKey(
        'geo.Departement',
        on_delete=models.PROTECT,
        related_name='courses',
        verbose_name='ville',
    )
    livreur = models.ForeignKey(
        'livreurs.Livreur',
        on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='courses',
        verbose_name='livreur assigne',
    )

    # ── Point A (retrait) ────────────────────────────────────────────
    a_quartier = models.CharField('A - quartier', max_length=150)
    a_nom_contact = models.CharField('A - nom contact', max_length=150)
    a_telephone_contact = models.CharField('A - telephone', max_length=20)
    a_position = gis_models.PointField(
        'A - GPS', geography=True, blank=True, null=True)

    # ── Point B (livraison) ──────────────────────────────────────────
    b_quartier = models.CharField('B - quartier', max_length=150)
    b_nom_contact = models.CharField('B - nom contact', max_length=150)
    b_telephone_contact = models.CharField('B - telephone', max_length=20)
    b_position = gis_models.PointField(
        'B - GPS', geography=True, blank=True, null=True)

    # Compte destinataire (point B) trouve par le lookup asynchrone APRES
    # creation. Jamais renseigne a la creation, jamais expose au demandeur
    # (sinon on divulguerait l'existence des comptes). Sert a lier la course
    # au compte du destinataire : notif + depot de sa propre position.
    contact_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='courses_recues',
        verbose_name='compte destinataire (B)',
    )

    description_colis = models.CharField(
        max_length=200, blank=True, default='',
        help_text='Repere pour le livreur (ex: pain, pagne, chaussures).',
    )
    prix = models.PositiveIntegerField(
        default=0, help_text='Prix en FCFA (fixe au depart, evolutif).')

    statut = models.CharField(
        max_length=12, choices=Statut.choices, default=Statut.DEMANDEE)
    raison_refus = models.CharField(max_length=200, blank=True, default='')

    # Horodatages par etape.
    assignee_le = models.DateTimeField(blank=True, null=True)
    acceptee_le = models.DateTimeField(blank=True, null=True)
    colis_pris_le = models.DateTimeField(blank=True, null=True)
    livree_le = models.DateTimeField(blank=True, null=True)
    annulee_le = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = 'course'
        verbose_name_plural = 'courses'
        indexes = [
            models.Index(fields=['statut', '-cree_le']),
            models.Index(fields=['livreur', 'statut']),
        ]

    def __str__(self):
        return f'{self.numero} ({self.statut})'


# Machine a etats : transitions autorisees.
# Le refus est prevu structurellement mais desactive par defaut (flag).
TRANSITIONS = {
    'demandee': ['assignee', 'annulee'],
    'assignee': ['acceptee', 'refusee', 'annulee'],
    'acceptee': ['vers_a', 'annulee'],
    'vers_a': ['colis_pris', 'annulee'],
    'colis_pris': ['vers_b'],
    'vers_b': ['livree'],
    'refusee': ['assignee'],  # reassignation au livreur suivant
    'livree': [],
    'annulee': [],
}

# Etat a partir duquel le demandeur ne peut plus annuler (colis deja pris).
ANNULATION_DEMANDEUR_JUSQUA = ['demandee', 'assignee', 'acceptee', 'vers_a']


class ParametresLivraison(ModeleBase):
    """Parametres tarifaires de la livraison (ligne unique).

    Pour l'instant : un prix de course fixe et unique, pilotable depuis
    l'admin sans republier l'app. La grille fine (par ville / vehicule /
    distance) fera l'objet d'une passe dediee plus tard.
    """
    prix_course = models.PositiveIntegerField(
        'prix d\'une course (FCFA)', default=500,
        help_text='Prix unique applique a toute course, en FCFA.',
    )

    class Meta:
        verbose_name = 'parametres livraison'
        verbose_name_plural = 'parametres livraison'

    def save(self, *args, **kwargs):
        # Singleton : on force une seule ligne.
        self.pk = self.pk or self.__class__.objects.first() and self.__class__.objects.first().pk or None
        super().save(*args, **kwargs)

    @classmethod
    def obtenir(cls):
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj

    def __str__(self):
        return f'Parametres livraison (prix course : {self.prix_course} FCFA)'
