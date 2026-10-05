"""Correspondance type de partenaire → catégorie par défaut.

Source unique : Categorie.types_partenaire (éditable dans l'admin Django,
catalog/admin.py). Pas de table de correspondance séparée : elle
dupliquerait ce champ déjà existant.
"""
from apps.users.models import ProfilPartenaire

from .models import Categorie, PartenaireCategorie


def categories_correspondantes(type_partenaire):
    return Categorie.objects.filter(
        types_partenaire__contains=[type_partenaire], est_archivee=False,
    ).order_by('ordre', 'nom')


def appliquer_correspondance(partenaire):
    """Rattache le partenaire aux catégories qui correspondent à son type,
    sans jamais en retirer. Crée le lien principal seulement si le
    partenaire n'en a pas encore. Retourne les liens créés."""
    crees = []
    for categorie in categories_correspondantes(partenaire.type_partenaire):
        if PartenaireCategorie.objects.filter(partenaire=partenaire, categorie=categorie).exists():
            continue
        principale = not PartenaireCategorie.objects.filter(
            partenaire=partenaire, est_principale=True).exists()
        crees.append(PartenaireCategorie.objects.create(
            partenaire=partenaire, categorie=categorie, est_principale=principale))
    return crees


def categories_manquantes():
    """Partenaires dont le type a une correspondance, sans la catégorie
    correspondante. Liste de (partenaire, categorie)."""
    manquants = []
    partenaires = ProfilPartenaire.objects.filter(
        type_partenaire__in=[t for t, _ in ProfilPartenaire.TypePartenaire.choices],
    ).select_related('user').order_by('id')
    for partenaire in partenaires:
        deja = set(PartenaireCategorie.objects.filter(partenaire=partenaire)
                   .values_list('categorie_id', flat=True))
        for categorie in categories_correspondantes(partenaire.type_partenaire):
            if categorie.id not in deja:
                manquants.append((partenaire, categorie))
    return manquants
