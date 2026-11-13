"""Notifications admin en temps réel : compteurs de non lues par canal et
diffusion WebSocket (consumer NotificationsAdminConsumer, route
ws/notifications/admin/).

- compteurs_admin(user) : calcul UNIQUE des compteurs, partagé avec
  GET /notifications/admin/compteur/ (secours REST, réponse inchangée).
- diffuser_compteurs_admin(utilisateurs, nouvelle) : SEULE fonction de
  diffusion. Exécutée après validation de la transaction (on_commit) ;
  une requête agrégée pour tous les destinataires (pas une par
  notification) ; ne fait JAMAIS échouer l'action métier (erreur
  journalisée, Redis indisponible compris).
"""
import logging

from django.db import transaction
from django.db.models import Count, Q

logger = logging.getLogger('poufiret.notifications')


def groupe_admin(user_id):
    """Groupe Channels propre à un compte admin (toutes ses pages ouvertes)."""
    return f'notifications_admin_{user_id}'


def _agregats():
    from apps.moderation.models import Notification
    return {'restaurant': Count('id', filter=Q(canal=Notification.Canal.RESTAURANT)),
            'general': Count('id', filter=Q(canal=Notification.Canal.GENERAL))}


def _forme(restaurant, general):
    return {'restaurant': restaurant, 'general': general, 'nb_non_lues': restaurant + general}


def compteurs_admin(user):
    """{"restaurant": n, "general": m, "nb_non_lues": n+m} — non lues du compte,
    en une requête (agrégat filtré)."""
    from apps.moderation.models import Notification
    c = Notification.objects.filter(user=user, lu=False).aggregate(**_agregats())
    return _forme(c['restaurant'], c['general'])


def _compteurs_par_utilisateur(ids):
    """Compteurs de plusieurs comptes en UNE requête (GROUP BY user)."""
    from apps.moderation.models import Notification
    lignes = (Notification.objects.filter(user_id__in=ids, lu=False).order_by()
              .values('user_id').annotate(**_agregats()))
    par_id = {l['user_id']: _forme(l['restaurant'], l['general']) for l in lignes}
    return {i: par_id.get(i, _forme(0, 0)) for i in ids}


def _ids_admins(utilisateurs):
    """Ids des comptes admin (staff ou super-admin) parmi des User ou des ids
    (un id est supposé désigner un admin : appelants = vues admin)."""
    ids = []
    for u in utilisateurs:
        if isinstance(u, int):
            ids.append(u)
        elif u is not None and (getattr(u, 'is_staff', False) or getattr(u, 'is_superuser', False)):
            ids.append(u.pk)
    return list(dict.fromkeys(ids))


def _envoyer(ids, nouvelle):
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        couche = get_channel_layer()
        if couche is None:
            return
        for user_id, compteurs in _compteurs_par_utilisateur(ids).items():
            async_to_sync(couche.group_send)(groupe_admin(user_id), {
                'type': 'compteurs_admin',
                'payload': {'type': 'compteurs', **compteurs, 'nouvelle': bool(nouvelle)},
            })
    except Exception:
        logger.exception('Diffusion WebSocket des compteurs admin (%s compte(s)) : échec, action non bloquée.',
                         len(ids))


def diffuser_compteurs_admin(utilisateurs, nouvelle):
    """Envoie à chaque admin concerné ses compteurs à jour, après validation de
    la transaction en cours (immédiatement hors transaction).
    utilisateurs : User (les non-admins sont ignorés) ou ids de comptes admin.
    nouvelle : True après création de notification(s) (son côté Angular),
    False après lecture."""
    try:
        ids = _ids_admins(utilisateurs)
        if ids:
            transaction.on_commit(lambda: _envoyer(ids, nouvelle))
    except Exception:
        logger.exception('Diffusion WebSocket des compteurs admin : échec, action non bloquée.')
