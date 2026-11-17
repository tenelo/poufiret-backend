"""Canal et cible des notifications admin (trois cloches : Restaurants /
Services / Autres).

canal_notification(type_notif, data, commande) : SEUL endroit qui décide
du canal, utilisé (via champs_canal) par les 5 points d'émission
(apps.orders, apps.reservations, apps.messaging, apps.publicites,
apps.administration.views_telephone) et par la migration moderation.0008.

Règle :
- "restaurant" : commande_nouvelle / commande_annulee_client d'une commande
  de restauration (TYPES_RESTAURATION : restaurateur, fast_food, grilleur)
  OU de boulanger — par le type du partenaire ou la catégorie ;
- "service" : demandes d'intervention et demandes de réservation (hôtels,
  résidences, maisons, véhicules) ;
- "general" (libellé « Autres ») : tout le reste (commandes des autres
  partenaires, pubs, changement de numéro…).
Ce classement ne concerne QUE le canal : TYPES_RESTAURATION, le contrôle
d'ouverture au panier et ?restauration=1 ne changent pas.

canal_de(...) : règle d'origine à deux canaux, figée pour la migration
moderation.0007 (ne plus l'utiliser à l'émission).
"""

CANAL_RESTAURANT = 'restaurant'
CANAL_SERVICE = 'service'
CANAL_GENERAL = 'general'

TYPES_COMMANDE_RESTAURANT = ('commande_nouvelle', 'commande_annulee_client')

# Types partenaire dont les commandes vont aussi dans la cloche
# Restaurants, en plus de TYPES_RESTAURATION (canal uniquement).
TYPES_CANAL_RESTAURANT_EN_PLUS = ('boulanger',)

# Cloche Services : par type de notification, ou par clé de data.
TYPES_SERVICE = ('reservation_nouvelle', 'intervention_nouvelle',
                 'demande_intervention', 'intervention_acceptee')
CLES_SERVICE = ('intervention_id', 'demande_id')

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
    """Règle d'origine (restaurant / general), figée pour la migration
    moderation.0007. À l'émission : canal_notification."""
    if type_notif in TYPES_COMMANDE_RESTAURANT and est_restaurant:
        return CANAL_RESTAURANT
    return CANAL_GENERAL


def est_service(type_notif, data=None):
    """Demande d'intervention ou de réservation (type ou clé de data)."""
    data = data or {}
    return type_notif in TYPES_SERVICE or any(data.get(c) not in (None, '') for c in CLES_SERVICE)


def canal_notification(type_notif, data=None, commande=None, est_restaurant=None):
    """SEUL endroit qui décide du canal d'une notification admin.
    commande : la Commande concernée (classement Restaurants) ;
    est_restaurant : booléen déjà calculé (migration de données)."""
    if type_notif in TYPES_COMMANDE_RESTAURANT:
        if est_restaurant is None:
            est_restaurant = commande is not None and commande_canal_restaurant(commande)
        return CANAL_RESTAURANT if est_restaurant else CANAL_GENERAL
    if est_service(type_notif, data):
        return CANAL_SERVICE
    return CANAL_GENERAL


def types_canal_restaurant():
    """TYPES_RESTAURATION + boulanger (canal de notification uniquement)."""
    from apps.restaurants.services import TYPES_RESTAURATION
    return {str(t) for t in TYPES_RESTAURATION} | set(TYPES_CANAL_RESTAURANT_EN_PLUS)


def _commande_de_types(commande, types):
    if commande.partenaire.type_partenaire in types:
        return True
    categorie = commande.categorie
    return bool(categorie and types & set(categorie.types_partenaire or []))


def commande_est_restaurant(commande):
    """Commande.categorie de restauration (Categorie.types_partenaire), ou
    partenaire d'un type de restauration (TYPES_RESTAURATION). Inchangé :
    boulangers exclus."""
    from apps.restaurants.services import TYPES_RESTAURATION
    return _commande_de_types(commande, {str(t) for t in TYPES_RESTAURATION})


def commande_canal_restaurant(commande):
    """Commande classée dans la cloche Restaurants : restauration OU
    boulanger (type du partenaire ou catégorie)."""
    return _commande_de_types(commande, types_canal_restaurant())


def champs_canal(type_notif, data, commande=None):
    """kwargs {canal, cible} à passer à Notification(...)."""
    return {'canal': canal_notification(type_notif, data, commande=commande),
            'cible': cible_depuis_data(data)}
