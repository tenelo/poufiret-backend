"""Rattachement automatique (P1, Categorie.types_partenaire) des types
fast_food, boutique_mode et libraire aux catégories EXISTANTES qui leur
correspondent — aucune catégorie créée. Si aucune ne correspond, un
avertissement est affiché (à rattacher ensuite depuis l'admin des
catégories). Les partenaires déjà existants de ces types sont rattachés
comme le ferait le signal P1 (apps.catalog.correspondances)."""
import re

from django.db import migrations

# type → (motif sur le nom de catégorie, type déjà rattaché équivalent)
REGLES = {
    'fast_food': (r'fast[\s-]?food', 'restaurateur'),
    'boutique_mode': (r'\b(mode|chaussures?|v[eê]tements?|habillement|pr[eê]t[\s-]à[\s-]porter)\b', None),
    'libraire': (r'librair|papeter|\blivres?\b', None),
}


def correspond(categorie, motif, type_equivalent):
    if type_equivalent and type_equivalent in (categorie.types_partenaire or []):
        return True
    return re.search(motif, categorie.nom, re.IGNORECASE) is not None


def rattacher(apps, schema_editor):
    Categorie = apps.get_model('catalog', 'Categorie')
    PartenaireCategorie = apps.get_model('catalog', 'PartenaireCategorie')
    ProfilPartenaire = apps.get_model('users', 'ProfilPartenaire')
    categories = list(Categorie.objects.filter(est_archivee=False))
    for type_, (motif, equivalent) in REGLES.items():
        cibles = [c for c in categories if correspond(c, motif, equivalent)]
        if not cibles:
            print(f'\n  [gabarits] AUCUNE catégorie existante pour le type « {type_} » : '
                  f'à rattacher depuis l\'admin des catégories (types_partenaire).')
            continue
        for c in cibles:
            if type_ not in (c.types_partenaire or []):
                c.types_partenaire = list(c.types_partenaire or []) + [type_]
                c.save(update_fields=['types_partenaire'])
        print(f'\n  [gabarits] {type_} → {", ".join(c.nom for c in cibles)}')
        for p in ProfilPartenaire.objects.filter(type_partenaire=type_):
            for c in cibles:
                if PartenaireCategorie.objects.filter(partenaire=p, categorie=c).exists():
                    continue
                principale = not PartenaireCategorie.objects.filter(partenaire=p, est_principale=True).exists()
                PartenaireCategorie.objects.create(partenaire=p, categorie=c, est_principale=principale)


def detacher(apps, schema_editor):
    Categorie = apps.get_model('catalog', 'Categorie')
    for c in Categorie.objects.all():
        types = [t for t in (c.types_partenaire or []) if t not in ('fast_food', 'boutique_mode')]
        if types != (c.types_partenaire or []):
            c.types_partenaire = types
            c.save(update_fields=['types_partenaire'])


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0017_gabarits'),
        ('users', '0022_gabarits'),
    ]

    operations = [migrations.RunPython(rattacher, detacher)]
