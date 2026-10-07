"""Services de l'app reservations : machine d'état des demandes (source
unique, partagée par le client, le loueur et l'admin — mode parallèle à
apps.orders.services), et notifications.
"""
import logging
from datetime import datetime

from django.utils import timezone

from apps.notifications.fcm import notifier_utilisateur

from .models import DemandeReservation, HistoriqueDemande

logger = logging.getLogger('poufiret.reservations')

# ── Machine d'état ────────────────────────────────────────────────────
TRANSITIONS = {
    'nouvelle': ['en_cours', 'confirmee', 'refusee', 'annulee'],
    'en_cours': ['confirmee', 'refusee', 'annulee'],
    'confirmee': ['terminee', 'annulee'],
    'refusee': [],
    'annulee': [],
    'terminee': [],
}

_LIBELLES = {
    'en_cours': 'est en cours de traitement',
    'confirmee': 'a été confirmée',
    'refusee': 'a été refusée',
    'terminee': 'est terminée',
}

# Commentaire obligatoire par périmètre — mêmes règles que TransitionLoueurView
# (apps.reservations.views) et TransitionAdminView (apps.reservations.views_admin) :
# le loueur ne motive que le refus, l'admin motive aussi l'annulation.
_COMMENTAIRE_OBLIGATOIRE = {
    'loueur': {DemandeReservation.Statut.REFUSEE},
    'admin': {DemandeReservation.Statut.REFUSEE, DemandeReservation.Statut.ANNULEE},
}


def transitions_possibles(statut, perimetre):
    """[{action, libelle, commentaire_obligatoire}] depuis `statut`, pour
    `perimetre` ('loueur' ou 'admin') — même machine d'état (TRANSITIONS) et
    mêmes règles de motif obligatoire que les vues de transition."""
    libelles = dict(DemandeReservation.Statut.choices)
    obligatoires = _COMMENTAIRE_OBLIGATOIRE[perimetre]
    return [
        {'action': action, 'libelle': libelles[action], 'commentaire_obligatoire': action in obligatoires}
        for action in TRANSITIONS.get(statut, [])
    ]

# Choix signalé au rapport : une demande confirmée de type « réservation »
# passe le logement visé en « réservé » ; si cette demande est ensuite
# annulée (ou refusée, chemin théorique depuis confirmee non prévu par la
# machine d'état), le logement redevient « disponible » — symétrique à la
# restauration de stock des menus (apps.restaurants.services). Le passage
# à « loué » (signature effective du bail) reste un acte distinct du
# loueur/admin via la route de disponibilité, hors du cycle de la demande.
GROUPE_PAR_STATUT = {
    DemandeReservation.Statut.NOUVELLE: 'a_traiter',
    DemandeReservation.Statut.EN_COURS: 'en_cours',
    DemandeReservation.Statut.CONFIRMEE: 'en_cours',
    DemandeReservation.Statut.TERMINEE: 'terminees',
    DemandeReservation.Statut.REFUSEE: 'annulees',
    DemandeReservation.Statut.ANNULEE: 'annulees',
}

LIBELLES_GROUPE = {
    'a_traiter': 'À traiter',
    'en_cours': 'En cours',
    'terminees': 'Terminées',
    'annulees': 'Annulées',
}

STATUTS_PAR_GROUPE = {}
for _statut, _groupe in GROUPE_PAR_STATUT.items():
    STATUTS_PAR_GROUPE.setdefault(_groupe, []).append(_statut)


def numero_demande():
    annee = datetime.now().year
    n = DemandeReservation.objects.filter(numero__startswith=f'RSV-{annee}-').count() + 1
    return f'RSV-{annee}-{n:05d}'


def _logement_de(demande):
    return getattr(demande.objet, 'logement', None)


def visite_eligible(objet):
    """Une visite ne peut porter que sur un logement disponible (règle
    actuelle, logement uniquement — générique aux autres verticaux plus tard)."""
    logement = getattr(objet, 'logement', None)
    if logement is None:
        return True
    return logement.disponibilite == logement.Disponibilite.DISPONIBLE


