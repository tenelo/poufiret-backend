"""Services de l'app orders : machine d'état des commandes (source unique,
partagée par le client, le partenaire et l'admin), demande de livreur
(TeneLivr) et notifications.

La machine d'état (transitions_pour : parcours « court » ou « restauration »
selon le type du partenaire), _LIBELLES_COMMANDE et
_notifier_transition_commande sont la source unique pour le client, le
partenaire et le centre de gestion admin.
"""
import logging

from django.utils import timezone

from apps.notifications.fcm import notifier_utilisateur

from .models import Commande, HistoriqueCommande

logger = logging.getLogger('poufiret.orders')

# ── Machine d'état : deux parcours selon le type du partenaire ───────
# « court » (commerces : boulangerie, mode, élevage, pharmacie, librairie…)
# et « restauration » (TYPES_RESTAURATION : restaurateur, fast_food,
# grilleur — « Accepter » = lancer la préparation). Les 9 statuts du modèle
# restent ; en_preparation n'est plus atteint par les nouvelles commandes,
# mais une commande déjà en en_preparation / prete termine son parcours.
PARCOURS_COURT = 'court'
PARCOURS_RESTAURATION = 'restauration'

_S = Commande.Statut


def parcours_de(commande):
    """'restauration' si le partenaire est d'un type de restauration
    (apps.restaurants.services.TYPES_RESTAURATION), sinon 'court'."""
    from apps.restaurants.services import TYPES_RESTAURATION
    if commande.partenaire.type_partenaire in TYPES_RESTAURATION:
        return PARCOURS_RESTAURATION
    return PARCOURS_COURT


def _en_livraison_si_livraison(commande):
    return [_S.EN_LIVRAISON] if commande.mode_livraison == Commande.ModeLivraison.LIVRAISON else []


def transitions_pour(commande):
    """Statuts cibles autorisés depuis le statut actuel de CETTE commande
    (source unique : client, partenaire, admin).

    Court        : nouvelle → acceptee | refusee | annulee ;
                   acceptee → [en_livraison si livraison] | livree | expiree | annulee ;
                   en_livraison → livree.
    Restauration : nouvelle → acceptee | refusee | annulee ;
                   acceptee → prete | annulee ;
                   prete → [en_livraison si livraison] | livree | expiree ;
                   en_livraison → livree.
    Anciennes commandes (les deux parcours) : en_preparation → prete | annulee ;
                   prete → [en_livraison si livraison] | livree | expiree."""
    statut = commande.statut
    if statut == _S.NOUVELLE:
        return [_S.ACCEPTEE, _S.REFUSEE, _S.ANNULEE]
    if statut == _S.ACCEPTEE:
        if parcours_de(commande) == PARCOURS_RESTAURATION:
            return [_S.PRETE, _S.ANNULEE]
        return _en_livraison_si_livraison(commande) + [_S.LIVREE, _S.EXPIREE, _S.ANNULEE]
    if statut == _S.EN_PREPARATION:
        return [_S.PRETE, _S.ANNULEE]
    if statut == _S.PRETE:
        return _en_livraison_si_livraison(commande) + [_S.LIVREE, _S.EXPIREE]
    if statut == _S.EN_LIVRAISON:
        return [_S.LIVREE]
    return []


def etapes_pour(commande):
    """Statuts du parcours NORMAL de cette commande, dans l'ordre (frise de
    suivi) : court → nouvelle, acceptee, [en_livraison], livree ;
    restauration → nouvelle, acceptee, prete, [en_livraison], livree."""
    etapes = [_S.NOUVELLE, _S.ACCEPTEE]
    if parcours_de(commande) == PARCOURS_RESTAURATION:
        etapes.append(_S.PRETE)
    return etapes + _en_livraison_si_livraison(commande) + [_S.LIVREE]


def transitions_possibles(commande, cibles=None, commentaire_annulation_obligatoire=True):
    """[{action, libelle, commentaire_obligatoire}] — format du centre admin,
    réutilisé côté partenaire / client. `cibles` : sous-ensemble autorisé
    (défaut : transitions_pour(commande))."""
    if cibles is None:
        cibles = transitions_pour(commande)
    return [{
        'action': str(action),
        'libelle': ACTIONS_LIBELLES.get(action, str(action)),
        'commentaire_obligatoire': commentaire_annulation_obligatoire and action == _S.ANNULEE,
    } for action in cibles]


