from django.db import migrations

TYPES_RESTAURATION = ['restaurateur']


def creer_fiches(apps, schema_editor):
    ProfilPartenaire = apps.get_model('users', 'ProfilPartenaire')
    ProfilRestaurant = apps.get_model('restaurants', 'ProfilRestaurant')
    existants = ProfilRestaurant.objects.values_list('partenaire_id', flat=True)
    ProfilRestaurant.objects.bulk_create(
        [ProfilRestaurant(partenaire_id=pid) for pid in
         ProfilPartenaire.objects.filter(type_partenaire__in=TYPES_RESTAURATION)
         .exclude(id__in=existants).values_list('id', flat=True)],
        ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ('restaurants', '0002_remove_profilrestaurant_whatsapp'),
        ('users', '0019_alter_numeroverifie_source'),
    ]

    operations = [
        migrations.RunPython(creer_fiches, migrations.RunPython.noop),
    ]
