"""Cohérence géographique d'un partenaire : localité du département, quartier
de la localité. Source de la règle 400 pour toutes les écritures."""


def verifier_coherence(departement, localite, quartier):
    """Retourne {champ: [message]} ; vide si la combinaison est cohérente."""
    erreurs = {}
    if localite is not None and departement is not None and localite.departement_id != departement.id:
        erreurs['localite_id'] = ["La localité n'appartient pas au département du partenaire."]
    if quartier is not None:
        if localite is None:
            erreurs['quartier_id'] = ["Choisissez d'abord une localité."]
        elif quartier.localite_id != localite.id:
            erreurs['quartier_id'] = ["Le quartier n'appartient pas à la localité choisie."]
    return erreurs
