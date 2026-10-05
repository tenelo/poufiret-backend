"""Rapprochement des villes/quartiers texte existants avec la géographie.

Classement d'un partenaire non encore rapproché :
- « exact » : ville texte = une seule localité du même département (normalisée),
  et quartier texte vide ou = un seul quartier de cette localité ;
- « proposition » : une localité exacte sans quartier exact, ou des
  propositions de similarité ≥ SEUIL ;
- « aucun » : rien de comparable.
"""
import difflib
import re
import unicodedata

from .coherence import verifier_coherence
from .models import Localite, Quartier

SEUIL = 0.85
MAX_PROPOSITIONS = 3


def normaliser(texte):
    t = unicodedata.normalize('NFKD', texte or '').encode('ascii', 'ignore').decode()
    return re.sub(r'[\s\-_’\']+', ' ', t.lower()).strip()


def _similarite(a, b):
    return difflib.SequenceMatcher(None, normaliser(a), normaliser(b)).ratio()


def _proposer(texte, candidats):
    scores = [(c, _similarite(texte, c.nom)) for c in candidats]
    retenus = sorted((x for x in scores if x[1] >= SEUIL), key=lambda x: -x[1])[:MAX_PROPOSITIONS]
    return [{'id': c.id, 'nom': c.nom, 'score': round(s, 2)} for c, s in retenus]


def _unique_exact(texte, candidats):
    cible = normaliser(texte)
    if not cible:
        return None
    matches = [c for c in candidats if normaliser(c.nom) == cible]
    return matches[0] if len(matches) == 1 else None


def analyser(profil):
    ville = (profil.ville or '').strip()
    quartier_txt = (profil.quartier or '').strip()
    localites = (list(Localite.objects.filter(departement_id=profil.departement_id, est_actif=True))
                 if profil.departement_id else [])

    exact_loc = _unique_exact(ville, localites)
    loc_props = _proposer(ville, localites) if ville and exact_loc is None else []

    exact_q = None
    quartier_props = []
    if quartier_txt:
        if exact_loc is not None:
            candidats_q = list(Quartier.objects.filter(localite=exact_loc, est_actif=True))
        else:
            candidats_q = list(Quartier.objects.filter(localite__in=localites, est_actif=True))
        exact_q = _unique_exact(quartier_txt, candidats_q) if exact_loc is not None else None
        if exact_q is None:
            quartier_props = _proposer(quartier_txt, candidats_q)

    if exact_loc is not None and (not quartier_txt or exact_q is not None):
        statut = 'exact'
    elif exact_loc is not None or loc_props or quartier_props:
        statut = 'proposition'
    else:
        statut = 'aucun'

    return {
        'partenaire_id': profil.id,
        'nom': profil.nom_commerce,
        'departement_id': profil.departement_id,
        'departement_nom': profil.departement.nom if profil.departement_id else '',
        'ville_texte': profil.ville,
        'quartier_texte': profil.quartier,
        'localite': {'id': exact_loc.id, 'nom': exact_loc.nom} if exact_loc else None,
        'quartier': {'id': exact_q.id, 'nom': exact_q.nom} if exact_q else None,
        'statut': statut,
        'propositions': {'localites': loc_props, 'quartiers': quartier_props},
    }


def lignes_a_traiter(profils):
    """(lignes d'analyse des partenaires non rapprochés, nombre de rapprochés)."""
    lignes, rapproches = [], 0
    for p in profils:
        if p.localite_id:
            rapproches += 1
        else:
            lignes.append(analyser(p))
    return lignes, rapproches


def compteurs(lignes, rapproches):
    cpt = {'exact': 0, 'proposition': 0, 'aucun': 0, 'rapproches': rapproches}
    for ligne in lignes:
        cpt[ligne['statut']] += 1
    return cpt


def appliquer(profil, localite, quartier, acteur=None, motif=''):
    """Écrit localite/quartier (même règle de cohérence que partout), met à
    jour les textes par save(), journalise. Retourne {} ou les erreurs."""
    erreurs = verifier_coherence(profil.departement if profil.departement_id else localite.departement
                                 if localite else None, localite, quartier)
    if erreurs:
        return erreurs
    from apps.administration.moderation import _journaliser
    from apps.administration.models import JournalModeration
    avant = f'{profil.ville} / {profil.quartier}'
    if profil.departement_id is None and localite is not None:
        profil.departement = localite.departement
    profil.localite = localite
    profil.quartier_geo = quartier
    profil.save()
    cible = f'{localite.nom}' + (f' / {quartier.nom}' if quartier else '')
    _journaliser(acteur, profil.user, JournalModeration.Action.GEO_RAPPROCHEMENT_PARTENAIRE,
                 f'{avant} → {cible}' + (f' — {motif}' if motif else ''))
    return {}
