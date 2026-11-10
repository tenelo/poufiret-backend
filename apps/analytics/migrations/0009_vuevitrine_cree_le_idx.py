"""Index de date pour les statistiques d'usage par période (admin)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0008_recherchelog_evenementapp'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='vuevitrine',
            index=models.Index(fields=['cree_le'], name='vuevitrine_cree_le_idx'),
        ),
    ]
