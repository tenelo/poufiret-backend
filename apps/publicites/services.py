from datetime import timedelta

from django.db.models import Avg, Count, F
from django.utils import timezone

from .models import ImpressionPublicite, ParametresPublicite, Publicite, TypeAffichage


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
    """Pubs actives : dans la periode, ou hors periode mais cible non atteinte."""
    maintenant = timezone.now()
    candidates = (
        Publicite.objects
        .filter(statut=Publicite.Statut.ACTIVE, debut_diffusion__lte=maintenant)
        .select_related('formule', 'partenaire')
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


def quota_formule_disponible(pub):
    """Vrai si la formule n'a pas atteint son quota d'annonceurs simultanes."""
    nb_actives = Publicite.objects.filter(
        formule=pub.formule, statut=Publicite.Statut.ACTIVE,
    ).exclude(pk=pub.pk).count()
    return nb_actives < pub.formule.quota_partenaires


def activer_publicite(pub):
    """Passe la pub en diffusion et calcule ses dates."""
    from datetime import timedelta
    pub.statut = Publicite.Statut.ACTIVE
    pub.debut_diffusion = timezone.now()
    pub.fin_diffusion = pub.debut_diffusion + timedelta(
        days=pub.formule.duree_jours)
    pub.save(update_fields=['statut', 'debut_diffusion', 'fin_diffusion',
                            'modifie_le'])


def appliquer_transition(pub, action):
    """Applique une transition de statut.

    Retourne (ok: bool, message: str). Ne verifie PAS les droits :
    l'appelant (vue API ou admin) s'en charge.
    """
    regle = TRANSITIONS.get(action)
    if regle is None:
        return False, 'Action inconnue.'
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
            return False, ('Quota de la formule atteint : '
                           'activation impossible pour le moment.')
        activer_publicite(pub)
        return True, 'Publicite activee, diffusion lancee.'

    pub.statut = vers
    pub.save(update_fields=['statut', 'modifie_le'])
    return True, f'Statut : {pub.get_statut_display()}.'
