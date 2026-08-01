"""Filtre de visibilite geographique selon la portee des partenaires.

Regle : un utilisateur situe dans le departement D voit un partenaire P si
  - P est dans D, ou
  - P a portee 'region' et P est dans la meme region que D, ou
  - P a portee 'district' (visible partout).

Cette logique est centralisee ici pour rester coherente entre l'annuaire,
le catalogue et la recherche.
"""
from django.db.models import Q


def filtre_visibilite(departement=None, localites_choisies=None):
    """Construit un Q() de visibilite pour un queryset de ProfilPartenaire.

    departement : l'objet Departement de l'utilisateur (ou None si inconnu).
    localites_choisies : liste optionnelle d'ids de departements que
        l'utilisateur a explicitement coches pour elargir sa vue. Si
        'all' est present, aucun filtre (il veut tout voir).

    Sans departement ni choix, on ne filtre que sur la portee district et
    region-visible-partout serait faux : on retombe sur "tout ce qui est
    au moins district", ce qui est le comportement le plus sur pour un
    visiteur non localise.
    """
    # Un partenaire est TOUJOURS visible partout s'il a portee district.
    q = Q(plan__portee='district')

    if localites_choisies and 'all' in localites_choisies:
        return Q()  # l'utilisateur veut tout voir

    if departement is not None:
        # Meme departement : visible quel que soit le plan.
        q |= Q(departement=departement)
        # Meme region + portee au moins region.
        q |= Q(departement__region=departement.region,
               plan__portee__in=['region', 'district'])

    if localites_choisies:
        # Departements explicitement coches : on applique la meme regle
        # de portee pour chacun (un partenaire n'apparait dans une localite
        # cochee que si sa portee l'y autorise).
        from apps.geo.models import Departement
        deps = Departement.objects.filter(
            id__in=[d for d in localites_choisies if str(d).isdigit()]
        ).select_related('region')
        for dep in deps:
            q |= Q(departement=dep)
            q |= Q(departement__region=dep.region,
                   plan__portee__in=['region', 'district'])

    return q
