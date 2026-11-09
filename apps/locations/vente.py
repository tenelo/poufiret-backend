"""Vente des logements et véhicules (additif aux locations) : source unique
des règles, libellés, filtres et représentations « vente ».

- mode_transaction : location (défaut, tout l'existant) | vente | location_vente ;
- prix de location (Article.prix) obligatoire si location ou location_vente ;
  prix_vente obligatoire si vente ou location_vente ;
- ?mode=location|vente : une annonce location_vente apparaît dans les deux ;
- annonce vendue (vendu=True) : retirée des listes publiques, toujours visible
  du loueur et de l'admin.
"""
from django.utils import timezone

from apps.catalog.models import Logement, ModeAnnonce, Vehicule

MODES_LOCATION = (ModeAnnonce.LOCATION, ModeAnnonce.LOCATION_VENTE)
MODES_VENTE = (ModeAnnonce.VENTE, ModeAnnonce.LOCATION_VENTE)

# Vehicule.mode (champ historique du catalogue) tenu en cohérence.
MODE_HISTORIQUE_VEHICULE = {
    ModeAnnonce.LOCATION: Vehicule.Mode.LOCATION,
    ModeAnnonce.VENTE: Vehicule.Mode.VENTE,
    ModeAnnonce.LOCATION_VENTE: Vehicule.Mode.LES_DEUX,
}

LIBELLES_MODE = dict(ModeAnnonce.choices)


def filtrer_mode(qs, mode):
    """?mode=location|vente (location_vente dans les deux). Autre valeur :
    filtre ignoré (même convention que les autres filtres publics)."""
    if mode == 'location':
        return qs.filter(mode_transaction__in=MODES_LOCATION)
    if mode == 'vente':
        return qs.filter(mode_transaction__in=MODES_VENTE)
    return qs


def est_a_vendre(fiche):
    return fiche.mode_transaction in MODES_VENTE


def est_a_louer(fiche):
    return fiche.mode_transaction in MODES_LOCATION


def champs_vente(fiche):
    """Champs de vente communs (lecture : public, gestion)."""
    return {
        'mode': fiche.mode_transaction,
        'mode_libelle': fiche.get_mode_transaction_display(),
        'prix_vente': fiche.prix_vente,
        'prix_negociable': fiche.prix_negociable,
        'vendu': fiche.vendu,
        'vendu_le': fiche.vendu_le,
    }


def champs_vente_vehicule(v):
    return {
        **champs_vente(v),
        'etat': v.etat or None,
        'etat_libelle': v.get_etat_display() if v.etat else None,
        'dedouane': v.dedouane,
        'carte_grise': v.carte_grise,
        'visite_technique_valide_jusqu_au': v.visite_technique_valide_jusqu_au,
        'assurance_valide_jusqu_au': v.assurance_valide_jusqu_au,
        'nb_proprietaires': v.nb_proprietaires,
        'kilometrage': v.kilometrage,
    }


def champs_vente_logement(l):
    return {
        **champs_vente(l),
        'type_document': l.type_document or None,
        'type_document_libelle': l.get_type_document_display() if l.type_document else None,
        'surface_terrain_m2': l.surface_terrain_m2,
        'est_lotie': l.est_lotie,
    }


def erreurs_prix(mode, prix_location, prix_vente):
    """Règle des prix selon le mode : {champ: [message]} (vide si conforme)."""
    erreurs = {}
    if mode in MODES_LOCATION and prix_location is None:
        erreurs['prix'] = ['Le prix de location est obligatoire pour une annonce en location.']
    if mode in MODES_VENTE and prix_vente is None:
        erreurs['prix_vente'] = ['Le prix de vente est obligatoire pour une annonce à vendre.']
    return erreurs


