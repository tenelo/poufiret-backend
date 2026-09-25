import logging
from datetime import timedelta

from django.db.models import Avg, Count, F
from django.utils import timezone

from apps.users.models import Portee

from .models import ImpressionPublicite, ParametresPublicite, Publicite, TypeAffichage

logger = logging.getLogger('poufiret.notifications')


def portee_a_appliquer(profil, demandee=None):
    """Portee stockee pour une campagne : MAX(forfait du partenaire, demandee).

    Une portee absente, egale ou inferieure au forfait n'est jamais une
    erreur : la campagne prend simplement celle du forfait (une pub ne
    descend jamais sous le forfait, voir Publicite.portee_effective). Une
    portee superieure est conservee. Source unique pour la creation et la
    reconduction.
    """
    forfait = getattr(profil, 'portee', Portee.DEPARTEMENT)
    if demandee and Portee.rang(demandee) > Portee.rang(forfait):
        return demandee
    return forfait


def est_heure_affluence(params=None):
    """Vrai si l'heure courante est dans le creneau d'affluence.

    Si calcul_affluence_auto est actif, le creneau est deduit des sessions
    reelles (heure ayant le plus de debuts de session sur 30 jours).
    """
    params = params or ParametresPublicite.obtenir()
    maintenant = timezone.localtime()
    if params.calcul_affluence_auto:
        creneau = calculer_heures_affluence()
        if creneau:
            debut, fin = creneau
            return debut <= maintenant.hour < fin
    debut, fin = params.affluence_debut, params.affluence_fin
    heure = maintenant.time()
    if debut <= fin:
        return debut <= heure < fin
    return heure >= debut or heure < fin  # creneau a cheval sur minuit


def calculer_heures_affluence(nb_heures=3, jours=30):
    """Deduit le creneau d'affluence des sessions reelles.

    Retourne (heure_debut, heure_fin) ou None si pas assez de donnees.
    """
    from django.db.models.functions import ExtractHour
    from apps.analytics.models import TempsSessionUtilisateur

    depuis = timezone.now() - timedelta(days=jours)
    compte_par_heure = dict(
        TempsSessionUtilisateur.objects.filter(debut__gte=depuis)
        .annotate(h=ExtractHour('debut'))
        .values_list('h')
        .annotate(n=Count('id'))
    )
    if not compte_par_heure:
        return None
    # Fenetre glissante de nb_heures consecutives la plus chargee
    meilleur_debut, meilleur_total = 0, -1
    for debut in range(24):
        total = sum(compte_par_heure.get((debut + i) % 24, 0) for i in range(nb_heures))
        if total > meilleur_total:
            meilleur_debut, meilleur_total = debut, total
    return meilleur_debut, (meilleur_debut + nb_heures) % 24


def duree_moyenne_session(utilisateur, jours=30):
    """Duree moyenne de session de l'utilisateur, en secondes."""
    from apps.analytics.models import TempsSessionUtilisateur

    depuis = timezone.now() - timedelta(days=jours)
    moyenne = (
        TempsSessionUtilisateur.objects
        .filter(utilisateur=utilisateur, debut__gte=depuis)
        .annotate(duree=F('dernier_ping') - F('debut'))
        .aggregate(m=Avg('duree'))['m']
    )
    return int(moyenne.total_seconds()) if moyenne else None


def minute_cible_interstitiel(utilisateur, params=None):
    """Minute a laquelle servir l'interstitiel a cet utilisateur.

    Session longue -> minute nominale (parametrable).
    Session courte -> on avance le tir pour l'atteindre avant deconnexion.
    """
    params = params or ParametresPublicite.obtenir()
    moyenne = duree_moyenne_session(utilisateur)
    if moyenne is None:
        return params.interstitiel_minute_min
    minutes = moyenne // 60
    if minutes >= params.interstitiel_minute_max:
        return params.interstitiel_minute_min
    ratio = params.interstitiel_ratio_session_courte / 100
    return max(1, int(minutes * ratio))


