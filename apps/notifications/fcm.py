"""Service d'envoi de notifications push via Firebase Cloud Messaging.
Inerte tant que le flag waffle 'fcm_actif' est off OU que la clé n'est pas configurée.
Le jour de l'activation : poser FIREBASE_CREDENTIALS (chemin du JSON) dans .env + activer le flag.
"""


def _init():
    """Initialise Firebase (délègue à apps.core.firebase, source unique
    d'initialisation du SDK — partagée avec la vérification d'idToken côté
    auth). Retourne None si pas de clé configurée."""
    from apps.core.firebase import obtenir_app_firebase
    return obtenir_app_firebase()


def envoyer_notification(token_fcm, titre, corps, data=None):
    """Envoie une notification à un appareil. Retourne (succès: bool, info: str).
    Silencieux et sans effet si FCM non configuré — ne lève jamais d'exception bloquante."""
    if not token_fcm:
        return False, 'token absent'
    app = _init()
    if app is None:
        return False, 'fcm non configure'
    try:
        from firebase_admin import messaging
        msg = messaging.Message(
            notification=messaging.Notification(title=titre, body=corps),
            data={k: str(v) for k, v in (data or {}).items()},
            token=token_fcm,
        )
        resp = messaging.send(msg)
        return True, resp
    except Exception as e:
        return False, str(e)


def notifier_utilisateur(user, titre, corps, data=None, request=None):
    """Notifie un utilisateur si le flag 'fcm_actif' est on et qu'il a un token.
    Point d'entrée à appeler depuis les autres modules (chat, commandes, etc.)."""
    from waffle import flag_is_active
    base = getattr(request, '_request', request) if request else None
    actif = flag_is_active(base, 'fcm_actif') if base else _flag_global('fcm_actif')
    if not actif:
        return False, 'flag off'
    return envoyer_notification(user.token_fcm, titre, corps, data)


def _flag_global(nom):
    """Évalue un flag waffle hors requête HTTP (ex: appel depuis un consumer WS)."""
    try:
        from waffle.models import Flag
        f = Flag.objects.filter(name=nom).first()
        return bool(f and f.everyone)
    except Exception:
        return False
