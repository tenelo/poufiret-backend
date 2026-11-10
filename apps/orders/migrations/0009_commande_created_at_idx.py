"""Index de date pour les statistiques d'usage par période (admin)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0008_elevage'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='commande',
            index=models.Index(fields=['created_at'], name='commande_created_at_idx'),
        ),
    ]
