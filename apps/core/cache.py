"""Backend de cache Redis tolérant aux pannes.

Le cache sert au throttling DRF et aux flags waffle : si Redis est
injoignable, le RedisCache standard lève une exception et TOUTES les requêtes
tombent en 500. Ici, une panne Redis se comporte comme un cache vide
(lecture = absent, écriture ignorée) — l'API continue de répondre, sans
throttling partagé le temps de la panne.

Un disjoncteur évite de payer le délai de connexion à chaque appel : après
une erreur, Redis est ignoré pendant _PAUSE secondes (par processus).
"""
import functools
import logging
import time

from django.core.cache.backends.redis import RedisCache
from redis.exceptions import RedisError

logger = logging.getLogger('poufiret.cache')

_PAUSE = 10.0        # secondes sans retenter Redis après une erreur
_LOG_MIN = 30.0      # au plus un avertissement toutes les 30 s

_etat = {'ignore_jusqua': 0.0, 'dernier_log': 0.0}


def _en_panne(erreur):
    maintenant = time.monotonic()
    _etat['ignore_jusqua'] = maintenant + _PAUSE
    if maintenant - _etat['dernier_log'] >= _LOG_MIN:
        _etat['dernier_log'] = maintenant
        logger.warning('Cache Redis indisponible (%s) : repli sans cache '
                       'pendant %.0f s.', erreur.__class__.__name__, _PAUSE)


def _tolerant(defaut):
    """defaut : valeur de repli, ou callable(self, *args, **kwargs)."""
    def decorateur(methode):
        @functools.wraps(methode)
        def enveloppe(self, *args, **kwargs):
            repli = (lambda: defaut(self, *args, **kwargs)) if callable(defaut) \
                else (lambda: defaut)
            if time.monotonic() < _etat['ignore_jusqua']:
                return repli()
            try:
                return methode(self, *args, **kwargs)
            except RedisError as erreur:
                _en_panne(erreur)
                return repli()
        return enveloppe
    return decorateur


def _get_defaut(self, key, default=None, *args, **kwargs):
    return default


def _incr_absent(self, key, *args, **kwargs):
    # Meme contrat que Django pour une cle absente.
    raise ValueError(f"Key '{key}' not found")


class RedisCacheTolerant(RedisCache):
    add = _tolerant(False)(RedisCache.add)
    get = _tolerant(_get_defaut)(RedisCache.get)
    set = _tolerant(None)(RedisCache.set)
    touch = _tolerant(False)(RedisCache.touch)
    delete = _tolerant(False)(RedisCache.delete)
    get_many = _tolerant(lambda self, *a, **k: {})(RedisCache.get_many)
    set_many = _tolerant(lambda self, *a, **k: [])(RedisCache.set_many)
    delete_many = _tolerant(None)(RedisCache.delete_many)
    has_key = _tolerant(False)(RedisCache.has_key)
    incr = _tolerant(_incr_absent)(RedisCache.incr)
    clear = _tolerant(None)(RedisCache.clear)