def _pubs_diffusables():
    """Pubs actives : dans la periode, ou hors periode mais cible non atteinte.

    Exclut aussi les pubs masquées par leur partenaire (masquage
    volontaire côté partenaire, mais par sécurité on ne les diffuse pas :
    voir Publicite.masquee_par_partenaire) — seul point d'entrée de la
    diffusion mobile (carrousel/interstitiel/bandeau/page publicités),
    donc suffisant pour couvrir tous ces emplacements en un seul endroit.
    """
    maintenant = timezone.now()
    candidates = (
        Publicite.objects
        .filter(statut=Publicite.Statut.ACTIVE, debut_diffusion__lte=maintenant)
        .exclude(masquee_par_partenaire=True)
        .select_related('formule', 'partenaire', 'partenaire__departement__region')
    )
    return [
        p for p in candidates
        if not p.fin_diffusion or maintenant < p.fin_diffusion or not p.cible_atteinte
    ]


def quota_du_type(formule, type_affichage):
    """Nombre de passages autorises par jour pour un emplacement donne.

    Si la formule definit passages_par_type, chaque emplacement a son
    propre quota : le carrousel ne peut plus consommer la place vendue
    pour l'interstitiel. Sinon, on retombe sur le quota global.
    """
    par_type = formule.passages_par_type or {}
    valeur = par_type.get(type_affichage)
    if isinstance(valeur, int) and valeur >= 0:
        return valeur
    return formule.passages_par_jour


def _passages_restants(pub, utilisateur, type_affichage=None):
    """Vrai si l'utilisateur n'a pas epuise les passages du jour.

    Quand la formule detaille ses quotas par emplacement, le decompte se
    fait sur le seul emplacement demande ; sinon sur tous confondus.
    """
    if utilisateur is None or not utilisateur.is_authenticated:
        return True
    debut_jour = timezone.localtime().replace(
        hour=0, minute=0, second=0, microsecond=0)
    filtres = {'publicite': pub, 'utilisateur': utilisateur,
               'cree_le__gte': debut_jour}
    detaille = bool(pub.formule.passages_par_type) and type_affichage
    if detaille:
        filtres['type_affichage'] = type_affichage
        quota = quota_du_type(pub.formule, type_affichage)
    else:
        quota = pub.formule.passages_par_jour
    return ImpressionPublicite.objects.filter(**filtres).count() < quota


def _vues_du_jour(utilisateur, pubs, type_affichage=None):
    """Impressions du jour par publicite, pour cet utilisateur (1 requete)."""
    if utilisateur is None or not utilisateur.is_authenticated or not pubs:
        return {}
    debut_jour = timezone.localtime().replace(
        hour=0, minute=0, second=0, microsecond=0)
    filtres = {'utilisateur': utilisateur, 'cree_le__gte': debut_jour,
               'publicite__in': [p.pk for p in pubs]}
    # Si au moins une formule detaille ses quotas, on compte par emplacement.
    if type_affichage and any(p.formule.passages_par_type for p in pubs):
        filtres['type_affichage'] = type_affichage
    lignes = (
        ImpressionPublicite.objects.filter(**filtres)
        .values('publicite').annotate(n=Count('id'))
    )
    return {l['publicite']: l['n'] for l in lignes}


def _taux_consommation(pub, vues, type_affichage=None):
    """Part du quota journalier deja consommee (0 = intacte, 1 = epuisee).

    Sert a faire tourner les pubs au lieu d'epuiser la plus prioritaire
    d'un seul bloc : celle qui a le moins entame son quota passe en premier.
    Le forfait reste respecte, puisqu'un quota plus eleve se consomme
    plus lentement en proportion.
    """
    quota = max(1, quota_du_type(pub.formule, type_affichage)
                if type_affichage else pub.formule.passages_par_jour)
    return vues.get(pub.pk, 0) / quota


