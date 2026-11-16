"""Additif : lien d'une pub reconduite vers son original. Pas de rattrapage :
les reconductions antérieures restent sans lien (null)."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('publicites', '0012_publicite_cree_par_admin'),
    ]

    operations = [
        migrations.AddField(
            model_name='publicite',
            name='reconduite_depuis',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='reconductions', to='publicites.publicite', verbose_name='reconduite depuis'),
        ),
    ]
