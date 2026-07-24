"""Active l'extension unaccent : recherche insensible aux accents.

Sans elle, "braise" ne trouve pas "Poisson Braisé" — inacceptable
quand la majorite des clients tapent sans accent.
"""
from django.contrib.postgres.operations import UnaccentExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0008_categorie_mots_cles_recherchesansresultat'),
    ]

    operations = [
        UnaccentExtension(),
    ]
