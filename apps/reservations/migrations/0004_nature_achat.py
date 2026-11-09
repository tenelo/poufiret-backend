"""Additif : nature « achat » (annonce à vendre : information ou visite en
vue d'achat, sans dates de location)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reservations", "0003_locations_v2"),
    ]

    operations = [
        migrations.AlterField(
            model_name="demandereservation",
            name="nature",
            field=models.CharField(choices=[("visite", "Visite"), ("reservation", "Réservation"),
                                            ("achat", "Achat (information ou visite)")],
                                   max_length=15, verbose_name="nature"),
        ),
    ]
