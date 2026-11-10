"""Masquage du marqueur des données de démonstration dans les réponses API.

Les commandes de démo (ex. locations/donnees_demo_locations) écrivent
« [DEMO] Données de démonstration. » (descriptions de partenaires) ou
« [DEMO] » (descriptions d'articles) : ce marqueur sert à les retrouver et à
les supprimer (--supprimer). Il reste en base, mais n'apparaît dans AUCUNE
réponse API (publique ou admin) : nettoyer_donnees est appliquée à toute
réponse JSON par apps.core.renderers.JSONRendererSansDemo.
"""
import re

MARQUEUR = '[DEMO]'
# Espaces AVANT le marqueur retirés (pas ceux d'après : « a [DEMO] b » → « a b »).
_MOTIF = re.compile(r'[ \t]*\[DEMO\](?:[ \t]*Données de démonstration\.)?')


def nettoyer_demo(texte):
    """Retire le marqueur (et son libellé) ; « » si le champ ne contenait que lui."""
    if not isinstance(texte, str) or MARQUEUR not in texte:
        return texte
    nettoye = _MOTIF.sub('', texte)
    nettoye = re.sub(r'\n{3,}', '\n\n', nettoye)
    return nettoye.strip()


def nettoyer_donnees(donnees):
    """Même chose, récursivement, sur une réponse (dict / liste / chaînes) —
    nouvelle structure, la donnée d'origine n'est pas modifiée."""
    if isinstance(donnees, str):
        return nettoyer_demo(donnees)
    if isinstance(donnees, dict):
        return {cle: nettoyer_donnees(valeur) for cle, valeur in donnees.items()}
    if isinstance(donnees, (list, tuple)):
        return [nettoyer_donnees(valeur) for valeur in donnees]
    return donnees
