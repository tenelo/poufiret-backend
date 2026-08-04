"""Indicateurs métier sur les partenaires (super-admin, lecture seule).

Vue business du réseau de partenaires, dérivée de ProfilPartenaire sans
nouvelle table : répartition par plan / type / département / statut,
comptage des certifiés et des faveurs, et surtout les abonnements qui
expirent bientôt (en tranches exclusives, pour prioriser les relances).
"""
from datetime import timedelta
from django.db.models import Count
from django.utils import timezone

from apps.users.models import ProfilPartenaire


def _compter_par(champ):
    """Répartition {valeur: n} sur un champ de ProfilPartenaire."""
    lignes = (
        ProfilPartenaire.objects.values(champ)
        .annotate(n=Count('id')).order_by('-n')
    )
    return {(l[champ] or 'non_defini'): l['n'] for l in lignes}


def par_plan():
    """Répartition par plan (nom du plan) — qui paie quoi."""
    lignes = (
        ProfilPartenaire.objects.values('plan__libelle')
        .annotate(n=Count('id')).order_by('-n')
    )
    return {(l['plan__libelle'] or 'sans_plan'): l['n'] for l in lignes}


def par_departement():
    """Répartition par département (nom) — couverture géographique."""
    lignes = (
        ProfilPartenaire.objects.values('departement__nom')
        .annotate(n=Count('id')).order_by('-n')
    )
    return {(l['departement__nom'] or 'non_defini'): l['n'] for l in lignes}


def expirations():
    """Abonnements par urgence d'expiration, en tranches EXCLUSIVES.

    Chaque partenaire est compté une seule fois, dans la tranche la plus
    urgente qui le concerne. 'deja_expire' = date de fin déjà passée.
    Les partenaires sans abonnement_fin sont ignorés (pas d'échéance).
    """
    today = timezone.localdate()
    qs = ProfilPartenaire.objects.filter(abonnement_fin__isnull=False)

    deja = qs.filter(abonnement_fin__lt=today).count()
    demain = qs.filter(
        abonnement_fin__gte=today,
        abonnement_fin__lte=today + timedelta(days=1)).count()
    sous_5j = qs.filter(
        abonnement_fin__gt=today + timedelta(days=1),
        abonnement_fin__lte=today + timedelta(days=5)).count()
    sous_15j = qs.filter(
        abonnement_fin__gt=today + timedelta(days=5),
        abonnement_fin__lte=today + timedelta(days=15)).count()
    sous_30j = qs.filter(
        abonnement_fin__gt=today + timedelta(days=15),
        abonnement_fin__lte=today + timedelta(days=30)).count()

    return {
        'deja_expire': deja,
        'demain': demain,
        'sous_5j': sous_5j,
        'sous_15j': sous_15j,
        'sous_30j': sous_30j,
    }


def tableau_de_bord():
    """Assemble tous les indicateurs partenaires."""
    total = ProfilPartenaire.objects.count()
    return {
        'total': total,
        'par_plan': par_plan(),
        'par_type': _compter_par('type_partenaire'),
        'par_departement': par_departement(),
        'par_statut': _compter_par('statut'),
        'certifies': ProfilPartenaire.objects.filter(badge_certifie=True).count(),
        'en_faveur': ProfilPartenaire.objects.filter(est_faveur=True).count(),
        'actifs': ProfilPartenaire.objects.filter(statut='actif').count(),
        'visibles': ProfilPartenaire.objects.filter(est_visible=True).count(),
        'expirations': expirations(),
    }


def export_partenaires_lignes():
    """Prépare (entetes, lignes) pour l'export CSV détaillé des partenaires."""
    qs = ProfilPartenaire.objects.select_related(
        'user', 'plan', 'departement').order_by('nom_commerce')
    entetes = ['nom_commerce', 'telephone', 'type', 'plan', 'departement',
               'statut', 'abonnement_fin', 'certifie', 'faveur', 'visible',
               'nb_vues']
    lignes = []
    for p in qs.iterator():
        lignes.append([
            p.nom_commerce,
            getattr(p.user, 'telephone', ''),
            p.type_partenaire,
            getattr(p.plan, 'libelle', ''),
            getattr(p.departement, 'nom', ''),
            p.statut,
            p.abonnement_fin.strftime('%Y-%m-%d') if p.abonnement_fin else '',
            'oui' if p.badge_certifie else 'non',
            'oui' if p.est_faveur else 'non',
            'oui' if p.est_visible else 'non',
            p.nb_vues,
        ])
    return entetes, lignes
