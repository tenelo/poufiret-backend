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
    nom = models.CharField('nom', max_length=100)
    district = models.ForeignKey(
        District, on_delete=models.PROTECT,
        related_name='regions', verbose_name='district',
    )
    ordre = models.PositiveIntegerField('ordre d\'affichage', default=0)

    class Meta:
        verbose_name = 'région'
        verbose_name_plural = 'régions'
        ordering = ['ordre', 'nom']
        constraints = [
            models.UniqueConstraint(
                fields=['nom', 'district'], name='unique_region_district'),
        ]

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
