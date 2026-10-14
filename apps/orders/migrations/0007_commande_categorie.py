"""Commande.categorie (additif, nullable) + remplissage des commandes existantes.

Le panier d'origine est supprimé à la validation : la catégorie est
reconstituée, par ordre de priorité, depuis :
  1. la catégorie des articles des lignes (panier pur → une seule
     catégorie ; en cas de mélange, la plus représentée en quantité) ;
  2. la catégorie principale du partenaire (PartenaireCategorie) ;
  3. la 1re catégorie non archivée correspondant au type du partenaire
     (Categorie.types_partenaire, ordre de la grille).
Sinon la commande reste sans catégorie (null).
"""
from collections import Counter

import django.db.models.deletion
from django.db import migrations, models


def remplir_categorie(apps, schema_editor):
    Commande = apps.get_model('orders', 'Commande')
    LigneCommande = apps.get_model('orders', 'LigneCommande')
    Categorie = apps.get_model('catalog', 'Categorie')
    PartenaireCategorie = apps.get_model('catalog', 'PartenaireCategorie')

    par_commande = {}
    for commande_id, categorie_id, quantite in (
            LigneCommande.objects.filter(article__isnull=False, commande__categorie__isnull=True)
            .values_list('commande_id', 'article__categorie_id', 'quantite')):
        par_commande.setdefault(commande_id, Counter())[categorie_id] += quantite

    principales = dict(PartenaireCategorie.objects.filter(est_principale=True)
                       .values_list('partenaire_id', 'categorie_id'))
    par_type = {}
    for cat in Categorie.objects.filter(est_archivee=False).order_by('ordre', 'nom'):
        for t in cat.types_partenaire or []:
            par_type.setdefault(t, cat.id)

    a_maj = []
    for c in Commande.objects.filter(categorie__isnull=True).select_related('partenaire'):
        compteur = par_commande.get(c.id)
        if compteur:
            c.categorie_id = compteur.most_common(1)[0][0]
        else:
            c.categorie_id = (principales.get(c.partenaire_id)
                              or par_type.get(c.partenaire.type_partenaire))
        if c.categorie_id:
            a_maj.append(c)
    Commande.objects.bulk_update(a_maj, ['categorie'], batch_size=500)
    print(f'\n  Commande.categorie remplie pour {len(a_maj)} commande(s).')


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0016_locations_v2'),
        ('orders', '0006_lignecommande_ligne_menu_lignepanier_ligne_menu_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='commande',
            name='categorie',
            field=models.ForeignKey(blank=True, help_text="Catégorie du panier d'origine (panier pur partenaire + catégorie).", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='commandes', to='catalog.categorie', verbose_name='catégorie'),
        ),
        migrations.RunPython(remplir_categorie, migrations.RunPython.noop),
    ]
