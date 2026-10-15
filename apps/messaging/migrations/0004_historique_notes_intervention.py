import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('messaging', '0003_demandeintervention_latitude_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='HistoriqueIntervention',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('statut', models.CharField(choices=[('en_attente', 'En attente'), ('acceptee', 'Acceptée'), ('refusee', 'Refusée'), ('en_cours', 'En cours'), ('terminee', 'Terminée'), ('annulee', 'Annulée')], max_length=20, verbose_name='statut atteint')),
                ('acteur_role', models.CharField(choices=[('client', 'Client'), ('artisan', 'Artisan'), ('admin', 'Admin')], max_length=12, verbose_name="rôle de l'acteur")),
                ('commentaire', models.TextField(blank=True, verbose_name='commentaire')),
                ('cree_le', models.DateTimeField(auto_now_add=True, verbose_name='créé le')),
                ('acteur', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='acteur')),
                ('demande', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='historique', to='messaging.demandeintervention', verbose_name="demande d'intervention")),
            ],
            options={
                'verbose_name': "historique de demande d'intervention",
                'verbose_name_plural': "historiques de demandes d'intervention",
                'ordering': ['cree_le'],
                'indexes': [models.Index(fields=['demande', 'cree_le'], name='hist_interv_demande_idx')],
            },
        ),
        migrations.CreateModel(
            name='NoteAdminIntervention',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('texte', models.TextField(verbose_name='texte')),
                ('cree_le', models.DateTimeField(auto_now_add=True, verbose_name='créé le')),
                ('auteur', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='auteur')),
                ('demande', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notes_admin', to='messaging.demandeintervention', verbose_name="demande d'intervention")),
            ],
            options={
                'verbose_name': "note admin sur demande d'intervention",
                'verbose_name_plural': "notes admin sur demandes d'intervention",
                'ordering': ['-cree_le'],
            },
        ),
    ]
