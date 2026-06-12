"""
Sélecteur d'environnement.
Charge development.py ou production.py selon DJANGO_ENV (.env).
Défaut : development (choix sûr — jamais de prod par accident).
"""
from decouple import config

_env = config('DJANGO_ENV', default='development')

if _env == 'production':
    from .production import *  # noqa
else:
    from .development import *  # noqa
