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

_redis_url = config('REDIS_URL', default='')
if _redis_url:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': _redis_url,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'poufiret-prod',
        }
    }

CONN_MAX_AGE = config('DB_CONN_MAX_AGE', default=0, cast=int)
DATABASES['default']['CONN_MAX_AGE'] = CONN_MAX_AGE

# Sécurité HTTPS — Nginx termine le TLS et transmet X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=False, cast=bool)
SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=False, cast=bool)
CSRF_COOKIE_SECURE = config('CSRF_COOKIE_SECURE', default=False, cast=bool)
