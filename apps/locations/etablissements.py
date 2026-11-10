"""Type d'établissement d'un partenaire hôtelier — règle UNIQUE (liste admin
des loueurs, liste publique des établissements, annuaire).

Hôtelier : type de sa fiche ProfilEtablissement ; sans fiche (créée à la
1re ouverture de la gestion) : la valeur par défaut que cette fiche prendra
(« hotel »). Autres partenaires : None.
"""
from django.db.models import Q

from apps.users.models import ProfilPartenaire

from .models import ProfilEtablissement

TYPE_DEFAUT = ProfilEtablissement._meta.get_field('type_etablissement').default
LIBELLES = dict(ProfilEtablissement.TypeEtablissement.choices)


def type_etablissement(partenaire):
    if partenaire.type_partenaire != ProfilPartenaire.TypePartenaire.HOTELIER:
        return None
    try:
        return partenaire.profil_etablissement.type_etablissement
    except ProfilEtablissement.DoesNotExist:
        return TYPE_DEFAUT


def champs_type_etablissement(partenaire):
    valeur = type_etablissement(partenaire)
    return {'type_etablissement': valeur, 'type_etablissement_libelle': LIBELLES.get(valeur) if valeur else None}


def q_type_etablissement(valeur, prefixe=''):
    """Q() : hôteliers dont le type d'établissement vaut `valeur` (fiche absente
    comptée comme « hotel »). Sur ProfilPartenaire, ou via `prefixe`."""
    p = prefixe
    filtre = Q(**{f'{p}profil_etablissement__type_etablissement': valeur})
    if valeur == TYPE_DEFAUT:
        filtre |= Q(**{f'{p}profil_etablissement__isnull': True})
    return Q(**{f'{p}type_partenaire': ProfilPartenaire.TypePartenaire.HOTELIER}) & filtre
