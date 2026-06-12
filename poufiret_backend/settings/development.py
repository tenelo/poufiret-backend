"""
Réglages de développement.
"""
from .base import *  # noqa

DEBUG = True

CORS_ALLOW_ALL_ORIGINS = True

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'poufiret-dev',
    }
}