def _notifier_transition_demande(demande, cible, acteur_role, request=None):
    """Notifie client et loueur, sauf l'acteur qui a déclenché la
    transition (mode parallèle à apps.orders._notifier_transition_commande)."""
    num = demande.numero
    if cible == 'annulee' and acteur_role == 'client':
        dest = getattr(demande.partenaire, 'user', None)
        if dest:
            notifier_utilisateur(
                dest, 'Demande annulée', f'La demande {num} a été annulée par le client.',
                data={'type': 'reservation', 'demande_id': demande.id, 'statut': demande.statut},
                request=request)
        return
    libelle = _LIBELLES.get(cible)
    if not libelle:
        return
    if acteur_role != 'client':
        notifier_utilisateur(
            demande.client, 'Suivi de votre demande', f'Votre demande {num} {libelle}.',
            data={'type': 'reservation', 'demande_id': demande.id, 'statut': demande.statut},
            request=request)
    if acteur_role != 'loueur':
        dest = getattr(demande.partenaire, 'user', None)
        if dest:
            notifier_utilisateur(
                dest, 'Suivi d\'une demande', f'La demande {num} {libelle}.',
                data={'type': 'reservation', 'demande_id': demande.id, 'statut': demande.statut},
                request=request)


def _notifier_admins_demande(demande, type_notif, titre, message):
    """Notification in-app (apps.moderation.models.Notification, réutilisé,
    même mécanisme que apps.orders._notifier_admins_commande) aux admins
    habilités (gerer_reservations). Best-effort."""
    try:
        from django.db.models import Q

        from apps.moderation.models import Notification
        from apps.users.models import User

        destinataires = User.objects.filter(is_active=True).filter(
            Q(is_superuser=True)
            | Q(is_staff=True, permissions_admin__gerer_reservations=True))
        groupe = GROUPE_PAR_STATUT.get(demande.statut, '')
        Notification.objects.bulk_create([
            Notification(
                user=u, type=type_notif, titre=titre, contenu=message,
                data={'demande_id': demande.id, 'groupe': groupe},
            ) for u in destinataires
        ])
    except Exception:
        logger.exception('Notification admin demande %s (%s) : échec, action non bloquée.',
                         demande.pk, type_notif)


def appliquer_transition_demande(demande, cible, acteur, acteur_role, commentaire='', request=None):
    """Point CENTRAL de toute transition de demande (client, loueur, admin)
    — ne vérifie PAS les droits d'accès par rôle (l'appelant s'en charge).
    Retourne (ok: bool, message: str)."""
    if cible not in TRANSITIONS.get(demande.statut, []):
        return False, f'Transition {demande.statut} → {cible} non autorisée.'

    ancien_statut = demande.statut
    demande.statut = cible
    maintenant = timezone.now()
    if cible == 'confirmee':
        demande.confirmee_le = maintenant
    elif cible == 'terminee':
        demande.terminee_le = maintenant
    elif cible == 'refusee':
        demande.raison_refus = commentaire or demande.raison_refus
    elif cible == 'annulee':
        demande.annulee_par = acteur
    demande.save()

    if demande.nature == DemandeReservation.Nature.RESERVATION:
        logement = _logement_de(demande)
        if logement is not None:
            if cible == 'confirmee':
                logement.disponibilite = logement.Disponibilite.RESERVE
                logement.save(update_fields=['disponibilite', 'updated_at'])
            elif cible in ('annulee', 'refusee') and ancien_statut == DemandeReservation.Statut.CONFIRMEE \
                    and logement.disponibilite == logement.Disponibilite.RESERVE:
                logement.disponibilite = logement.Disponibilite.DISPONIBLE
                logement.save(update_fields=['disponibilite', 'updated_at'])

    HistoriqueDemande.objects.create(
        demande=demande, statut=cible, acteur=acteur, acteur_role=acteur_role,
        commentaire=commentaire or '',
    )
    _notifier_transition_demande(demande, cible, acteur_role, request)
    if cible == 'annulee' and acteur_role == 'client':
        _notifier_admins_demande(
            demande, 'reservation_nouvelle', 'Demande annulée',
            f'{demande.numero} — {demande.client.get_full_name() or demande.client.telephone} '
            f'chez {demande.partenaire.nom_commerce}.')

    return True, f'Statut : {demande.get_statut_display()}.'
