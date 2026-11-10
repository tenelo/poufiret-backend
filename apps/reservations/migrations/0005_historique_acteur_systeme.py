"""Additif : rôle « systeme » dans l'historique des demandes (refus
automatique d'une demande en attente dont les dates sont déjà réservées)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reservations", "0004_nature_achat"),
    ]

    operations = [
        migrations.AlterField(
            model_name="historiquedemande",
            name="acteur_role",
            field=models.CharField(choices=[("client", "Client"), ("loueur", "Loueur"), ("admin", "Admin"),
                                            ("systeme", "Système")],
                                   max_length=10, verbose_name="rôle de l'acteur"),
        ),
    ]
