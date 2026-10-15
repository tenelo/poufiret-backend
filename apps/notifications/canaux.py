"""Canal et cible des notifications admin (centre restaurant / général).

Calcul unique, utilisé à l'émission (apps.orders, apps.publicites,
apps.reservations, apps.messaging) ET par la migration de données
moderation.0007 — d'où des fonctions pures, sans import de modèle.

Règle : commande_nouvelle / commande_annulee_client d'une commande de
restauration → "restaurant" ; tout le reste → "general".
"""

CANAL_RESTAURANT = 'restaurant'
CANAL_GENERAL = 'general'

TYPES_COMMANDE_RESTAURANT = ('commande_nouvelle', 'commande_annulee_client')

# Clé de `data` → écran Angular du deep-linking.
_ECRANS = (
    ('commande_id', 'commandes'),
    ('intervention_id', 'interventions'),
    ('demande_id', 'demandes_location'),
    ('publicite_id', 'publicites'),
)


def cible_depuis_data(data):
    """{"ecran", "id"} déduit des clés de deep-linking de `data`, ou None."""
    data = data or {}
    for cle, ecran in _ECRANS:
        if data.get(cle) not in (None, ''):
            return {'ecran': ecran, 'id': data[cle]}
    return None


def canal_de(type_notif, est_restaurant):
    """est_restaurant : la commande concernée relève de la restauration."""
    if type_notif in TYPES_COMMANDE_RESTAURANT and est_restaurant:
        return CANAL_RESTAURANT
    return CANAL_GENERAL


def commande_est_restaurant(commande):
    """Commande.categorie de restauration (Categorie.types_partenaire), ou
    partenaire d'un type de restauration (TYPES_RESTAURATION)."""
    from apps.restaurants.services import TYPES_RESTAURATION
    types = {str(t) for t in TYPES_RESTAURATION}
    if commande.partenaire.type_partenaire in types:
        return True
    categorie = commande.categorie
    return bool(categorie and types & set(categorie.types_partenaire or []))


def champs_canal(type_notif, data, commande=None):
    """kwargs {canal, cible} à passer à Notification(...)."""
    est_restaurant = commande is not None and commande_est_restaurant(commande)
    return {'canal': canal_de(type_notif, est_restaurant), 'cible': cible_depuis_data(data)}
