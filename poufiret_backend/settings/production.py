"""
Réglages de production.
"""
from .base import *  # noqa

DEBUG = False

# CORS restreint aux origines explicitement autorisées (lues depuis .env)
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = config('CORS_ALLOWED_ORIGINS', default='', cast=Csv())

# Cache switchable par env. Par défaut LocMem (inerte, sans dépendance) ;
# le jour où on lance Redis, il suffit de définir REDIS_URL dans .env.
# COUTURE : aucun changement de code applicatif, juste une variable d'env.
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

# Durée de connexion DB persistante, pilotée par env (0 = comportement actuel).
# COUTURE : prépare PgBouncer/scaling sans toucher au code.
CONN_MAX_AGE = config('DB_CONN_MAX_AGE', default=0, cast=int)
DATABASES['default']['CONN_MAX_AGE'] = CONN_MAX_AGE

# Sécurité HTTPS — activable par env quand Nginx/TLS sera en place (Phase 3).
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=False, cast=bool)
SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=False, cast=bool)
CSRF_COOKIE_SECURE = config('CSRF_COOKIE_SECURE', default=False, cast=bool)
