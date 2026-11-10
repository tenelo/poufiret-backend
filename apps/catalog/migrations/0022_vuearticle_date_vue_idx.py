"""Index de date pour les statistiques d'usage par période (admin)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0021_categorie_affichage_enfants'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='vuearticle',
            index=models.Index(fields=['date_vue'], name='vuearticle_date_vue_idx'),
        ),
    ]
