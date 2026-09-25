"""
Réglages de production.
"""
from .base import *  # noqa

DEBUG = False

# WhiteNoise sert les fichiers statiques (admin) sans serveur dédié.
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

# Origines de confiance pour le CSRF (admin Django en HTTPS).
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())

# CORS restreint (sans effet sur l'app mobile : CORS ne concerne que les navigateurs).
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = config('CORS_ALLOWED_ORIGINS', default='', cast=Csv())

# Cache Redis PARTAGÉ entre les workers (throttling DRF, flags waffle...).
# Variable dédiée CACHE_REDIS_URL, distincte de REDIS_URL (Channels, base 0) :
# le cache vit dans une autre base Redis (ex. .../1). Absente => LocMemCache
# (un cache par worker), comportement d'avant.
_cache_redis_url = config('CACHE_REDIS_URL', default='')
if _cache_redis_url:
    CACHES = {
        'default': {
            'BACKEND': 'apps.core.cache.RedisCacheTolerant',
            'LOCATION': _cache_redis_url,
            'KEY_PREFIX': 'poufiret',
            'OPTIONS': {
                'socket_connect_timeout': 0.5,
                'socket_timeout': 0.5,
            },
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'poufiret-prod',
        }
    }

# Connexions PostgreSQL persistantes (0 = une connexion neuve par requête).
# DB_CONN_HEALTH_CHECKS vérifie qu'une connexion réutilisée est encore vivante.
CONN_MAX_AGE = config('DB_CONN_MAX_AGE', default=0, cast=int)
DATABASES['default']['CONN_MAX_AGE'] = CONN_MAX_AGE
DATABASES['default']['CONN_HEALTH_CHECKS'] = config(
    'DB_CONN_HEALTH_CHECKS', default=False, cast=bool)

# Sécurité HTTPS — Nginx termine le TLS et transmet X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=False, cast=bool)
SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=False, cast=bool)
CSRF_COOKIE_SECURE = config('CSRF_COOKIE_SECURE', default=False, cast=bool)
