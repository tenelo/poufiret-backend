"""Additif : prix propre d'une variante (ex. « Plaquette de 30 »,
« Poulet pondeuse »). Null pour toutes les variantes existantes : elles
gardent prix de l'article + prix_supplement.
"""
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0019_vente_logements_vehicules'),
    ]

    operations = [
        migrations.AddField(
            model_name='variante',
            name='prix',
            field=models.DecimalField(
                blank=True, decimal_places=0, max_digits=12, null=True,
                validators=[django.core.validators.MinValueValidator(0)],
                verbose_name='prix propre (FCFA)',
                help_text="Facultatif : remplace le prix de l'article pour cette variante."),
        ),
    ]
