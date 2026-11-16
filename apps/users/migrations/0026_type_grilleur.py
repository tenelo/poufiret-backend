"""Nouveau type de partenaire « grilleur » (Grillades / Braisé). Choix seulement."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0025_whatsapp_externe_actif"),
    ]

    operations = [
        migrations.AlterField(
            model_name="profilpartenaire",
            name="type_partenaire",
            field=models.CharField(
                choices=[
                    ("commercant", "Commerçant"),
                    ("pharmacien", "Pharmacien"),
                    ("boulanger", "Boulanger"),
                    ("restaurateur", "Restaurateur"),
                    ("fast_food", "Fast-food"),
                    ("grilleur", "Grillades / Braisé"),
                    ("couturier", "Couturier / Couturière"),
                    ("menuisier", "Menuisier"),
                    ("plombier", "Plombier"),
                    ("electricien", "Électricien"),
                    ("macon", "Maçon"),
                    ("coiffeur", "Coiffeur / Coiffeuse"),
                    ("libraire", "Libraire"),
                    ("boutique_mode", "Vendeur de chaussures / Mode"),
                    ("hotelier", "Hôtelier"),
                    ("mecanicien", "Mécanicien"),
                    ("eleveur", "Éleveur / Vente à la ferme"),
                    ("loueur_maison", "Loueur de maison"),
                    ("loueur_voiture", "Loueur de voiture"),
                    ("autre", "Autre"),
                ],
                default="commercant",
                help_text="Désigne l'appellation du partenaire (commerçant, pharmacien, coiffeur, etc.).",
                max_length=20,
                verbose_name="type de partenaire",
            ),
        ),
    ]
