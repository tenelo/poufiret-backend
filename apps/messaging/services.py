"""Services des demandes d'intervention : machine d'état (point CENTRAL de
toute transition — client, artisan, admin), historique, réassignation,
notifications client/artisan et notification admin à la création.

Même architecture que apps.orders.services (appliquer_transition_commande).
Ne vérifie PAS les droits : l'appelant s'en charge.
"""
import logging

from django.db.models import Q
from django.utils import timezone

from apps.notifications.fcm import notifier_utilisateur

from .models import DemandeIntervention, HistoriqueIntervention

logger = logging.getLogger(__name__)

TRANSITIONS = {
    'en_attente': ['acceptee', 'refusee', 'annulee'],
    'acceptee': ['en_cours', 'annulee'],
    'en_cours': ['terminee', 'annulee'],
    'terminee': [], 'refusee': [], 'annulee': [],
}

# Libellés des boutons d'action (admin) et motif obligatoire.
ACTIONS_LIBELLES = {
    'acceptee': 'Accepter', 'refusee': 'Refuser', 'en_cours': 'Démarrer',
    'terminee': 'Terminer', 'annulee': 'Annuler',
}
ACTIONS_COMMENTAIRE_OBLIGATOIRE = {'annulee', 'refusee'}

# Statuts depuis lesquels l'admin peut réassigner la demande à un autre artisan.
STATUTS_REASSIGNABLES = ('en_attente', 'refusee')

_LIBELLES_INTERVENTION = {
    'acceptee': 'a ete acceptee',
    'refusee': 'a ete refusee',
    'en_cours': 'est en cours',
    'terminee': 'est terminee',
    'annulee': 'a ete annulee',
}


def _data(demande, est_artisan):
    return {'type': 'intervention', 'id': str(demande.id), 'est_artisan': '1' if est_artisan else '0'}


def _notifier_transition_intervention(demande, cible, acteur_role, request):
    """Notifie la bonne partie après un changement de statut :
    - client qui annule → l'artisan ;
    - artisan → le client (comportement historique) ;
    - admin → le client ET l'artisan."""
    num = demande.numero
    if acteur_role == HistoriqueIntervention.ActeurRole.CLIENT:
        if cible == 'annulee':
            dest = getattr(demande.artisan, 'user', None)
            if dest:
                notifier_utilisateur(
                    dest, 'Demande annulee',
                    f'La demande {num} a ete annulee par le client.',
                    data=_data(demande, True), request=request)
        return
    libelle = _LIBELLES_INTERVENTION.get(cible)
    if not libelle:
        return
    if acteur_role == HistoriqueIntervention.ActeurRole.ARTISAN and cible == 'annulee':
        return  # comportement historique : rien pour une annulation côté artisan
    notifier_utilisateur(
        demande.user, 'Suivi de demande', f'Votre demande {num} {libelle}.',
        data=_data(demande, False), request=request)
    if acteur_role == HistoriqueIntervention.ActeurRole.ADMIN:
        dest = getattr(demande.artisan, 'user', None)
        if dest:
            notifier_utilisateur(
                dest, 'Suivi de demande',
                f'La demande {num} {libelle} (par l\'administration).',
                data=_data(demande, True), request=request)


def appliquer_transition_intervention(demande, cible, acteur, acteur_role,
                                      commentaire='', request=None, champs=None):
    """Vérifie la machine d'état, applique le statut (+ dates clés et
    `champs` éventuels : date_proposee, prix_propose…), historise et notifie.
    Retourne (ok: bool, message: str)."""
    if cible not in TRANSITIONS.get(demande.statut, []):
        return False, f"Transition {demande.statut} → {cible} non autorisée."
    for nom, valeur in (champs or {}).items():
        setattr(demande, nom, valeur)
    if cible == 'acceptee':
        demande.acceptee_le = timezone.now()
    elif cible == 'terminee':
        demande.terminee_le = timezone.now()
    elif cible == 'refusee' and commentaire and not (champs or {}).get('raison_refus'):
        demande.raison_refus = commentaire
    demande.statut = cible
    demande.save()
    HistoriqueIntervention.objects.create(
        demande=demande, statut=cible, acteur=acteur, acteur_role=acteur_role,
        commentaire=commentaire or '')
    _notifier_transition_intervention(demande, cible, acteur_role, request)
    return True, ''


