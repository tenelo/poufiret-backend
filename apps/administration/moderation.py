"""Actions de modération de comptes (G5, réservées au super-admin).

Chaque action journalise une entrée dans JournalModeration (audit
obligatoire) et révoque les sessions actives de la cible quand elle perd
l'accès. Les suspensions/bannissements/suppressions douces s'appuient sur
is_active=False (levier Django qui bloque la connexion) + un contexte tracé.
"""
from django.db import transaction
from django.utils import timezone

from apps.users.models import SessionAppareil
from .models import JournalModeration


def _revoquer_sessions(cible, acteur):
    """Coupe toutes les sessions appareils actives de la cible."""
    SessionAppareil.objects.filter(user=cible, est_active=True).update(
        est_active=False,
        revoque_le=timezone.now(),
        revoque_par=acteur,
    )


def _journaliser(acteur, cible, action, motif):
    """Crée l'entrée d'audit. cible peut être None (suppression hard)."""
    JournalModeration.objects.create(
        acteur=acteur,
        cible=cible,
        cible_identifiant=getattr(cible, 'telephone', '') if cible else '',
        cible_role=getattr(cible, 'role', '') if cible else '',
        action=action,
        motif=motif or '',
    )


@transaction.atomic
def suspendre(acteur, cible, motif=''):
    """Suspension réversible : le compte ne peut plus se connecter."""
    cible.est_suspendu = True
    cible.est_banni = False
    cible.suspendu_le = timezone.now()
    cible.suspension_motif = motif or ''
    cible.is_active = False
    cible.save(update_fields=['est_suspendu', 'est_banni', 'suspendu_le',
                              'suspension_motif', 'is_active'])
    _revoquer_sessions(cible, acteur)
    _journaliser(acteur, cible, JournalModeration.Action.SUSPENDRE, motif)
    return cible


@transaction.atomic
def reactiver(acteur, cible, motif=''):
    """Lève une suspension/bannissement : le compte peut se reconnecter."""
    cible.est_suspendu = False
    cible.est_banni = False
    cible.suspendu_le = None
    cible.suspension_motif = ''
    cible.is_active = True
    cible.save(update_fields=['est_suspendu', 'est_banni', 'suspendu_le',
                              'suspension_motif', 'is_active'])
    _journaliser(acteur, cible, JournalModeration.Action.REACTIVER, motif)
    return cible


@transaction.atomic
def bannir(acteur, cible, motif=''):
    """Bannissement : suspension permanente."""
    cible.est_banni = True
    cible.est_suspendu = True
    cible.suspendu_le = timezone.now()
    cible.suspension_motif = motif or ''
    cible.is_active = False
    cible.save(update_fields=['est_banni', 'est_suspendu', 'suspendu_le',
                              'suspension_motif', 'is_active'])
    _revoquer_sessions(cible, acteur)
    _journaliser(acteur, cible, JournalModeration.Action.BANNIR, motif)
    return cible


@transaction.atomic
def supprimer_soft(acteur, cible, motif=''):
    """Suppression douce : compte désactivé et marqué supprimé, récupérable."""
    cible.est_supprime = True
    cible.supprime_le = timezone.now()
    cible.is_active = False
    cible.save(update_fields=['est_supprime', 'supprime_le', 'is_active'])
    _revoquer_sessions(cible, acteur)
    _journaliser(acteur, cible, JournalModeration.Action.SUPPRIMER_SOFT, motif)
    return cible


@transaction.atomic
def supprimer_hard(acteur, cible, motif=''):
    """Suppression DÉFINITIVE : efface le compte de la base (irréversible).

    On journalise AVANT de supprimer, en conservant l'identifiant de la
    cible en clair (la FK cible deviendra NULL, mais cible_identifiant reste).
    """
    _journaliser(acteur, cible, JournalModeration.Action.SUPPRIMER_HARD, motif)
    cible.delete()
    return None


@transaction.atomic
def restaurer(acteur, cible, motif=''):
    """Annule une suppression douce : le compte redevient utilisable.

    Ne touche PAS aux suspensions/bannissements : restaurer un compte
    supprimé le remet actif s'il n'est pas par ailleurs suspendu/banni.
    """
    cible.est_supprime = False
    cible.supprime_le = None
    # On ne réactive que si le compte n'est pas suspendu/banni par ailleurs.
    if not cible.est_suspendu and not cible.est_banni:
        cible.is_active = True
    cible.save(update_fields=['est_supprime', 'supprime_le', 'is_active'])
    _journaliser(acteur, cible, JournalModeration.Action.RESTAURER, motif)
    return cible
