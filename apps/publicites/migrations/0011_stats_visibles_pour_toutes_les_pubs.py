"""Migration de données : les stats deviennent visibles par défaut côté
partenaire (voir 0010, default=True) — on aligne aussi les pubs existantes.
Réversible sans perte : le retour arrière ne touche à rien (l'état d'avant
n'était pas uniforme et n'est pas reconstituable)."""
from django.db import migrations


def tout_visible(apps, schema_editor):
    Publicite = apps.get_model('publicites', 'Publicite')
    Publicite.objects.filter(stats_visibles_partenaire=False).update(
        stats_visibles_partenaire=True)


class Migration(migrations.Migration):

    dependencies = [
        ('publicites', '0010_alter_publicite_stats_visibles_partenaire'),
    ]

    operations = [
        migrations.RunPython(tout_visible, migrations.RunPython.noop),
    ]
