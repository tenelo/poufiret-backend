"""
Configuration Django pour Poufiret.
"""
from pathlib import Path
from decouple import config, Csv

# ------------------------------------------------------------------------------
# Chemins de base
# ------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ------------------------------------------------------------------------------
# Sécurité — lues depuis le .env
# ------------------------------------------------------------------------------
SECRET_KEY = config('DJANGO_SECRET_KEY')
DEBUG = config('DJANGO_DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('DJANGO_ALLOWED_HOSTS', default='', cast=Csv())

# ------------------------------------------------------------------------------
# Applications installées
# ------------------------------------------------------------------------------
DJANGO_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',           # support PostGIS / géolocalisation
    'django.contrib.postgres',      # lookups PostgreSQL (unaccent, recherche)
]

THIRD_PARTY_APPS = [
    'rest_framework',               # API REST
    'channels',                     # WebSocket temps reel
    'corsheaders',                  # CORS pour Flutter
    'rest_framework_simplejwt.token_blacklist',  # blacklist refresh tokens
    'waffle',                       # feature flags
]

LOCAL_APPS = [
    'apps.core',                    # couche commune (modele abstrait, exceptions)
    # On ajoutera ici nos apps : users, catalog, social, orders, etc.
    'apps.users',
    'apps.catalog',
    'apps.social',
    'apps.orders',
    'apps.messaging',
    'apps.moderation',
    'apps.payments',
    'apps.notifications',
    'apps.analytics',
    'apps.publicites',
    'apps.geo',
    'apps.version',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ------------------------------------------------------------------------------
# Middleware
# ------------------------------------------------------------------------------
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',   # doit être très haut
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'waffle.middleware.WaffleMiddleware',
]

ROOT_URLCONF = 'poufiret_backend.urls'

# ------------------------------------------------------------------------------
# Templates
# ------------------------------------------------------------------------------
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'poufiret_backend.wsgi.application'

# ------------------------------------------------------------------------------
# Base de données — PostgreSQL + PostGIS
# ------------------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE': 'django.contrib.gis.db.backends.postgis',
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

# ------------------------------------------------------------------------------
# Validation des mots de passe
# ------------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ------------------------------------------------------------------------------
# Internationalisation
# ------------------------------------------------------------------------------
LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Africa/Abidjan'
USE_I18N = True
USE_TZ = True

# ------------------------------------------------------------------------------
# Fichiers statiques (CSS, JS de l'admin Django) et médias (uploads)
# ------------------------------------------------------------------------------
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ------------------------------------------------------------------------------
# CORS — pour autoriser Flutter à appeler l'API
# ------------------------------------------------------------------------------
CORS_ALLOW_ALL_ORIGINS = DEBUG    # tout permettre en dev, restreindre en prod
CORS_ALLOW_CREDENTIALS = True

# ------------------------------------------------------------------------------
# Type de clé primaire par défaut
# ------------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ------------------------------------------------------------------------------
# Modèle utilisateur personnalisé
# ------------------------------------------------------------------------------
AUTH_USER_MODEL = 'users.User'

# ------------------------------------------------------------------------------
# Django REST Framework
# ------------------------------------------------------------------------------
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'apps.core.pagination.StandardPagination',
    'PAGE_SIZE': config('API_PAGE_SIZE', default=20, cast=int),
    'DEFAULT_VERSIONING_CLASS': 'rest_framework.versioning.URLPathVersioning',
    'DEFAULT_VERSION': 'v1',
    'ALLOWED_VERSIONS': ['v1'],
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': config('THROTTLE_ANON', default='60/min'),
        'user': config('THROTTLE_USER', default='1000/min'),
    },
    'EXCEPTION_HANDLER': 'apps.core.exceptions.custom_exception_handler',
}

# ------------------------------------------------------------------------------
# SIMPLE_JWT — authentification par token (style "reste connecté")
# ------------------------------------------------------------------------------
from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=180),   # 6 mois d'inactivite max
    'ROTATE_REFRESH_TOKENS': True,                   # fenetre glissante
    'BLACKLIST_AFTER_ROTATION': True,                # invalide l'ancien refresh
    'UPDATE_LAST_LOGIN': True,                        # alimente last_login
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# ------------------------------------------------------------------------------
# Channels (WebSocket temps réel)
# ------------------------------------------------------------------------------
ASGI_APPLICATION = 'poufiret_backend.asgi.application'

REDIS_URL = config('REDIS_URL', default='redis://redis-poufiret:6379/0')

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {'hosts': [REDIS_URL]},
    }
}

# ------------------------------------------------------------------------------
# Firebase Cloud Messaging (notifications push) — inerte tant que non configuré
# ------------------------------------------------------------------------------
FIREBASE_CREDENTIALS = config('FIREBASE_CREDENTIALS', default='')
