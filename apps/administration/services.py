"""Services du bloc administration (G5, super-admin).

Regroupe les mesures et actions réservées au super-admin :
  - répartition par type d'appareil (point 4 de G5) ;
  - (la modération de comptes est dans moderation.py).

Les stats de connexion (points 1-3 de G5 : comptes créés, en ligne,
connexions jour/semaine/mois) restent dans apps.analytics.stats_connexion
et sont simplement réexposées côté administration si besoin.
"""
from django.db.models import Count

from apps.users.models import SessionAppareil


def repartition_appareils(actives_seulement=True):
    """Répartition des appareils par plateforme (android / ios / web / autre).

    actives_seulement : si True, ne compte que les sessions appareils encore
        actives (est_active=True), ce qui reflète le parc réellement utilisé.
        Si False, compte l'historique complet.

    Retourne un dict : {'total': N, 'par_plateforme': {...},
                        'appareils_distincts': M}.
    """
    qs = SessionAppareil.objects.all()
    if actives_seulement:
        qs = qs.filter(est_active=True)

    par_plateforme = {p: 0 for p, _ in SessionAppareil.Plateforme.choices}
    for ligne in qs.values('plateforme').annotate(n=Count('id')):
        code = ligne['plateforme']
        if code in par_plateforme:
            par_plateforme[code] = ligne['n']

    # Appareils physiquement distincts (dédupliqués par appareil_id non vide).
    distincts = (
        qs.exclude(appareil_id='')
        .values('appareil_id').distinct().count()
    )

    return {
        'total': qs.count(),
        'appareils_distincts': distincts,
        'par_plateforme': par_plateforme,
    }


def export_appareils_lignes(actives_seulement=True):
    """Prépare (entetes, lignes) pour l'export CSV détaillé des appareils."""
    from django.utils import timezone
    qs = SessionAppareil.objects.select_related('user')
    if actives_seulement:
        qs = qs.filter(est_active=True)
    qs = qs.order_by('-derniere_activite_le')

    entetes = ['id', 'utilisateur', 'role', 'plateforme', 'appareil_nom',
               'appareil_id', 'adresse_ip', 'derniere_activite', 'active']
    lignes = []
    for x in qs.iterator():
        u = x.user
        lignes.append([
            str(x.id),
            getattr(u, 'telephone', ''),
            getattr(u, 'role', ''),
            x.plateforme,
            x.appareil_nom,
            x.appareil_id,
            x.adresse_ip,
            timezone.localtime(x.derniere_activite_le).strftime('%Y-%m-%d %H:%M:%S'),
            'oui' if x.est_active else 'non',
        ])
    return entetes, lignes


def comptes_par_statut():
    """Répartition des comptes par état de modération (santé du parc comptes).

    actifs   : utilisables (ni suspendus, ni bannis, ni supprimés).
    suspendus: suspension réversible en cours (hors bannis).
    bannis   : suspension permanente.
    supprimes: suppression douce (récupérable).
    """
    from django.contrib.auth import get_user_model
    U = get_user_model()
    total = U.objects.count()
    supprimes = U.objects.filter(est_supprime=True).count()
    bannis = U.objects.filter(est_banni=True, est_supprime=False).count()
    suspendus = U.objects.filter(
        est_suspendu=True, est_banni=False, est_supprime=False).count()
    actifs = U.objects.filter(
        est_suspendu=False, est_banni=False, est_supprime=False).count()
    return {
        'total': total,
        'actifs': actifs,
        'suspendus': suspendus,
        'bannis': bannis,
        'supprimes': supprimes,
    }
