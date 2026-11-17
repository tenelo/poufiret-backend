"""Abonnements Web Push (admin web). Première migration de l'app
notifications (aucun modèle auparavant). Additif."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AbonnementPushWeb',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('endpoint', models.CharField(max_length=1000, unique=True, verbose_name='endpoint')),
                ('p256dh', models.CharField(max_length=200, verbose_name='clé p256dh')),
                ('auth', models.CharField(max_length=100, verbose_name='clé auth')),
                ('user_agent', models.CharField(blank=True, max_length=300, verbose_name='navigateur')),
                ('cree_le', models.DateTimeField(auto_now_add=True, verbose_name='créé le')),
                ('modifie_le', models.DateTimeField(auto_now=True, verbose_name='modifié le')),
                ('dernier_envoi_ok', models.DateTimeField(blank=True, null=True, verbose_name='dernier envoi réussi')),
                ('nb_echecs', models.PositiveSmallIntegerField(default=0, verbose_name='échecs consécutifs')),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name='abonnements_push_web',
                    to=settings.AUTH_USER_MODEL, verbose_name='utilisateur')),
            ],
            options={
                'verbose_name': 'abonnement Web Push',
                'verbose_name_plural': 'abonnements Web Push',
                'ordering': ['-modifie_le'],
            },
        ),
    ]
