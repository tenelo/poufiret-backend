"""Additif : bouton WhatsApp externe du partenaire (désactivé par défaut)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0024_consentements_notes_avis"),
    ]

    operations = [
        migrations.AddField(
            model_name="profilpartenaire",
            name="whatsapp_externe_actif",
            field=models.BooleanField(
                default=False,
                help_text="Affiche publiquement un bouton vers le vrai WhatsApp (champ whatsapp), "
                          "en plus de la messagerie interne.",
                verbose_name="bouton WhatsApp externe actif"),
        ),
    ]
