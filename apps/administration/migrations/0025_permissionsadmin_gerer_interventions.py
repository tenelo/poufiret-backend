from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("administration", "0024_locations_v2"),
    ]

    operations = [
        migrations.AddField(
            model_name="permissionsadmin",
            name="gerer_interventions",
            field=models.BooleanField(
                default=False,
                verbose_name="gérer les demandes d'intervention (écriture ; implique la lecture)",
            ),
        ),
    ]
