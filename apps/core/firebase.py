"""Initialisation partagée du SDK Firebase Admin.

Point d'entrée UNIQUE pour obtenir l'app Firebase par défaut. Réutilisé par :
- apps.notifications.fcm (push FCM, gardé par le flag waffle 'fcm_actif' en
  amont, dans notifier_utilisateur — pas ici) ;
- apps.users (vérification d'idToken Firebase Phone Auth) — l'authentification
  ne doit JAMAIS dépendre d'un réglage propre aux notifications, donc cette
  initialisation est volontairement inconditionnelle (pas de flag).

Un seul `firebase_admin.initialize_app()` doit être appelé pour l'app
'[DEFAULT]' ; centraliser l'init ici évite qu'un 2e appelant ne déclenche une
ValueError "app already exists" en réinitialisant séparément.
"""
from django.conf import settings

_app = None  # instance Firebase initialisée à la demande


def obtenir_app_firebase():
    """Initialise l'app Firebase par défaut une seule fois.
    Retourne None si FIREBASE_CREDENTIALS n'est pas configuré ou en cas
    d'erreur d'initialisation (credentials invalides, etc.)."""
    global _app
    if _app is not None:
        return _app
    cred_path = getattr(settings, 'FIREBASE_CREDENTIALS', '')
    if not cred_path:
        return None
    try:
        import firebase_admin
        from firebase_admin import credentials
        cred = credentials.Certificate(cred_path)
        _app = firebase_admin.initialize_app(cred)
        return _app
    except Exception:
        return None


def verifier_id_token(id_token):
    """Vérifie un idToken Firebase (Phone Auth) et retourne le token décodé
    (dict, contient notamment 'phone_number' au format E.164).

    Lève une exception (firebase_admin.auth.*Error ou autre) si le token est
    invalide, expiré, ou si Firebase n'est pas configuré — à catcher par
    l'appelant, jamais utilisée pour renvoyer une 500 brute au client."""
    app = obtenir_app_firebase()
    if app is None:
        raise RuntimeError('Firebase non configuré (FIREBASE_CREDENTIALS absent).')
    from firebase_admin import auth
    return auth.verify_id_token(id_token, app=app)