def _interstitiel_autorise(utilisateur, params):
    """Respecte l'intervalle minimum entre deux interstitiels."""
    if utilisateur is None or not utilisateur.is_authenticated:
        return True
    dernier = ImpressionPublicite.objects.filter(
        utilisateur=utilisateur, type_affichage=TypeAffichage.INTERSTITIEL,
    ).order_by('-cree_le').first()
    if dernier is None:
        return True
    ecoule = (timezone.now() - dernier.cree_le).total_seconds()
    return ecoule >= params.intervalle_min_interstitiel_secondes


def _pub_visible_pour(pub, utilisateur):
    """Vrai si l'utilisateur est dans la portee EFFECTIVE de la pub.

    Miroir de geo.portee.filtre_visibilite, cote publicite :
      - utilisateur non localise (anonyme ou sans departement) -> voit TOUT
        (coherent avec l'organique : on donne envie avant de localiser) ;
      - portee 'district' -> visible partout ;
      - portee 'region'   -> meme region que l'utilisateur ;
      - portee 'departement' -> meme departement que le partenaire.
    La portee utilisee est portee_effective = MAX(forfait, achetee).
    """
    dep_user = getattr(utilisateur, 'departement', None) if (
        utilisateur is not None and utilisateur.is_authenticated) else None
    if dep_user is None:
        return True

    portee = pub.portee_effective
    if portee == 'district':
        return True

    dep_pub = getattr(pub.partenaire, 'departement', None)
    if dep_pub is None:
        # Partenaire sans departement renseigne : on ne le cache pas.
        return True

    if portee == 'region':
        return dep_pub.region_id == dep_user.region_id
    # portee 'departement'
    return dep_pub.id == dep_user.id


def selectionner_pubs(type_affichage, utilisateur=None, minute_session=None, limite=None):
    """Retourne les pubs a diffuser pour un emplacement donne, triees par priorite."""
    params = ParametresPublicite.obtenir()
    affluence = est_heure_affluence(params)

    if type_affichage == TypeAffichage.INTERSTITIEL:
        if not _interstitiel_autorise(utilisateur, params):
            return []
        if utilisateur is not None and utilisateur.is_authenticated:
            cible = minute_cible_interstitiel(utilisateur, params)
            if minute_session is None or minute_session < cible:
                return []

    resultat = []
    for pub in _pubs_diffusables():
        formule = pub.formule
        if type_affichage not in (formule.types_affichage or []):
            continue
        if affluence and not formule.acces_heures_affluence:
            continue
        if not _passages_restants(pub, utilisateur, type_affichage):
            continue
        if not _pub_visible_pour(pub, utilisateur):
            continue
        resultat.append(pub)

    # Rotation : la moins servie (en proportion de son quota) d'abord.
    # La priorite ne departage plus que les egalites.
    vues = _vues_du_jour(utilisateur, resultat, type_affichage)
    resultat.sort(key=lambda p: (
        _taux_consommation(p, vues, type_affichage),
        -p.formule.priorite, p.cree_le))
    return resultat[:limite] if limite else resultat


# ── Transitions de statut (source unique : API, admin, Angular) ───────

TRANSITIONS = {
    'soumettre': {
        'depuis': [Publicite.Statut.BROUILLON],
        'vers': Publicite.Statut.EN_ATTENTE_PAIEMENT,
        'admin': False,
        'libelle': 'Soumettre',
    },
    'annuler_soumission': {
        'depuis': [Publicite.Statut.EN_ATTENTE_PAIEMENT],
        'vers': Publicite.Statut.BROUILLON,
        'admin': False,
        'libelle': 'Annuler la soumission',
    },
    'confirmer_paiement': {
        'depuis': [Publicite.Statut.EN_ATTENTE_PAIEMENT],
        'vers': Publicite.Statut.EN_ATTENTE_VALIDATION,
        'admin': True,
        'libelle': 'Confirmer le paiement',
    },
    'valider': {
        'depuis': [Publicite.Statut.EN_ATTENTE_VALIDATION],
        'vers': Publicite.Statut.ACTIVE,
        'admin': True,
        'libelle': 'Valider et lancer la diffusion',
    },
    'rejeter': {
        'depuis': [Publicite.Statut.EN_ATTENTE_VALIDATION,
                   Publicite.Statut.EN_ATTENTE_PAIEMENT],
        'vers': Publicite.Statut.REJETEE,
        'admin': True,
        'libelle': 'Rejeter',
    },
    'terminer': {
        'depuis': [Publicite.Statut.ACTIVE],
        'vers': Publicite.Statut.TERMINEE,
        'admin': True,
        'libelle': 'Terminer la diffusion',
    },
}

