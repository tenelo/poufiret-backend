"""Pubs Poufiret (pubs maison du carrousel), leurs impressions, écrans du
parcours « Découvrir Poufiret » et réglages (singleton). Additif."""
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('publicites', '0014_publicite_index_liste_admin'),
        ('catalog', '0023_categorie_max_photos_par_article'),
        ('analytics', '0009_vuevitrine_cree_le_idx'),
        ('geo', '0006_departement_cree_le_departement_modifie_le_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PubPoufiret',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('cree_le', models.DateTimeField(auto_now_add=True)),
                ('modifie_le', models.DateTimeField(auto_now=True)),
                ('titre', models.CharField(max_length=100, verbose_name='titre')),
                ('texte', models.CharField(blank=True, max_length=200, verbose_name='texte court')),
                ('image_couverture', models.ImageField(upload_to='publicites/poufiret/', verbose_name='image')),
                ('est_active', models.BooleanField(default=True, verbose_name='active')),
                ('ordre', models.IntegerField(default=0, verbose_name='ordre')),
                ('date_debut', models.DateTimeField(blank=True, null=True, verbose_name='début')),
                ('date_fin', models.DateTimeField(blank=True, null=True, verbose_name='fin')),
                ('portee', models.CharField(choices=[('tout', 'Tout le monde'), ('region', 'Une région'),
                                                     ('departement', 'Un département')],
                                            default='tout', max_length=12, verbose_name='portée')),
                ('nb_impressions', models.PositiveIntegerField(default=0, verbose_name='affichages')),
                ('nb_clics', models.PositiveIntegerField(default=0, verbose_name='clics')),
                ('nb_personnes_touchees', models.PositiveIntegerField(default=0, verbose_name='personnes touchées')),
                ('categorie', models.ForeignKey(
                    help_text="Supprimée : la pub n'est plus diffusée.", null=True,
                    on_delete=django.db.models.deletion.SET_NULL, related_name='pubs_poufiret',
                    to='catalog.categorie', verbose_name='catégorie cible')),
                ('cree_par', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='pubs_poufiret_creees', to=settings.AUTH_USER_MODEL, verbose_name='créée par')),
                ('departement', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='pubs_poufiret', to='geo.departement', verbose_name='département')),
                ('region', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='pubs_poufiret', to='geo.region', verbose_name='région')),
            ],
            options={
                'verbose_name': 'pub Poufiret',
                'verbose_name_plural': 'pubs Poufiret',
                'ordering': ['ordre', 'cree_le'],
            },
        ),
        migrations.CreateModel(
            name='ImpressionPubPoufiret',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('cree_le', models.DateTimeField(auto_now_add=True)),
                ('modifie_le', models.DateTimeField(auto_now=True)),
                ('type_affichage', models.CharField(
                    choices=[('carrousel', 'Carrousel (accueil)'), ('interstitiel', 'Interstitiel (70-80% écran)'),
                             ('bandeau_bas', 'Bandeau bas transparent'), ('page_publicites', 'Page Publicités')],
                    default='carrousel', max_length=20, verbose_name='emplacement')),
                ('minute_session', models.PositiveIntegerField(blank=True, null=True, verbose_name='minute de session')),
                ('cliquee', models.BooleanField(default=False, verbose_name='cliquée')),
                ('pub', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name='impressions',
                    to='publicites.pubpoufiret', verbose_name='pub Poufiret')),
                ('session', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='impressions_pubs_poufiret', to='analytics.tempssessionutilisateur')),
                ('utilisateur', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='impressions_pubs_poufiret', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'impression de pub Poufiret',
                'verbose_name_plural': 'impressions de pubs Poufiret',
                'indexes': [
                    models.Index(fields=['pub', 'utilisateur'], name='imp_poufiret_pub_user_idx'),
                    models.Index(fields=['session', 'pub', 'type_affichage'], name='imp_poufiret_session_idx'),
                    models.Index(fields=['cree_le'], name='imp_poufiret_cree_le_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='EcranDecouverte',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('cree_le', models.DateTimeField(auto_now_add=True)),
                ('modifie_le', models.DateTimeField(auto_now=True)),
                ('ordre', models.IntegerField(default=0, verbose_name='ordre')),
                ('image', models.ImageField(upload_to='publicites/decouverte/', verbose_name='image')),
                ('titre', models.CharField(max_length=100, verbose_name='titre')),
                ('texte', models.CharField(blank=True, max_length=300, verbose_name='texte court')),
                ('bouton_libelle', models.CharField(blank=True, max_length=40, verbose_name='libellé du bouton')),
                ('est_actif', models.BooleanField(default=True, verbose_name='actif')),
                ('bouton_categorie', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='ecrans_decouverte', to='catalog.categorie',
                    verbose_name='catégorie du bouton')),
            ],
            options={
                'verbose_name': 'écran « Découvrir Poufiret »',
                'verbose_name_plural': 'écrans « Découvrir Poufiret »',
                'ordering': ['ordre', 'cree_le'],
            },
        ),
        migrations.CreateModel(
            name='ParametresPoufiret',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('cree_le', models.DateTimeField(auto_now_add=True)),
                ('modifie_le', models.DateTimeField(auto_now=True)),
                ('pubs_maison_actives', models.BooleanField(default=False, verbose_name='pubs Poufiret actives')),
                ('frequence_pub_maison', models.PositiveIntegerField(
                    default=3, verbose_name='fréquence (une pub Poufiret toutes les N pubs partenaires)')),
                ('duree_affichage_secondes', models.PositiveIntegerField(
                    default=5, verbose_name="durée d'affichage d'une pub Poufiret (secondes)")),
                ('parcours_actif', models.BooleanField(
                    default=False, verbose_name='parcours « Découvrir Poufiret » actif')),
                ('version_parcours', models.PositiveIntegerField(
                    default=0, help_text="Incrémentée à chaque publication : l'app remontre le parcours.",
                    verbose_name='version du parcours')),
            ],
            options={
                'verbose_name': 'paramètres Poufiret',
                'verbose_name_plural': 'paramètres Poufiret',
            },
        ),
    ]
