"""Index pour la liste admin paginée (admin/liste/) : tri par onglet
(statut, cree_le) et filtre de période (fin_diffusion)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('publicites', '0013_publicite_reconduite_depuis'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='publicite',
            index=models.Index(fields=['statut', 'cree_le'], name='publicite_statut_cree_idx'),
        ),
        migrations.AddIndex(
            model_name='publicite',
            index=models.Index(fields=['fin_diffusion'], name='publicite_fin_diff_idx'),
        ),
    ]
