"""Bascule les anciens 'superviseur_livraison' au sens national (sans
département de rattachement) vers le nouveau rôle 'coordonnateur_livraison'.

Contexte : la hiérarchie livraison passe de 2 à 3 niveaux.
'superviseur_livraison' désignait jusqu'ici un niveau national (voit
toutes les villes) ; il désigne désormais le responsable d'UNE ville
(rattaché à un département, comme un gestionnaire, avec plus de droits).
Le niveau national prend le nouveau rôle 'coordonnateur_livraison'.

Critère : un User avec role='superviseur_livraison' dont le profil_livraison
existe ET a departement=None (= national) est basculé vers
'coordonnateur_livraison'. Les superviseur_livraison avec un département
restent superviseurs (sens ville, cohérent avec le nouveau modèle).
"""
from django.db import migrations


def basculer_vers_coordonnateur(apps, schema_editor):
    User = apps.get_model('users', 'User')
    ProfilLivraison = apps.get_model('livraison', 'ProfilLivraison')

    ids_nationaux = ProfilLivraison.objects.filter(
        user__role='superviseur_livraison',
        departement__isnull=True,
    ).values_list('user_id', flat=True)

    User.objects.filter(id__in=list(ids_nationaux)).update(
        role='coordonnateur_livraison')


def revenir_vers_superviseur(apps, schema_editor):
    """Best-effort : inverse exactement le critère de la migration forward."""
    User = apps.get_model('users', 'User')
    ProfilLivraison = apps.get_model('livraison', 'ProfilLivraison')

    ids_nationaux = ProfilLivraison.objects.filter(
        user__role='coordonnateur_livraison',
        departement__isnull=True,
    ).values_list('user_id', flat=True)

    User.objects.filter(id__in=list(ids_nationaux)).update(
        role='superviseur_livraison')


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0017_coordonnateur_livraison_role'),
        ('livraison', '0007_teneli_livraison_gestion'),
    ]

    operations = [
        migrations.RunPython(basculer_vers_coordonnateur, revenir_vers_superviseur),
    ]