def artisans_compatibles(demande):
    """Partenaires actifs du même type que l'artisan actuel (hors lui)."""
    from apps.users.models import ProfilPartenaire
    return (ProfilPartenaire.objects
            .filter(type_partenaire=demande.artisan.type_partenaire,
                    statut=ProfilPartenaire.Statut.ACTIF)
            .exclude(pk=demande.artisan_id))


def assigner_intervention(demande, artisan, acteur, commentaire='', request=None):
    """Réassigne la demande (admin) : statut remis à en_attente, raison de
    refus effacée, historique, notification du nouvel artisan et du client.
    Retourne (ok, message)."""
    if demande.statut not in STATUTS_REASSIGNABLES:
        return False, (f'Réassignation impossible au statut « {demande.get_statut_display()} » '
                       f'(possible : en attente ou refusée).')
    if artisan.pk == demande.artisan_id:
        return False, 'Cet artisan est déjà assigné à la demande.'
    if not artisans_compatibles(demande).filter(pk=artisan.pk).exists():
        return False, ("Artisan incompatible : il doit être actif et du même type "
                       f"({demande.artisan.get_type_partenaire_display()}).")
    ancien = demande.artisan
    demande.artisan = artisan
    demande.statut = DemandeIntervention.Statut.EN_ATTENTE
    demande.raison_refus = ''
    demande.save()
    HistoriqueIntervention.objects.create(
        demande=demande, statut=demande.statut, acteur=acteur,
        acteur_role=HistoriqueIntervention.ActeurRole.ADMIN,
        commentaire=(f'Réassignée de « {ancien.nom_commerce} » à « {artisan.nom_commerce} ».'
                     + (f' {commentaire}' if commentaire else '')))
    notifier_utilisateur(
        artisan.user, "Nouvelle demande d'intervention",
        f'La demande {demande.numero} vous a ete assignee.',
        data=_data(demande, True), request=request)
    notifier_utilisateur(
        demande.user, 'Suivi de demande',
        f'Votre demande {demande.numero} a ete confiee a {artisan.nom_commerce}.',
        data=_data(demande, False), request=request)
    return True, ''


def notifier_admins_intervention_nouvelle(demande):
    """Notification in-app intervention_nouvelle (canal general, cible
    interventions) aux super-admins et aux admins ayant voir_interventions
    ou gerer_interventions. Best-effort : ne bloque jamais la création."""
    try:
        from apps.moderation.models import Notification
        from apps.notifications.canaux import champs_canal
        from apps.users.models import User

        destinataires = User.objects.filter(is_active=True).filter(
            Q(is_superuser=True)
            | Q(is_staff=True, permissions_admin__voir_interventions=True)
            | Q(is_staff=True, permissions_admin__gerer_interventions=True)).distinct()
        data = {'intervention_id': demande.id, 'statut': demande.statut}
        canal = champs_canal(Notification.Type.INTERVENTION_NOUVELLE, data)
        client = demande.user.get_full_name() or demande.user.telephone
        Notification.objects.bulk_create([
            Notification(
                user=u, type=Notification.Type.INTERVENTION_NOUVELLE,
                titre="Nouvelle demande d'intervention",
                contenu=(f'{demande.numero} — {client} → {demande.artisan.nom_commerce} '
                         f'({demande.get_type_intervention_display()}, '
                         f'{demande.get_urgence_display()}).'),
                data=data, **canal,
            ) for u in destinataires
        ])
    except Exception:
        logger.exception('Notification admin intervention %s : échec, création non bloquée.',
                         demande.pk)
