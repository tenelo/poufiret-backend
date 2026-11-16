"""Image facultative par variante (format). Additif."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0023_categorie_max_photos_par_article'),
    ]

    operations = [
        migrations.AddField(
            model_name='variante',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to='catalogue/variantes/', verbose_name='image'),
        ),
    ]
