"""Lookup asynchrone du destinataire (point B) apres creation d'une course.

Objectif : si le numero du contact B correspond a un compte Poufiret,
lier la course a ce compte (contact_user) et notifier le destinataire.

Regles dures :
- STRICTEMENT non-bloquant : declenche via transaction.on_commit + thread
  daemon. Ni la recherche ni la notif ne doivent ralentir/faire echouer
  la creation de course.
- CONFIDENTIALITE : on ne revele JAMAIS au demandeur si le numero a un
  compte. La notif part en silence, aucun retour cote reponse creation.
- Echec silencieux : toute exception dans le thread est logguee, jamais
  propagee.
"""
import logging
import threading

from django.contrib.auth import get_user_model
from django.db import transaction

logger = logging.getLogger(__name__)
User = get_user_model()


def _variantes_numero(brut):
    """Genere les formats plausibles d'un numero pour matcher le compte.

    Les comptes sont stockes au format international (+225XXXXXXXXXX).
    Le formulaire envoie souvent 10 chiffres (0700000002). On tente donc
    plusieurs variantes, sans dupliquer.
    """
    if not brut:
        return []
    n = ''.join(c for c in brut if c.isdigit() or c == '+')
    variantes = []

    def _ajouter(v):
        if v and v not in variantes:
            variantes.append(v)

    _ajouter(n)
    # Chiffres seuls (sans +).
    chiffres = n.lstrip('+')
    _ajouter('+' + chiffres)
    # 0XXXXXXXXX (local ivoirien) -> +225XXXXXXXXXX
    if chiffres.startswith('0') and len(chiffres) == 10:
        _ajouter('+225' + chiffres)
        _ajouter('225' + chiffres)
    # 225XXXXXXXXXX -> +225XXXXXXXXXX
    if chiffres.startswith('225'):
        _ajouter('+' + chiffres)
    # +225XXXXXXXXXX -> 0XXXXXXXXX (cas inverse, robustesse)
    if chiffres.startswith('225') and len(chiffres) == 13:
        _ajouter('0' + chiffres[3:])
    return variantes


def _trouver_compte(telephone):
    """Retourne le User correspondant au numero, ou None."""
    variantes = _variantes_numero(telephone)
    if not variantes:
        return None
    return User.objects.filter(telephone__in=variantes).first()


def _executer_lookup(course_id):
    """Corps du thread : relit la course, cherche le compte, lie + notifie.
    Tourne HORS transaction/requete. Toute erreur est logguee et avalee."""
    from .models import Course
    try:
        course = Course.objects.filter(pk=course_id).first()
        if course is None:
            return
        user = _trouver_compte(course.b_telephone_contact)
        if user is None:
            return
        # Ne pas se notifier soi-meme (cas "je recois la livraison").
        if user.id == course.demandeur_id:
            return
        # Liaison (uniquement ce champ, pas de save global).
        course.contact_user = user
        course.save(update_fields=['contact_user'])
        # Notif silencieuse (inerte si flag off ou pas de token).
        _notifier(course, user)
    except Exception:
        logger.exception('Lookup destinataire echoue (course=%s)', course_id)


def _notifier(course, user):
    """Notif FCM au destinataire. Jamais bloquante, jamais fatale."""
    try:
        from apps.notifications.fcm import notifier_utilisateur
        notifier_utilisateur(
            user,
            titre='Un colis arrive pour vous',
            corps='Ouvrez pour deposer votre position et suivre la livraison.',
            data={'type': 'course_destinataire', 'course_id': str(course.id)},
        )
    except Exception:
        logger.exception('Notif destinataire echouee (course=%s)', course.id)


def programmer_lookup_destinataire(course):
    """Point d'entree appele depuis la vue de creation.

    Programme le lookup APRES le commit de la transaction courante, dans un
    thread daemon. Retour immediat : n'impacte jamais la reponse HTTP.
    """
    course_id = course.id

    def _lancer():
        t = threading.Thread(
            target=_executer_lookup, args=(course_id,), daemon=True)
        t.start()

    transaction.on_commit(_lancer)