def marquer_vendu(fiche, vendu, acteur_role='', acteur_nom=''):
    """Marque l'annonce vendue (vendu_le = maintenant) ou la remet en vente.
    Lève ValueError si l'annonce n'est pas à vendre."""
    if not est_a_vendre(fiche):
        raise ValueError("Cette annonce n'est pas à vendre (mode location) : "
                         "passez-la en vente ou location_vente d'abord.")
    fiche.vendu = bool(vendu)
    fiche.vendu_le = timezone.now() if fiche.vendu else None
    fiche.modifie_par_role = acteur_role
    fiche.modifie_par_nom = acteur_nom
    fiche.save(update_fields=['vendu', 'vendu_le', 'modifie_par_role', 'modifie_par_nom', 'updated_at'])
    return fiche


def meta_vente():
    """Référentiels et description des champs de vente pour les formulaires
    (affichage conditionnel : champs de vente si mode = vente ou location_vente)."""
    choix = lambda c: [{'valeur': v, 'libelle': str(l)} for v, l in c]  # noqa: E731
    condition_vente = {'champ': 'mode', 'valeurs': list(MODES_VENTE)}
    condition_location = {'champ': 'mode', 'valeurs': list(MODES_LOCATION)}
    commun = [
        {'cle': 'mode', 'libelle': 'Type d\'annonce', 'type': 'choix', 'choix': choix(ModeAnnonce.choices),
         'obligatoire': True, 'defaut': ModeAnnonce.LOCATION, 'visible_si': None},
        {'cle': 'prix', 'libelle': 'Prix de location (FCFA)', 'type': 'entier', 'choix': [],
         'obligatoire': True, 'visible_si': condition_location},
        {'cle': 'prix_vente', 'libelle': 'Prix de vente (FCFA)', 'type': 'entier', 'choix': [],
         'obligatoire': True, 'visible_si': condition_vente},
        {'cle': 'prix_negociable', 'libelle': 'Prix négociable', 'type': 'booleen', 'choix': [],
         'obligatoire': False, 'defaut': True, 'visible_si': condition_vente},
    ]
    vehicule = commun + [
        {'cle': 'etat', 'libelle': 'État', 'type': 'choix',
         'choix': choix(Vehicule.EtatVehicule.choices), 'obligatoire': False, 'visible_si': condition_vente},
        {'cle': 'kilometrage', 'libelle': 'Kilométrage', 'type': 'entier', 'choix': [],
         'obligatoire': False, 'visible_si': condition_vente},
        {'cle': 'dedouane', 'libelle': 'Dédouané', 'type': 'booleen', 'choix': [],
         'obligatoire': False, 'visible_si': condition_vente},
        {'cle': 'carte_grise', 'libelle': 'Carte grise disponible', 'type': 'booleen', 'choix': [],
         'obligatoire': False, 'visible_si': condition_vente},
        {'cle': 'visite_technique_valide_jusqu_au', 'libelle': "Visite technique valide jusqu'au",
         'type': 'date', 'choix': [], 'obligatoire': False, 'visible_si': condition_vente},
        {'cle': 'assurance_valide_jusqu_au', 'libelle': "Assurance valide jusqu'au",
         'type': 'date', 'choix': [], 'obligatoire': False, 'visible_si': condition_vente},
        {'cle': 'nb_proprietaires', 'libelle': 'Nombre de propriétaires précédents', 'type': 'entier',
         'choix': [], 'obligatoire': False, 'visible_si': condition_vente},
    ]
    logement = commun + [
        {'cle': 'type_document', 'libelle': 'Document de propriété', 'type': 'choix',
         'choix': choix(Logement.TypeDocument.choices), 'obligatoire': False, 'visible_si': condition_vente},
        {'cle': 'surface_terrain_m2', 'libelle': 'Surface du terrain (m²)', 'type': 'entier', 'choix': [],
         'obligatoire': False, 'visible_si': condition_vente},
        {'cle': 'est_lotie', 'libelle': 'Parcelle lotie', 'type': 'booleen', 'choix': [],
         'obligatoire': False, 'visible_si': condition_vente},
    ]
    return {
        'modes': choix(ModeAnnonce.choices),
        'etats_vehicule': choix(Vehicule.EtatVehicule.choices),
        'types_document': choix(Logement.TypeDocument.choices),
        'champs_vente': {'vehicule': vehicule, 'logement': logement},
    }
