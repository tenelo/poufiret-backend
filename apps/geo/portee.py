"""Filtre de visibilite geographique selon la portee des partenaires.

Regle : un utilisateur situe dans le departement D voit un partenaire P si
  - P est dans D, ou
  - P a portee 'region' et P est dans la meme region que D, ou
  - P a portee 'district' (visible partout).

Centralise ici pour rester coherent entre annuaire, catalogue et recherche.
"""
from django.db.models import Q


def filtre_visibilite(departement=None, localites_choisies=None):
    """Construit un Q() de visibilite pour un queryset de ProfilPartenaire.

    departement : l'objet Departement de l'utilisateur (ou None si inconnu).
    localites_choisies : liste optionnelle d'ids de departements coches par
        l'utilisateur pour elargir sa vue ('all' = tout voir).

    Choix produit : un utilisateur NON localise (anonyme, ou departement
    non renseigne, sans localite cochee) voit TOUT. On donne envie d'abord ;
    l'app invite ensuite a s'enregistrer pour une vue localisee. Le filtre
    n'a de sens qu'une fois la localisation connue.
    """
    if departement is None and not localites_choisies:
        return Q()

    if localites_choisies and 'all' in localites_choisies:
        return Q()

    # Un partenaire est TOUJOURS visible partout s'il a portee district.
    q = Q(plan__portee='district')

    # Le departement de l'utilisateur n'est pris en compte que s'il n'a
    # PAS coche de localites : un choix explicite remplace la vue par
    # defaut. Sinon, cocher "Poro" afficherait aussi son propre
    # departement, ce qui n'est pas ce que l'utilisateur demande.
    if departement is not None and not localites_choisies:
        # Meme departement : visible quel que soit le plan.
        q |= Q(departement=departement)
        # Meme region + portee au moins region.
        q |= Q(departement__region=departement.region,
               plan__portee__in=['region', 'district'])

    if localites_choisies:
        from apps.geo.models import Departement
        deps = Departement.objects.filter(
            id__in=[d for d in localites_choisies if str(d).isdigit()]
        ).select_related('region')
        for dep in deps:
            q |= Q(departement=dep)
            q |= Q(departement__region=dep.region,
                   plan__portee__in=['region', 'district'])

    return q
