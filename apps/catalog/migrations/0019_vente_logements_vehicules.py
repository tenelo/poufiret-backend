"""Additif : vente des logements et véhicules.

mode_transaction (location | vente | location_vente), défaut « location » :
l'AddField remplit toutes les annonces existantes à « location » — tout
l'existant reste une location. Champs de vente communs (prix_vente,
prix_negociable, vendu, vendu_le) + champs propres au véhicule vendu et à
la maison vendue. Vehicule.mode (champ historique du catalogue) inchangé.
"""
from django.db import migrations, models

MODES = [("location", "Location"), ("vente", "Vente"), ("location_vente", "Location ou vente")]


def champs_vente(modele):
    return [
        migrations.AddField(
            model_name=modele, name="mode_transaction",
            field=models.CharField(choices=MODES, default="location", max_length=15,
                                   verbose_name="mode de transaction"),
        ),
        migrations.AddField(
            model_name=modele, name="prix_vente",
            field=models.DecimalField(blank=True, decimal_places=0, max_digits=14, null=True,
                                      verbose_name="prix de vente (FCFA)"),
        ),
        migrations.AddField(
            model_name=modele, name="prix_negociable",
            field=models.BooleanField(default=True, verbose_name="prix négociable"),
        ),
        migrations.AddField(
            model_name=modele, name="vendu",
            field=models.BooleanField(default=False, verbose_name="vendu"),
        ),
        migrations.AddField(
            model_name=modele, name="vendu_le",
            field=models.DateTimeField(blank=True, null=True, verbose_name="vendu le"),
        ),
    ]


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0018_rattachement_types_gabarits"),
    ]

    operations = [
        *champs_vente("logement"),
        migrations.AddField(
            model_name="logement", name="type_document",
            field=models.CharField(blank=True, choices=[
                ("acd", "ACD (arrêté de concession définitive)"),
                ("certificat_foncier", "Certificat foncier"),
                ("lettre_attribution", "Lettre d'attribution"),
                ("attestation_villageoise", "Attestation villageoise"),
                ("autre", "Autre")], max_length=30, verbose_name="document de propriété"),
        ),
        migrations.AddField(
            model_name="logement", name="surface_terrain_m2",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="surface du terrain (m²)"),
        ),
        migrations.AddField(
            model_name="logement", name="est_lotie",
            field=models.BooleanField(blank=True, null=True, verbose_name="parcelle lotie"),
        ),
        *champs_vente("vehicule"),
        migrations.AddField(
            model_name="vehicule", name="etat",
            field=models.CharField(blank=True, choices=[
                ("neuf", "Neuf"), ("occasion_locale", "Occasion locale"),
                ("france_au_revoir", "France au revoir (occasion importée)")],
                max_length=20, verbose_name="état"),
        ),
        migrations.AddField(
            model_name="vehicule", name="dedouane",
            field=models.BooleanField(blank=True, null=True, verbose_name="dédouané"),
        ),
        migrations.AddField(
            model_name="vehicule", name="carte_grise",
            field=models.BooleanField(blank=True, null=True, verbose_name="carte grise"),
        ),
        migrations.AddField(
            model_name="vehicule", name="visite_technique_valide_jusqu_au",
            field=models.DateField(blank=True, null=True, verbose_name="visite technique valide jusqu'au"),
        ),
        migrations.AddField(
            model_name="vehicule", name="assurance_valide_jusqu_au",
            field=models.DateField(blank=True, null=True, verbose_name="assurance valide jusqu'au"),
        ),
        migrations.AddField(
            model_name="vehicule", name="nb_proprietaires",
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="nombre de propriétaires"),
        ),
    ]
