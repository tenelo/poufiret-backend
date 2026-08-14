"""Notifications FCM sur les transitions de course (Bloc 4).

Applique la matrice "qui recoit quoi" a chaque changement d'etat. Tout
passe par notifier_utilisateur (facade FCM), qui est INERTE tant que le
flag 'fcm_actif' est off ou qu'il n'y a pas de token : on cable les hooks,
ils restent dormants jusqu'a activation. Jamais bloquant, jamais fatal.

Matrice :
  assignee    -> livreur                 "Nouvelle course a livrer."
  acceptee    -> demandeur               "Votre livreur a accepte, il arrive."
  colis_pris  -> demandeur + destinataire "Colis recupere, en route."
  vers_b      -> destinataire            "Le livreur arrive vers vous."
  livree      -> demandeur + destinataire "Colis livre."
  annulee     -> livreur (si assigne)    "Course annulee."
  vers_a, refusee, demandee -> aucune notif.

Le destinataire n'est notifie que s'il a un compte lie (contact_user).
"""
import logging

logger = logging.getLogger(__name__)


def _envoyer(user, titre, corps, course):
    """Notifie un compte via la facade FCM. Silencieux si user est None."""
    if user is None:
        return
    try:
        from apps.notifications.fcm import notifier_utilisateur
        notifier_utilisateur(
            user, titre=titre, corps=corps,
            data={'type': 'course_transition',
                  'course_id': str(course.id),
                  'statut': course.statut},
        )
    except Exception:
        logger.exception('Notif transition echouee (course=%s, user=%s)',
                         course.id, getattr(user, 'id', None))


def notifier_transition(course, nouveau_statut):
    """Applique la matrice de notification pour le statut atteint.
    A appeler APRES la sauvegarde du nouveau statut. Non-bloquant."""
    demandeur = course.demandeur
    destinataire = course.contact_user  # None si pas de compte lie
    livreur_user = course.livreur.user if course.livreur_id else None
    num = course.numero

    if nouveau_statut == 'assignee':
        _envoyer(livreur_user, 'Nouvelle course',
                 f'Course {num} a livrer.', course)

    elif nouveau_statut == 'acceptee':
        _envoyer(demandeur, 'Livreur en route',
                 'Votre livreur a accepte, il arrive au point de retrait.', course)

    elif nouveau_statut == 'colis_pris':
        _envoyer(demandeur, 'Colis recupere',
                 f'Le colis de la course {num} a ete recupere, il est en route.',
                 course)
        _envoyer(destinataire, 'Un colis arrive',
                 'Votre colis a ete recupere, il est en route vers vous.', course)

    elif nouveau_statut == 'vers_b':
        _envoyer(destinataire, 'Le livreur arrive',
                 'Le livreur est en route vers vous.', course)

    elif nouveau_statut == 'livree':
        _envoyer(demandeur, 'Colis livre',
                 f'La course {num} a ete livree.', course)
        _envoyer(destinataire, 'Colis livre',
                 'Votre colis a ete livre.', course)

    elif nouveau_statut == 'annulee':
        _envoyer(livreur_user, 'Course annulee',
                 f'La course {num} a ete annulee.', course)

    # vers_a, refusee, demandee : aucune notif.
