"""Web Push (VAPID, pywebpush) vers l'admin web Angular (PWA ngsw) : vraies
notifications système (bannière + son), même onglet gelé ou fermé.

- envoyer_push_web(utilisateurs, titre, corps, data, canal, avec_compteurs) :
  SEUL point d'envoi. Planifié après validation de la transaction
  (on_commit) ; lecture des abonnements dans le thread appelant, envoi
  réseau dans un pool de 4 threads (5 s max, TTL 1 jour). Ne fait JAMAIS
  échouer l'action métier (erreurs journalisées).
- Inactif tant que le flag waffle « push_web_actif » est éteint OU qu'une
  clé VAPID manque (VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT).
- Payload au format ngsw ({"notification": {...}}) : tag par canal
  (une bannière remplace la précédente), renotify, clic -> URL unique
  /notifications/ouvrir?ecran=<ecran>&id=<id> (cible déjà calculée).
- Nettoyage : 404 / 410 -> abonnement supprimé ; MAX_ECHECS échecs
  consécutifs -> supprimé ; un succès remet le compteur à 0.
"""
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

from django.conf import settings
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from .canaux import CANAL_GENERAL, cible_depuis_data

logger = logging.getLogger('poufiret.notifications')

FLAG = 'push_web_actif'
TTL_SECONDES = 24 * 3600
DELAI_SECONDES = 5
URL_OUVRIR = '/notifications/ouvrir'
ICONE_DEFAUT = '/assets/icons/icon-192x192.png'
_PREFIXE_THREAD = 'push-web'
_executeur = ThreadPoolExecutor(max_workers=4, thread_name_prefix=_PREFIXE_THREAD)


# ── Configuration ───────────────────────────────────────────────────────

def cles_vapid():
    """(publique, privée, sujet) depuis les réglages (.env), chaînes vides
    si absentes."""
    return (getattr(settings, 'VAPID_PUBLIC_KEY', '') or '',
            getattr(settings, 'VAPID_PRIVATE_KEY', '') or '',
            getattr(settings, 'VAPID_SUBJECT', '') or '')


def _flag_global(nom):
    """Flag waffle évalué hors requête (thread, on_commit)."""
    try:
        from waffle.models import Flag
        f = Flag.objects.filter(name=nom).first()
        return bool(f and f.everyone)
    except Exception:
        return False


def est_actif():
    """Vrai si les 3 clés VAPID sont présentes ET le flag est actif."""
    return all(cles_vapid()) and _flag_global(FLAG)


# ── Contenu ─────────────────────────────────────────────────────────────

def url_ouverture(data):
    """/notifications/ouvrir?ecran=<ecran>&id=<id> (cible déduite de data),
    ou /notifications/ouvrir sans cible."""
    cible = cible_depuis_data(data)
    if not cible:
        return URL_OUVRIR
    return f"{URL_OUVRIR}?{urlencode({'ecran': cible['ecran'], 'id': cible['id']})}"


def construire_payload(titre, corps, data=None, canal=None, nb_non_lues=None):
    """Payload ngsw. nb_non_lues > 1 (non lues du canal, admins) : texte
    « n nouvelles notifications (dernière : …) »."""
    url = url_ouverture(data)
    texte = corps if not nb_non_lues or nb_non_lues <= 1 else \
        f'{nb_non_lues} nouvelles notifications (dernière : {corps})'
    return {'notification': {
        'title': titre,
        'body': texte,
        'icon': getattr(settings, 'PUSH_WEB_ICONE', '') or ICONE_DEFAUT,
        'tag': canal or CANAL_GENERAL,
        'renotify': True,
        'data': {
            'url': url,
            'onActionClick': {'default': {'operation': 'navigateLastFocusedOrOpen', 'url': url}},
        },
    }}


# ── Envoi ───────────────────────────────────────────────────────────────

def envoyer_push_web(utilisateurs, titre, corps, data=None, canal=None, avec_compteurs=False):
    """Planifie l'envoi aux abonnements des utilisateurs (User ou ids), après
    validation de la transaction. avec_compteurs : texte regroupé selon les
    non lues du canal (notifications admin). Sans effet si inactif."""
    try:
        if not est_actif():
            return
        ids = list(dict.fromkeys(getattr(u, 'pk', u) for u in utilisateurs if u is not None))
        if ids:
            transaction.on_commit(lambda: _preparer(ids, titre, corps, dict(data or {}), canal, avec_compteurs))
    except Exception:
        logger.exception('Push web : planification impossible, action non bloquée.')


def _preparer(ids, titre, corps, data, canal, avec_compteurs):
    """Thread appelant : lit les abonnements (et les compteurs), construit
    un payload par compte puis confie chaque envoi réseau au pool."""
    try:
        from .models import AbonnementPushWeb
        abonnements = list(AbonnementPushWeb.objects.filter(user_id__in=ids)
                           .values('id', 'user_id', 'endpoint', 'p256dh', 'auth'))
        if not abonnements:
            return
        compteurs = {}
        if avec_compteurs:
            from .temps_reel import _compteurs_par_utilisateur
            compteurs = _compteurs_par_utilisateur(ids)
        tag = canal or CANAL_GENERAL
        for a in abonnements:
            nb = compteurs.get(a['user_id'], {}).get(tag) if avec_compteurs else None
            _executeur.submit(_envoyer_un, a, construire_payload(titre, corps, data, tag, nb))
    except Exception:
        logger.exception('Push web : préparation de l envoi impossible, action non bloquée.')


def _webpush(abonnement, payload):
    """Appel réseau (pywebpush), isolé pour être simulé dans les tests."""
    from pywebpush import webpush
    _publique, privee, sujet = cles_vapid()
    webpush(
        subscription_info={'endpoint': abonnement['endpoint'],
                           'keys': {'p256dh': abonnement['p256dh'], 'auth': abonnement['auth']}},
        data=json.dumps(payload, ensure_ascii=False),
        vapid_private_key=privee, vapid_claims={'sub': sujet},
        ttl=TTL_SECONDES, timeout=DELAI_SECONDES,
    )


def _envoyer_un(abonnement, payload):
    """Envoie à un abonnement et met à jour son état. 404 / 410 : supprimé ;
    autre échec : +1, supprimé à MAX_ECHECS. Jamais d'exception remontée."""
    from .models import AbonnementPushWeb
    qs = AbonnementPushWeb.objects.filter(pk=abonnement['id'])
    try:
        _webpush(abonnement, payload)
        qs.update(dernier_envoi_ok=timezone.now(), nb_echecs=0)
    except Exception as e:
        try:
            code = getattr(getattr(e, 'response', None), 'status_code', None)
            if code in (404, 410):
                qs.delete()
                logger.info('Push web : abonnement %s expiré (%s), supprimé.', abonnement['id'], code)
            else:
                qs.update(nb_echecs=F('nb_echecs') + 1)
                qs.filter(nb_echecs__gte=AbonnementPushWeb.MAX_ECHECS).delete()
                logger.warning('Push web : échec abonnement %s (%s) : %s', abonnement['id'], code, e)
        except Exception:
            logger.exception('Push web : mise à jour de l abonnement %s impossible.', abonnement['id'])
    finally:
        # Threads du pool : rendre la connexion à la base (jamais dans le
        # thread de la requête, qui peut être dans une transaction).
        if threading.current_thread().name.startswith(_PREFIXE_THREAD):
            connection.close()
