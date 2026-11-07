"""Additif : consentements de collecte sur User ; note moyenne et nombre
d'avis sur ProfilPartenaire (recalculés par apps.social.avis)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0023_elevage"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="consentement_statistiques",
            field=models.BooleanField(default=False, verbose_name="consentement statistiques"),
        ),
        migrations.AddField(
            model_name="user",
            name="consentement_statistiques_le",
            field=models.DateTimeField(blank=True, null=True, verbose_name="consentement statistiques modifié le"),
        ),
        migrations.AddField(
            model_name="user",
            name="consentement_ia",
            field=models.BooleanField(default=False, verbose_name="consentement IA"),
        ),
        migrations.AddField(
            model_name="user",
            name="consentement_ia_le",
            field=models.DateTimeField(blank=True, null=True, verbose_name="consentement IA modifié le"),
        ),
        migrations.AddField(
            model_name="user",
            name="consentement_version",
            field=models.CharField(blank=True, help_text='Ex. "2026-11".', max_length=20,
                                   verbose_name="version des conditions acceptées"),
        ),
        migrations.AddField(
            model_name="profilpartenaire",
            name="note_moyenne",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=3, null=True,
                                      verbose_name="note moyenne des avis"),
        ),
        migrations.AddField(
            model_name="profilpartenaire",
            name="nb_avis",
            field=models.PositiveIntegerField(default=0, verbose_name="nombre d'avis visibles"),
        ),
    ]
