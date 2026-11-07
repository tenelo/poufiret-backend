"""Collecte pour analyses / IA : point d'écriture UNIQUE de RechercheLog et
EvenementApp.

Règles communes :
- consentement : l'utilisateur n'est rattaché que s'il a accepté les
  statistiques (User.consentement_statistiques) ; sinon la ligne est
  enregistrée sans utilisateur (anonyme) ;
- best-effort : toute erreur est journalisée (log) et avalée — la collecte ne
  fait JAMAIS échouer l'action principale (ajout au panier, commande…) ;
- plateforme / version : en-têtes X-Plateforme (android | ios | web | autre)
  et X-Version-App envoyés par les clients (absents → « autre » / vide).
"""
import logging
import re
import unicodedata

from django.db import transaction

logger = logging.getLogger(__name__)

LONGUEUR_MIN_TERME = 2

# Types que le client (mobile / web) peut envoyer lui-même ; les autres sont
# produits par le serveur uniquement (pas de falsification possible).
TYPES_EVENEMENTS_CLIENT = (
    'appel_partenaire', 'whatsapp_partenaire', 'partage_article',
    'partage_partenaire', 'itineraire_partenaire',
)


def normaliser_terme(terme):
    """Minuscules, sans accents, espaces réduits : « Café  Crème » → « cafe creme »."""
    sans_accents = ''.join(c for c in unicodedata.normalize('NFKD', terme or '')
                           if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', sans_accents).strip().lower()


def plateforme_de(request, valeur=None):
    from .models import Plateforme
    brut = (valeur or (request.META.get('HTTP_X_PLATEFORME', '') if request is not None else '')).lower()
    return brut if brut in Plateforme.values else Plateforme.AUTRE


def version_app_de(request, valeur=None):
    brut = valeur or (request.META.get('HTTP_X_VERSION_APP', '') if request is not None else '')
    return str(brut)[:20]


def utilisateur_collecte(user):
    """L'utilisateur à rattacher à une ligne de collecte, ou None (anonyme) :
    non connecté, ou sans consentement aux statistiques."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return None
    return user if getattr(user, 'consentement_statistiques', False) else None


def journaliser_recherche(request, terme, source, nb_resultats, categorie_id=None):
    """Crée une ligne RechercheLog ; renvoie son id, ou None (terme < 2
    caractères, ou échec d'écriture — jamais d'exception)."""
    terme = (terme or '').strip()
    if len(terme) < LONGUEUR_MIN_TERME:
        return None
    try:
        from .models import RechercheLog
        with transaction.atomic():
            ligne = RechercheLog.objects.create(
                terme=terme[:200], terme_normalise=normaliser_terme(terme)[:200],
                utilisateur=utilisateur_collecte(getattr(request, 'user', None)),
                categorie_id=categorie_id, source=source,
                nb_resultats=max(int(nb_resultats or 0), 0),
                plateforme=plateforme_de(request))
        return ligne.id
    except Exception:
        logger.exception('Collecte : journal de recherche « %s » non enregistré.', terme)
        return None


def ajouter_recherche_id(reponse, recherche_id):
    """Ajoute recherche_id à une réponse sans casser son format : à la racine
    si c'est un objet JSON (dont les listes paginées), sinon en en-tête
    X-Recherche-Id. Rien si la recherche n'a pas été journalisée."""
    if recherche_id is None:
        return reponse
    if isinstance(reponse.data, dict):
        reponse.data['recherche_id'] = recherche_id
    else:
        reponse['X-Recherche-Id'] = str(recherche_id)
    return reponse


def enregistrer_evenement(type_evenement, *, request=None, utilisateur=None, partenaire=None,
                          objet_type='', objet_id='', categorie=None, valeur=None, donnees=None,
                          plateforme=None, version_app=None):
    """Crée un EvenementApp. N'échoue JAMAIS : toute erreur est loguée et avalée
    (savepoint : une erreur SQL n'invalide pas la transaction de l'appelant)."""
    try:
        from .models import EvenementApp
        if utilisateur is None and request is not None:
            utilisateur = getattr(request, 'user', None)
        with transaction.atomic():
            evenement = EvenementApp.objects.create(
                type=type_evenement,
                utilisateur=utilisateur_collecte(utilisateur),
                partenaire=partenaire,
                objet_type=objet_type or '', objet_id=str(objet_id) if objet_id not in (None, '') else '',
                categorie=categorie, valeur=valeur, donnees=donnees or {},
                plateforme=plateforme_de(request, plateforme),
                version_app=version_app_de(request, version_app))
        return evenement
    except Exception:
        logger.exception('Collecte : événement %s non enregistré (action non bloquée).', type_evenement)
        return None