# Code JournalModeration.Action correspondant a chaque transition admin
# (valeurs <= 20 caracteres : JournalModeration.action est un CharField(20)).
_ACTIONS_JOURNAL = {
    'confirmer_paiement': 'pub_paiement_ok',
    'valider': 'pub_valider',
    'rejeter': 'pub_rejeter',
    'terminer': 'pub_terminer',
    'annuler_soumission': 'pub_annuler',
}


def journaliser_transition(acteur, pub, action, message):
    """Trace une transition admin de pub dans le journal d'audit existant
    (JournalModeration, meme mecanisme que les autres actions du projet).

    Best-effort : n'empeche jamais la transition elle-meme si l'ecriture
    du journal echoue (meme pattern que les autres journalisations du
    projet, ex. apps.publicites.credits.consommer_credit).
    Journalise les transitions admin et l'annulation de soumission par le
    partenaire ; soumettre n'est pas concernee.
    """
    code = _ACTIONS_JOURNAL.get(action)
    if code is None:
        return
    try:
        from apps.administration.moderation import _journaliser
        _journaliser(
            acteur, pub.partenaire.user, code,
            f'Publicité « {pub.titre} » (id {pub.pk}) — {message}',
        )
    except Exception:
        pass


def nb_actives_formule(formule, exclure=None):
    """Nombre de pubs au statut active en meme temps sur CETTE formule
    (tous partenaires confondus), sans compter `exclure` (la pub en cours
    d'activation)."""
    qs = Publicite.objects.filter(formule=formule, statut=Publicite.Statut.ACTIVE)
    if exclure is not None:
        qs = qs.exclude(pk=exclure.pk)
    return qs.count()


def quota_formule_disponible(pub):
    """Vrai si la formule n'a pas atteint son quota d'annonceurs simultanes."""
    return nb_actives_formule(pub.formule, exclure=pub) < pub.formule.quota_partenaires


def raison_refus_annulation(pub):
    """Message francais si la soumission ne peut pas etre annulee, sinon None.

    Annulable seulement si la pub est soumise (en attente de paiement), pas
    encore activee, et sans paiement confirme.
    """
    Statut = Publicite.Statut
    refus = {
        Statut.BROUILLON: "Cette publicité n'a pas été soumise : il n'y a rien à annuler.",
        Statut.EN_ATTENTE_VALIDATION: (
            'Le paiement de cette publicité est déjà confirmé : la '
            'soumission ne peut plus être annulée.'),
        Statut.ACTIVE: (
            'Cette publicité est déjà active : la soumission ne peut plus '
            'être annulée.'),
        Statut.TERMINEE: (
            'Cette publicité est terminée : la soumission ne peut plus être '
            'annulée.'),
        Statut.REJETEE: (
            'Cette publicité a été rejetée : sa soumission ne peut pas être '
            'annulée.'),
    }
    if pub.statut in refus:
        return refus[pub.statut]
    paiement = pub.paiement
    if paiement is not None and paiement.statut == 'confirme':
        return ('Un paiement est déjà confirmé pour cette publicité : la '
                'soumission ne peut plus être annulée.')
    return None


def activer_publicite(pub):
    """Passe la pub en diffusion et calcule ses dates."""
    from datetime import timedelta
    pub.statut = Publicite.Statut.ACTIVE
    pub.debut_diffusion = timezone.now()
    pub.fin_diffusion = pub.debut_diffusion + timedelta(
        days=pub.formule.duree_jours)
    pub.save(update_fields=['statut', 'debut_diffusion', 'fin_diffusion',
                            'modifie_le'])


