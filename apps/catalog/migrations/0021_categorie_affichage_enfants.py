"""Additif : présentation des sous-catégories (pastilles | grille), réglée
par l'admin. Toutes les catégories existantes : « pastilles ».
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0020_variante_prix'),
    ]

    operations = [
        migrations.AddField(
            model_name='categorie',
            name='affichage_enfants',
            field=models.CharField(
                choices=[('pastilles', 'Pastilles'), ('grille', 'Grille')], default='pastilles',
                max_length=10, verbose_name='affichage des sous-catégories'),
        ),
    ]