_LIBELLES_COMMANDE = {
    'acceptee': 'a ete acceptee',
    'refusee': 'a ete refusee',
    'en_preparation': 'est en preparation',
    'prete': 'est prete',
    'en_livraison': 'est en livraison',
    'livree': 'a ete livree',
}

# Répartition des 9 statuts réels dans les 4 groupes du centre de gestion
# admin. Choix signalé au rapport : `expiree` (non récupérée) n'est ni un
# succès (livree) ni une action explicite (annulee/refusee), mais c'est bien
# une fin de vie négative de la commande — rangée dans `annulees`.
GROUPE_PAR_STATUT = {
    Commande.Statut.NOUVELLE: 'a_traiter',
    Commande.Statut.ACCEPTEE: 'en_cours',
    Commande.Statut.EN_PREPARATION: 'en_cours',
    Commande.Statut.PRETE: 'en_cours',
    Commande.Statut.EN_LIVRAISON: 'en_cours',
    Commande.Statut.LIVREE: 'terminees',
    Commande.Statut.REFUSEE: 'annulees',
    Commande.Statut.ANNULEE: 'annulees',
    Commande.Statut.EXPIREE: 'annulees',
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

ACTIONS_LIBELLES = {
    'acceptee': 'Accepter',
    'refusee': 'Refuser',
    'en_preparation': 'Mettre en préparation',
    'prete': 'Marquer prête',
    'en_livraison': 'Passer en livraison',
    'livree': 'Marquer livrée',
    'expiree': 'Marquer expirée',
    'annulee': 'Annuler',
}


def statut_permet_livreur(commande):
    """Statut à partir duquel un livreur peut être demandé : acceptee ou
    prete (anciennes commandes) au parcours court ; prete en restauration."""
    if parcours_de(commande) == PARCOURS_RESTAURATION:
        return commande.statut == _S.PRETE
    return commande.statut in (_S.ACCEPTEE, _S.PRETE)


def commande_eligible_livreur(commande):
    """Vrai si `demander_livreur(commande, ...)` réussirait — mêmes
    conditions, sans effet de bord (pas de création de Course)."""
    if commande.mode_livraison != Commande.ModeLivraison.LIVRAISON:
        return False
    if not statut_permet_livreur(commande):
        return False
    if commande.courses.exclude(statut__in=['annulee', 'refusee']).exists():
        return False
    return commande.partenaire.localisation is not None


def _notifier_transition_commande(commande, cible, acteur_est_client, request=None):
    """Notifie la bonne partie apres un changement de statut de commande.
    Inchangée (déplacée depuis views.py) : le centre admin réutilise cette
    même fonction, donc les notifications client/partenaire partent
    EXACTEMENT comme lors d'une transition partenaire — y compris leurs
    angles morts existants (ex. une annulation par le partenaire/l'admin ne
    notifie aujourd'hui ni l'un ni l'autre, `cible='annulee'` n'étant pas
    dans _LIBELLES_COMMANDE ; comportement préexistant, non modifié ici)."""
    num = commande.numero
    if cible == 'annulee' and acteur_est_client:
        dest = getattr(commande.partenaire, 'user', None)
        if dest:
            notifier_utilisateur(
                dest, 'Commande annulee',
                f'La commande {num} a ete annulee par le client.',
                data={'type': 'commande', 'commande_id': str(commande.id),
                     'statut': str(commande.statut)},
                request=request)
        return
    libelle = _LIBELLES_COMMANDE.get(cible)
    if cible == 'acceptee' and parcours_de(commande) == PARCOURS_RESTAURATION:
        libelle = 'a ete acceptee et est en preparation'
    if libelle:
        notifier_utilisateur(
            commande.user, 'Suivi de commande',
            f'Votre commande {num} {libelle}.',
            data={'type': 'commande', 'commande_id': str(commande.id),
                 'statut': str(commande.statut)},
            request=request)


def _notifier_admins_commande(commande, type_notif, titre, message):
    """Notification in-app (apps.moderation.models.Notification, réutilisé —
    même modèle que pour les pubs, apps.publicites.services._notifier_admins_pub)
    aux admins habilités à gérer les commandes.

    Best-effort : n'empêche JAMAIS l'action si l'écriture échoue (try/except
    + log). data = {commande_id, groupe} (entier, pas de casse en str : le
    PK de Commande n'est pas un UUID)."""
    try:
        from django.db.models import Q

        from apps.moderation.models import Notification
        from apps.users.models import User

        destinataires = list(User.objects.filter(is_active=True).filter(
            Q(is_superuser=True)
            | Q(is_staff=True, permissions_admin__gerer_commandes=True)))
        from apps.notifications.canaux import champs_canal

        groupe = GROUPE_PAR_STATUT.get(commande.statut, '')
        data = {'commande_id': commande.id, 'groupe': groupe}
        canal = champs_canal(type_notif, data, commande=commande)
        Notification.objects.bulk_create([
            Notification(
                user=u, type=type_notif, titre=titre, contenu=message,
                data=data, **canal,
            ) for u in destinataires
        ])
        from apps.notifications.temps_reel import diffuser_compteurs_admin
        diffuser_compteurs_admin(destinataires, nouvelle=True,
                                 push=(titre, message, {**data, 'canal': canal['canal']}))
    except Exception:
        logger.exception(
            'Notification admin commande %s (%s) : échec, action non bloquée.',
            commande.pk, type_notif)


def appliquer_transition_commande(commande, cible, acteur, acteur_role,
                                  commentaire='', request=None):
    """Point CENTRAL de toute transition de commande (client, partenaire,
    admin) — ne vérifie PAS les droits d'accès par rôle (l'appelant s'en
    charge, comme pour apps.publicites.services.appliquer_transition) :
    - vérifie la machine d'état (transitions_pour : parcours de la commande) ;
    - applique le changement de statut + les dates clés existantes ;
    - historise (HistoriqueCommande : statut, acteur, rôle, commentaire) ;
    - notifie client/partenaire via _notifier_transition_commande, à
      l'identique d'une transition partenaire ;
    - notifie les admins si le client annule (commande_annulee_client).

    Retourne (ok: bool, message: str).
    """
    if cible not in transitions_pour(commande):
        return False, message_transition_refusee(commande, cible)

    commande.statut = cible
    maintenant = timezone.now()
    if cible == 'acceptee':
        commande.acceptee_le = maintenant
    elif cible == 'prete':
        commande.prete_le = maintenant
    elif cible == 'livree':
        commande.livree_le = maintenant
    elif cible == 'refusee':
        commande.raison_refus = commentaire or commande.raison_refus
    elif cible == 'annulee':
        commande.annulee_par = acteur
    commande.save()

    if cible in ('annulee', 'refusee'):
        from apps.restaurants import services as services_restaurants
        pour_date = timezone.localtime(commande.created_at).date()
        for ligne in commande.lignes.filter(ligne_menu__isnull=False).select_related('ligne_menu'):
            services_restaurants.restaurer_stock(ligne.ligne_menu, ligne.quantite, pour_date=pour_date)

    HistoriqueCommande.objects.create(
        commande=commande, statut=cible, acteur=acteur,
        acteur_role=acteur_role, commentaire=commentaire or '',
    )

    if cible == 'annulee':
        # Collecte (analytics) : best-effort, ne fait jamais échouer la transition.
        from apps.analytics.collecte import enregistrer_evenement
        enregistrer_evenement(
            'commande_annulee', request=request, utilisateur=commande.user,
            partenaire=commande.partenaire, objet_type='commande', objet_id=commande.id,
            categorie=commande.categorie, valeur=commande.total,
            donnees={'numero': commande.numero, 'motif': commentaire or '',
                     'acteur_role': acteur_role, 'acteur_id': getattr(acteur, 'id', None)})

    acteur_est_client = acteur_role == HistoriqueCommande.ActeurRole.CLIENT
    _notifier_transition_commande(commande, cible, acteur_est_client, request)

    if cible == 'annulee' and acteur_est_client:
        _notifier_admins_commande(
            commande, 'commande_annulee_client', 'Commande annulée',
            f'{commande.numero} — {commande.user.get_full_name() or commande.user.telephone} '
            f'chez {commande.partenaire.nom_commerce}.')

    return True, f"Statut : {commande.get_statut_display()}."


def message_transition_refusee(commande, cible):
    """Message clair d'une transition interdite (400), avec les actions
    possibles depuis le statut actuel."""
    actuel = str(commande.get_statut_display())
    libelles = {v: str(l) for v, l in Commande.Statut.choices}
    vise = libelles.get(cible, cible or '—')
    possibles = [libelles.get(c, str(c)) for c in transitions_pour(commande)]
    suite = (f" Statut(s) possible(s) depuis « {actuel} » : {', '.join(possibles)}."
             if possibles else f" Aucun changement possible depuis « {actuel} ».")
    return f"Transition {commande.statut} → {cible} non autorisée : « {actuel} » → « {vise} » impossible.{suite}"


class DemandeLivreurInvalide(Exception):
    """400 — la commande n'est pas éligible à une demande de livreur."""


class LivraisonEnCoursError(Exception):
    """409 — une course est déjà active pour cette commande."""
    def __init__(self, message, numero_course):
        super().__init__(message)
        self.numero_course = numero_course


def demander_livreur(commande, demandeur, type_demandeur='partenaire'):
    """Crée une demande de livraison (Course TeneLivr) pour une commande
    acceptée (parcours court) ou prête (restauration, et anciennes
    commandes) — voir statut_permet_livreur — MÊME logique que apps.orders.views.CommanderLivreurView
    (partenaire) : mêmes gardes, même création de Course, même tentative
    d'assignation. Réutilisée par le partenaire ET par l'admin.

    Isolation TeneLivr respectée : ce module (orders) importe
    apps.livraison, jamais l'inverse — aucune dépendance nouvelle de
    livraison/livreurs vers orders ni vers l'administration.

    Point A = toujours le partenaire RÉEL de la commande (commande.partenaire),
    jamais le compte du demandeur — un admin agissant comme intermédiaire ne
    change pas le lieu de retrait.

    `type_demandeur` : 'partenaire' ou 'admin' (conservé pour l'analytics
    uniquement, comme le champ Course.type_demandeur documenté).

    Retourne (course, resultat_assignation).
    Lève DemandeLivreurInvalide (400) ou LivraisonEnCoursError (409).
    """
    from apps.livraison.models import Course
    from apps.livraison.views import _numero as _numero_course, finaliser_assignation

    profil = commande.partenaire

    # Ordre des gardes identique à l'ancien CommanderLivreurView (partenaire),
    # préservé pour la non-régression : mode livraison, puis course active,
    # puis statut, puis GPS.
    if commande.mode_livraison != Commande.ModeLivraison.LIVRAISON:
        raise DemandeLivreurInvalide("Cette commande n'est pas en mode livraison.")

    course_active = commande.courses.exclude(
        statut__in=['annulee', 'refusee']).order_by('-cree_le').first()
    if course_active is not None:
        raise LivraisonEnCoursError(
            'Une course est déjà en cours pour cette commande.',
            course_active.numero)

    if not statut_permet_livreur(commande):
        if parcours_de(commande) == PARCOURS_RESTAURATION:
            raise DemandeLivreurInvalide(
                "La commande doit être prête avant d'appeler un livreur.")
        raise DemandeLivreurInvalide(
            "La commande doit être acceptée avant d'appeler un livreur.")
    if profil.localisation is None:
        raise DemandeLivreurInvalide(
            "Le commerce n'a pas de position GPS. Renseignez-la d'abord.")

    client = commande.user
    course = Course.objects.create(
        numero=_numero_course(),
        demandeur=demandeur,
        type_demandeur=type_demandeur,
        ville=profil.departement,
        commande=commande,
        contact_user=client,
        a_quartier=profil.quartier or profil.nom_commerce,
        a_nom_contact=profil.nom_commerce,
        a_telephone_contact=profil.telephone_pro or profil.user.telephone,
        a_position=profil.localisation,
        b_quartier=commande.adresse_snapshot or '—',
        b_nom_contact=client.get_full_name() or client.telephone,
        b_telephone_contact=client.telephone,
        b_position=commande.localisation_livraison,
        description_colis=commande.numero,
        prix=int(commande.frais_livraison or 0),
    )
    resultat = finaliser_assignation(course)

    commande.statut = Commande.Statut.EN_LIVRAISON
    commande.save(update_fields=['statut'])

    return course, resultat