def _notifier_admins_pub(pub, type_notif, titre, message):
    """Notification in-app (apps.moderation.models.Notification, réutilisé
    tel quel — aucun nouveau modèle) aux admins habilités à valider les
    pubs, sur soumission ou confirmation de paiement.

    Best-effort : n'empêche JAMAIS la transition si l'écriture échoue
    (try/except + log), même esprit que journaliser_transition. Hors
    périmètre : pas de push FCM vers les admins (PWA Angular).
    """
    try:
        from django.db.models import Q

        from apps.moderation.models import Notification
        from apps.users.models import User

        destinataires = User.objects.filter(is_active=True).filter(
            Q(is_superuser=True)
            | Q(is_staff=True, permissions_admin__valider_publicite=True))
        Notification.objects.bulk_create([
            Notification(
                user=u, type=type_notif, titre=titre, contenu=message,
                data={'publicite_id': str(pub.id), 'statut_publicite': pub.statut},
            ) for u in destinataires
        ])
    except Exception:
        logger.exception(
            'Notification admin pub %s (%s) : échec, transition non bloquée.',
            pub.pk, type_notif)


def _notifier_transition_pub(pub, vers):
    """Déclenche la notification adaptée selon le nouvel état atteint.

    Appelé depuis le coeur meme d'appliquer_transition (pas par chaque
    appelant, contrairement a journaliser_transition qui a besoin de
    l'acteur) : couvre ainsi TOUTES les routes qui passent par cette
    fonction — API partenaire (soumettre), admin (confirmer_paiement),
    et les boutons de transition du Django admin (apps/publicites/admin.py
    ::vue_transition, qui appelle aussi appliquer_transition). N'est PAS
    déclenché si un admin édite le champ `statut` à la main dans le
    formulaire Django admin, en dehors de ces boutons — cas non couvert,
    signalé au rapport.
    """
    if vers == Publicite.Statut.EN_ATTENTE_PAIEMENT:
        _notifier_admins_pub(
            pub, 'pub_soumise', 'Nouvelle campagne soumise',
            f'{pub.titre} — {pub.partenaire.nom_commerce} ({pub.formule.nom})')
    elif vers == Publicite.Statut.EN_ATTENTE_VALIDATION:
        _notifier_admins_pub(
            pub, 'pub_a_valider', 'Campagne prête à valider',
            f'{pub.titre} — {pub.partenaire.nom_commerce}')


def appliquer_transition(pub, action):
    """Applique une transition de statut.

    Retourne (ok: bool, message: str). Ne verifie PAS les droits :
    l'appelant (vue API ou admin) s'en charge.
    """
    regle = TRANSITIONS.get(action)
    if regle is None:
        return False, 'Action inconnue.'
    if action == 'annuler_soumission':
        raison = raison_refus_annulation(pub)
        if raison:
            return False, raison
    if pub.statut not in regle['depuis']:
        return False, (f'Transition impossible depuis '
                       f'"{pub.get_statut_display()}".')

    vers = regle['vers']
    activation = vers == Publicite.Statut.ACTIVE or (
        action == 'confirmer_paiement'
        and ParametresPublicite.obtenir().validation_auto
    )
    if activation:
        if not quota_formule_disponible(pub):
            quota = pub.formule.quota_partenaires
            return False, (
                f'Quota de la formule « {pub.formule.nom} » atteint '
                f'({nb_actives_formule(pub.formule, exclure=pub)}/{quota} '
                f'campagne(s) active(s) en même temps). Activation impossible '
                f'tant qu\'une campagne active de cette formule n\'est pas '
                f'terminée.')
        activer_publicite(pub)
        return True, 'Publicite activee, diffusion lancee.'

    pub.statut = vers
    pub.save(update_fields=['statut', 'modifie_le'])
    _notifier_transition_pub(pub, vers)
    return True, f'Statut : {pub.get_statut_display()}.'
