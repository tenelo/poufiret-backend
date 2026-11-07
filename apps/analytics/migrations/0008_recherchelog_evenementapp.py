"""Additif : journal de toutes les recherches (RechercheLog) et événements
applicatifs (EvenementApp) — écrits via apps.analytics.collecte."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

PLATEFORMES = [("android", "Android"), ("ios", "iOS"), ("web", "Web"), ("autre", "Autre")]


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0007_vueservicelivraison"),
        ("catalog", "0018_rattachement_types_gabarits"),
        ("users", "0024_consentements_notes_avis"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RechercheLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("terme", models.CharField(max_length=200, verbose_name="terme")),
                ("terme_normalise", models.CharField(help_text="Minuscules, sans accents, espaces réduits.", max_length=200, verbose_name="terme normalisé")),
                ("source", models.CharField(choices=[("accueil", "Accueil (recherche unifiée)"), ("catalogue", "Catalogue"), ("restaurants", "Restaurants / établissements"), ("locations", "Locations"), ("autre", "Autre")], default="autre", max_length=20, verbose_name="source")),
                ("nb_resultats", models.PositiveIntegerField(default=0, verbose_name="nombre de résultats")),
                ("resultat_type", models.CharField(blank=True, choices=[("article", "Article"), ("partenaire", "Partenaire")], max_length=20, null=True, verbose_name="type du résultat touché")),
                ("resultat_id", models.CharField(blank=True, max_length=64, null=True, verbose_name="id du résultat touché")),
                ("clique_le", models.DateTimeField(blank=True, null=True, verbose_name="cliqué le")),
                ("plateforme", models.CharField(choices=PLATEFORMES, default="autre", max_length=10, verbose_name="plateforme")),
                ("cree_le", models.DateTimeField(auto_now_add=True, verbose_name="créée le")),
                ("categorie", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="recherches_log", to="catalog.categorie", verbose_name="catégorie (filtre)")),
                ("utilisateur", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="recherches_log", to=settings.AUTH_USER_MODEL, verbose_name="utilisateur")),
            ],
            options={
                "verbose_name": "recherche (journal)",
                "verbose_name_plural": "recherches (journal)",
                "ordering": ["-cree_le"],
                "indexes": [
                    models.Index(fields=["terme_normalise"], name="recherchelog_terme_idx"),
                    models.Index(fields=["cree_le"], name="recherchelog_cree_le_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="EvenementApp",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("type", models.CharField(choices=[("panier_ajout", "Ajout au panier"), ("panier_retrait", "Retrait du panier"), ("panier_vide", "Panier vidé"), ("commande_creee", "Commande créée"), ("commande_annulee", "Commande annulée"), ("appel_partenaire", "Appel du partenaire"), ("whatsapp_partenaire", "WhatsApp du partenaire"), ("partage_article", "Partage d'un article"), ("partage_partenaire", "Partage d'un partenaire"), ("itineraire_partenaire", "Itinéraire vers le partenaire"), ("favori_ajout", "Ajout aux favoris"), ("favori_retrait", "Retrait des favoris")], max_length=30, verbose_name="type")),
                ("objet_type", models.CharField(blank=True, max_length=30, verbose_name="type d'objet")),
                ("objet_id", models.CharField(blank=True, max_length=64, verbose_name="id de l'objet")),
                ("valeur", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name="valeur (ex. montant)")),
                ("donnees", models.JSONField(blank=True, default=dict, verbose_name="données")),
                ("plateforme", models.CharField(choices=PLATEFORMES, default="autre", max_length=10, verbose_name="plateforme")),
                ("version_app", models.CharField(blank=True, max_length=20, verbose_name="version de l'app")),
                ("cree_le", models.DateTimeField(auto_now_add=True, verbose_name="créé le")),
                ("categorie", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="evenements_app", to="catalog.categorie", verbose_name="catégorie")),
                ("partenaire", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="evenements_app", to="users.profilpartenaire", verbose_name="partenaire")),
                ("utilisateur", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="evenements_app", to=settings.AUTH_USER_MODEL, verbose_name="utilisateur")),
            ],
            options={
                "verbose_name": "événement applicatif",
                "verbose_name_plural": "événements applicatifs",
                "ordering": ["-cree_le"],
                "indexes": [
                    models.Index(fields=["type", "cree_le"], name="evenementapp_type_idx"),
                    models.Index(fields=["partenaire", "cree_le"], name="evenementapp_partenaire_idx"),
                ],
            },
        ),
    ]
