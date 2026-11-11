"""Vitrine des hôtels / résidences (carrousel de la page publique) et
paramètres du module locations (singleton : nombre maximum d'images de
vitrine, 10 par défaut). Additif : aucune donnée existante modifiée."""
import uuid

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

import apps.core.images


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0022_vuearticle_date_vue_idx'),
        ('locations', '0001_locations_v2'),
    ]

    operations = [
        migrations.CreateModel(
            name='ParametresLocations',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('cree_le', models.DateTimeField(auto_now_add=True)),
                ('modifie_le', models.DateTimeField(auto_now=True)),
                ('nb_max_images_vitrine', models.PositiveSmallIntegerField(
                    default=10, validators=[django.core.validators.MinValueValidator(1)],
                    verbose_name="nombre maximum d'images de vitrine",
                    help_text="Carrousel d'un hôtel / d'une résidence. Baisser ce nombre ne supprime rien : "
                              "la page publique ne montre que les premières images.")),
            ],
            options={
                'verbose_name': 'paramètres locations',
                'verbose_name_plural': 'paramètres locations',
            },
        ),
        migrations.CreateModel(
            name='ImageVitrine',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('cree_le', models.DateTimeField(auto_now_add=True)),
                ('modifie_le', models.DateTimeField(auto_now=True)),
                ('image', models.ImageField(blank=True, upload_to='vitrines/', verbose_name='photo propre')),
                ('legende', models.CharField(blank=True, max_length=200, verbose_name='légende')),
                ('ordre', models.IntegerField(default=0, verbose_name='ordre')),
                ('etablissement', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name='images_vitrine',
                    to='locations.profiletablissement', verbose_name='établissement')),
                ('image_hebergement', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                    related_name='vitrines', to='catalog.articleimage', verbose_name="photo d'hébergement")),
            ],
            options={
                'verbose_name': 'image de vitrine',
                'verbose_name_plural': 'images de vitrine',
                'ordering': ['etablissement', 'ordre', 'cree_le'],
                'constraints': [
                    models.CheckConstraint(
                        check=(models.Q(('image_hebergement__isnull', False), ('image', ''))
                               | models.Q(('image_hebergement__isnull', True), models.Q(('image', ''), _negated=True))),
                        name='image_vitrine_une_seule_source'),
                    models.UniqueConstraint(
                        condition=models.Q(('image_hebergement__isnull', False)),
                        fields=('etablissement', 'image_hebergement'),
                        name='unique_image_hebergement_par_vitrine'),
                ],
            },
            bases=(apps.core.images.ImagesOptimiseesMixin, models.Model),
        ),
    ]
