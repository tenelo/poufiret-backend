"""Additif : avis clients (note 1-5 + commentaire) sur commande, course,
intervention ou réservation."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("social", "0002_initial"),
        ("users", "0024_consentements_notes_avis"),
        ("livreurs", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Avis",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("objet_type", models.CharField(choices=[("commande", "Commande"), ("course", "Course (livraison)"), ("intervention", "Demande d'intervention"), ("reservation", "Réservation (location)")], max_length=20, verbose_name="type d'objet")),
                ("objet_id", models.CharField(help_text="Entier (commande, intervention, réservation) ou UUID (course).", max_length=64, verbose_name="id de l'objet")),
                ("note", models.PositiveSmallIntegerField(verbose_name="note (1 à 5)")),
                ("commentaire", models.TextField(blank=True, max_length=1000, verbose_name="commentaire")),
                ("est_visible", models.BooleanField(default=True, verbose_name="visible")),
                ("reponse_partenaire", models.TextField(blank=True, max_length=1000, null=True, verbose_name="réponse du partenaire")),
                ("repondu_le", models.DateTimeField(blank=True, null=True, verbose_name="répondu le")),
                ("cree_le", models.DateTimeField(auto_now_add=True, verbose_name="créé le")),
                ("modifie_le", models.DateTimeField(auto_now=True, verbose_name="modifié le")),
                ("auteur", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="avis_donnes", to=settings.AUTH_USER_MODEL, verbose_name="auteur")),
                ("livreur", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="avis", to="livreurs.livreur", verbose_name="livreur (courses)")),
                ("partenaire", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="avis", to="users.profilpartenaire", verbose_name="partenaire noté")),
            ],
            options={
                "verbose_name": "avis",
                "verbose_name_plural": "avis",
                "ordering": ["-cree_le"],
                "indexes": [models.Index(fields=["partenaire", "est_visible", "-cree_le"], name="avis_partenaire_idx")],
                "constraints": [
                    models.UniqueConstraint(fields=("auteur", "objet_type", "objet_id"), name="unique_avis_par_objet"),
                    models.CheckConstraint(check=models.Q(("note__gte", 1), ("note__lte", 5)), name="avis_note_1_a_5"),
                ],
            },
        ),
    ]
