"""Découpage administratif de la Côte d'Ivoire, limité aux niveaux utiles.

District > Région > Département. On s'arrête au département : un habitant
d'un village ou d'une sous-préfecture de Ferké dit simplement
« département de Ferké ». Descendre plus bas obligerait à regrouper des
dizaines de communes sans gain pour l'analyse.

L'utilisateur et le partenaire ne choisissent que leur DÉPARTEMENT ; la
région et le district en sont déduits par les relations.
"""
from django.db import models


class District(models.Model):
    nom = models.CharField('nom', max_length=100, unique=True)
    ordre = models.PositiveIntegerField('ordre d\'affichage', default=0)

    class Meta:
        verbose_name = 'district'
        verbose_name_plural = 'districts'
        ordering = ['ordre', 'nom']

    def __str__(self):
        return self.nom


class Region(models.Model):
    nom = models.CharField('nom', max_length=100, unique=True)
    district = models.ForeignKey(
        District, on_delete=models.PROTECT,
        related_name='regions', verbose_name='district',
    )
    ordre = models.PositiveIntegerField('ordre d\'affichage', default=0)
    est_actif = models.BooleanField(
        'actif', default=True,
        help_text='Décocher pour masquer cette région du choix des '
                  'utilisateurs sans la supprimer.',
    )
    cree_le = models.DateTimeField('créé le', auto_now_add=True, null=True)
    modifie_le = models.DateTimeField('modifié le', auto_now=True, null=True)

    class Meta:
        verbose_name = 'région'
        verbose_name_plural = 'régions'
        ordering = ['ordre', 'nom']

    def __str__(self):
        return self.nom


class Departement(models.Model):
    nom = models.CharField('nom', max_length=100)
    region = models.ForeignKey(
        Region, on_delete=models.PROTECT,
        related_name='departements', verbose_name='région',
    )
    ordre = models.PositiveIntegerField('ordre d\'affichage', default=0)
    est_actif = models.BooleanField(
        'actif', default=True,
        help_text='Décocher pour masquer ce département du choix des '
                  'utilisateurs sans le supprimer.',
    )
    cree_le = models.DateTimeField('créé le', auto_now_add=True, null=True)
    modifie_le = models.DateTimeField('modifié le', auto_now=True, null=True)

    class Meta:
        verbose_name = 'département'
        verbose_name_plural = 'départements'
        ordering = ['ordre', 'nom']
        constraints = [
            models.UniqueConstraint(
                fields=['nom', 'region'], name='unique_departement_region'),
        ]

    def __str__(self):
        return self.nom

    @property
    def district(self):
        """Raccourci : le district dont dépend ce département."""
        return self.region.district


class Localite(models.Model):
    """Localité (ville, commune, sous-préfecture...) d'un département.

    Niveau intermédiaire entre Département et Quartier, ajouté pour la
    gestion admin détaillée de la géographie (voir apps.geo.admin_views).
    """
    nom = models.CharField('nom', max_length=120)
    departement = models.ForeignKey(
        Departement, on_delete=models.PROTECT,
        related_name='localites', verbose_name='département',
    )
    ordre = models.PositiveIntegerField("ordre d'affichage", default=0)
    est_actif = models.BooleanField('actif', default=True)
    cree_le = models.DateTimeField('créé le', auto_now_add=True, null=True)
    modifie_le = models.DateTimeField('modifié le', auto_now=True, null=True)

    class Meta:
        verbose_name = 'localité'
        verbose_name_plural = 'localités'
        ordering = ['ordre', 'nom']
        constraints = [
            models.UniqueConstraint(
                fields=['nom', 'departement'],
                name='unique_localite_departement'),
        ]

    def __str__(self):
        return f'{self.nom} ({self.departement})'


class Quartier(models.Model):
    """Quartier d'une localité (niveau le plus fin, saisi en livraison).

    Sert à l'autocomplétion des points de retrait/livraison. Enrichissable
    au fil de l'eau (comme les mots-clés de recherche) : on démarre avec les
    quartiers connus et on complète à mesure.
    """
    nom = models.CharField('nom', max_length=120)
    localite = models.ForeignKey(
        Localite, on_delete=models.PROTECT,
        related_name='quartiers', verbose_name='localité',
    )
    ordre = models.PositiveIntegerField("ordre d'affichage", default=0)
    est_actif = models.BooleanField('actif', default=True)
    cree_le = models.DateTimeField('créé le', auto_now_add=True, null=True)
    modifie_le = models.DateTimeField('modifié le', auto_now=True, null=True)

    class Meta:
        verbose_name = 'quartier'
        verbose_name_plural = 'quartiers'
        ordering = ['ordre', 'nom']
        constraints = [
            models.UniqueConstraint(
                fields=['nom', 'localite'],
                name='unique_quartier_localite'),
        ]

    def __str__(self):
        return f'{self.nom} ({self.localite})'

