"""Journal d'audit factorisé + connexions admin à une ligne par admin.

1. JournalModeration : occurrences (défaut 1) et derniere_occurrence
   (additifs, remplie = cree_le pour l'existant), index de liste et de
   regroupement.
2. ConnexionAdmin (une ligne par admin) remplie depuis les sessions
   appareils des comptes is_staff : premiere = plus ancienne, derniere =
   plus récente (IP, appareil, plateforme de celle-ci), nb_connexions =
   nombre de lignes.
3. Doublons supprimés : pour chaque admin, les sessions « sans appareil_id »
   (une par connexion web jusqu'ici) sont réduites à la plus récente. Les
   sessions identifiées par appareil_id (déjà une par appareil, utiles à la
   révocation ciblée) sont conservées.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Count, F, Max, Min


def remplir_journal(apps, schema_editor):
    JournalModeration = apps.get_model('administration', 'JournalModeration')
    n = JournalModeration.objects.filter(derniere_occurrence__isnull=True).update(
        derniere_occurrence=F('cree_le'))
    print(f'\n  Journal : derniere_occurrence remplie pour {n} entrée(s).')


def regrouper_connexions(apps, schema_editor):
    SessionAppareil = apps.get_model('users', 'SessionAppareil')
    ConnexionAdmin = apps.get_model('administration', 'ConnexionAdmin')

    admins = SessionAppareil.objects.filter(user__is_staff=True)
    avant = admins.count()
    stats = (admins.order_by().values('user_id')
             .annotate(nb=Count('id'), premiere=Min('cree_le'), derniere=Max('cree_le')))
    crees = 0
    for s in stats:
        if ConnexionAdmin.objects.filter(admin_id=s['user_id']).exists():
            continue
        recente = admins.filter(user_id=s['user_id']).order_by('-cree_le').first()
        ConnexionAdmin.objects.create(
            admin_id=s['user_id'], premiere_connexion=s['premiere'],
            derniere_connexion=s['derniere'], nb_connexions=s['nb'],
            derniere_ip=recente.adresse_ip, dernier_appareil=(recente.appareil_nom or '')[:500],
            derniere_plateforme=recente.plateforme or '')
        crees += 1

    supprimees = 0
    for user_id in (admins.filter(appareil_id='').order_by().values('user_id')
                    .annotate(n=Count('id')).filter(n__gt=1).values_list('user_id', flat=True)):
        garder = (admins.filter(user_id=user_id, appareil_id='')
                  .order_by('-cree_le').values_list('id', flat=True).first())
        supprimees += (admins.filter(user_id=user_id, appareil_id='')
                       .exclude(id=garder).delete()[0])
    apres = SessionAppareil.objects.filter(user__is_staff=True).count()
    print(f'  Connexions admin : sessions appareils admin {avant} → {apres} ligne(s) '
          f'({supprimees} doublon(s) supprimé(s)) ; ConnexionAdmin : {crees} ligne(s) créée(s) '
          f'(une par admin).')


class Migration(migrations.Migration):

    dependencies = [
        ('administration', '0025_permissionsadmin_gerer_interventions'),
        ('users', '0021_position_partenaire'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='journalmoderation',
            name='occurrences',
            field=models.PositiveIntegerField(default=1, verbose_name='occurrences'),
        ),
        migrations.AddField(
            model_name='journalmoderation',
            name='derniere_occurrence',
            field=models.DateTimeField(blank=True, help_text='Date de la dernière occurrence regroupée (= cree_le si une seule).', null=True, verbose_name='dernière occurrence'),
        ),
        migrations.AddIndex(
            model_name='journalmoderation',
            index=models.Index(fields=['-cree_le'], name='journal_cree_le_idx'),
        ),
        migrations.AddIndex(
            model_name='journalmoderation',
            index=models.Index(fields=['acteur', 'action', '-derniere_occurrence'], name='journal_regroupement_idx'),
        ),
        migrations.RunPython(remplir_journal, migrations.RunPython.noop),
        migrations.CreateModel(
            name='ConnexionAdmin',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('premiere_connexion', models.DateTimeField(verbose_name='première connexion')),
                ('derniere_connexion', models.DateTimeField(db_index=True, verbose_name='dernière connexion')),
                ('nb_connexions', models.PositiveIntegerField(default=1, verbose_name='nombre de connexions')),
                ('derniere_ip', models.GenericIPAddressField(blank=True, null=True, verbose_name='dernière adresse IP')),
                ('dernier_appareil', models.CharField(blank=True, max_length=500, verbose_name='dernier appareil (user agent)')),
                ('derniere_plateforme', models.CharField(blank=True, max_length=10, verbose_name='dernière plateforme')),
                ('admin', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='connexion_admin', to=settings.AUTH_USER_MODEL, verbose_name='compte admin')),
            ],
            options={
                'verbose_name': 'connexion admin',
                'verbose_name_plural': 'connexions admin',
                'ordering': ['-derniere_connexion'],
            },
        ),
        migrations.RunPython(regrouper_connexions, migrations.RunPython.noop),
    ]
