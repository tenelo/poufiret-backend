"""Statistiques de livraison (lecture seule) pour le tableau de bord admin.

Tout est dérivé de l'existant, sans nouvelle table :
  - livraison.Course : une ligne par course (demandee, assignee, acceptee,
    vers_a, colis_pris, vers_b, livree, refusee, annulee).
  - analytics.VueServiceLivraison : une ligne par ouverture de l'onglet
    livraison (consultation, sans forcément aboutir à une course).

Définition retenue :
  - "abouti" / chiffre d'affaires = uniquement les courses au statut
    Course.Statut.LIVREE (seul état terminal qui correspond à une
    livraison réellement effectuée ; cf. TRANSITIONS dans
    apps.livraison.models, 'livree': [] est l'état final du cycle normal).
"""
from django.db.models import Count, Q, Sum
from django.db.models.functions import ExtractHour, TruncDay, TruncMonth
from django.utils import timezone

from apps.livraison.models import Course
from .models import VueServiceLivraison

LIMITE_TOP = 10


def _courses_periode(debut=None, fin=None):
    """Courses filtrées sur [debut, fin] (bornes incluses), sur cree_le."""
    qs = Course.objects.all()
    if debut is not None:
        qs = qs.filter(cree_le__date__gte=debut)
    if fin is not None:
        qs = qs.filter(cree_le__date__lte=fin)
    return qs


def _consultations_periode(debut=None, fin=None):
    """VueServiceLivraison filtrées sur la même période que les courses."""
    qs = VueServiceLivraison.objects.all()
    if debut is not None:
        qs = qs.filter(cree_le__date__gte=debut)
    if fin is not None:
        qs = qs.filter(cree_le__date__lte=fin)
    return qs


def stats_client(user_id):
    """Stats livraison d'un client : consultations + usages (demandeur/destinataire)."""
    return {
        'nb_consultations': VueServiceLivraison.objects.filter(
            utilisateur_id=user_id).count(),
        'nb_utilisations_demandeur': Course.objects.filter(
            demandeur_id=user_id).count(),
        'nb_utilisations_destinataire': Course.objects.filter(
            contact_user_id=user_id).count(),
    }


def stats_partenaire(partenaire_id):
    """Stats livraison d'un partenaire : courses issues de ses commandes."""
    return {
        'nb_livreurs_commandes': Course.objects.filter(
            commande__partenaire_id=partenaire_id).count(),
    }


def _taux_conversion(courses_qs, consultations_qs):
    nb_consultations = consultations_qs.count()
    nb_courses = courses_qs.count()
    ratio = round(nb_courses / nb_consultations, 3) if nb_consultations else 0.0
    return {
        'nb_consultations': nb_consultations,
        'nb_courses': nb_courses,
        'ratio_courses_par_consultation': ratio,
    }


def _ca_total(courses_qs):
    """Chiffre d'affaires : uniquement les courses LIVREE (voir docstring module)."""
    total = courses_qs.filter(statut=Course.Statut.LIVREE).aggregate(
        total=Sum('prix'))['total']
    return total or 0


def _ca_par_periode(courses_qs):
    livrees = courses_qs.filter(statut=Course.Statut.LIVREE)

    par_jour = (
        livrees.annotate(periode=TruncDay('cree_le'))
        .values('periode').annotate(total=Sum('prix')).order_by('periode')
    )
    par_mois = (
        livrees.annotate(periode=TruncMonth('cree_le'))
        .values('periode').annotate(total=Sum('prix')).order_by('periode')
    )
    par_heure = (
        livrees.annotate(heure=ExtractHour('cree_le'))
        .values('heure').annotate(total=Sum('prix')).order_by('heure')
    )
    return {
        'par_jour': [
            {'periode': l['periode'].strftime('%Y-%m-%d'), 'total': l['total'] or 0}
            for l in par_jour
        ],
        'par_mois': [
            {'periode': l['periode'].strftime('%Y-%m'), 'total': l['total'] or 0}
            for l in par_mois
        ],
        'par_heure': [
            {'heure': l['heure'], 'total': l['total'] or 0}
            for l in par_heure
        ],
    }


def _repartition_demandeurs(courses_qs):
    lignes = (courses_qs.values('type_demandeur')
              .annotate(n=Count('id')).order_by('-n'))
    return [
        {'type_demandeur': l['type_demandeur'] or 'non_precise', 'nb_courses': l['n']}
        for l in lignes
    ]


def _top_villes(courses_qs):
    lignes = (courses_qs.values('ville__nom')
              .annotate(n=Count('id')).order_by('-n')[:LIMITE_TOP])
    return [
        {'ville': l['ville__nom'] or 'non_precise', 'nb_courses': l['n']}
        for l in lignes
    ]


def _top_quartiers_depart(courses_qs):
    lignes = (courses_qs.exclude(a_quartier='').values('a_quartier')
              .annotate(n=Count('id')).order_by('-n')[:LIMITE_TOP])
    return [{'quartier': l['a_quartier'], 'nb_courses': l['n']} for l in lignes]


def _top_categories_partenaire(courses_qs):
    """Top des catégories principales des partenaires, via Course -> commande
    -> partenaire -> PartenaireCategorie (est_principale=True). Ignore les
    courses directes (sans commande liée)."""
    lignes = (
        courses_qs.filter(
            commande__isnull=False,
            commande__partenaire__liens_categories__est_principale=True,
        )
        .values('commande__partenaire__liens_categories__categorie__nom')
        .annotate(n=Count('id')).order_by('-n')[:LIMITE_TOP]
    )
    return [
        {
            'categorie': l['commande__partenaire__liens_categories__categorie__nom']
                         or 'non_precise',
            'nb_courses': l['n'],
        }
        for l in lignes
    ]


def stats_par_ville(courses_qs):
    """Ventilation compacte (nb courses, CA) par département.

    Sert la vue nationale du coordonnateur, pour comparer les villes entre
    elles. Contrairement à _top_villes : pas de LIMITE_TOP (toutes les
    villes ayant au moins une course sur la période), et inclut le CA
    (courses LIVREE, même définition que _ca_total) en plus du décompte.
    """
    lignes = (
        courses_qs.exclude(ville_id__isnull=True)
        .values('ville_id', 'ville__nom')
        .annotate(
            nb_courses=Count('id'),
            ca=Sum('prix', filter=Q(statut=Course.Statut.LIVREE)),
        )
        .order_by('-nb_courses')
    )
    return [
        {
            'ville_id': l['ville_id'],
            'ville_nom': l['ville__nom'] or 'non_precise',
            'nb_courses': l['nb_courses'],
            'ca': l['ca'] or 0,
        }
        for l in lignes
    ]


def tableau_de_bord(debut=None, fin=None, ville_id=None):
    """Assemble le tableau de bord complet des stats de livraison.

    debut / fin : objets date() optionnels, bornent la période (incluses).
    ville_id : optionnel, restreint les courses à ce département (id de
        geo.Departement, correspond à Course.ville_id). None = toutes les
        villes (comportement identique à avant l'ajout de ce paramètre).

    Note : VueServiceLivraison (consultations) n'a pas de notion de ville
    (une ouverture de l'onglet livraison n'est pas rattachée à un
    département) — consultations_qs n'est donc jamais filtré par ville_id,
    même quand les courses le sont. Le ratio de conversion, dans ce cas,
    compare des courses locales à des consultations nationales : à lire en
    conséquence côté ville.
    """
    courses_qs = _courses_periode(debut, fin)
    if ville_id is not None:
        courses_qs = courses_qs.filter(ville_id=ville_id)
    consultations_qs = _consultations_periode(debut, fin)

    return {
        'genere_le': timezone.now().isoformat(),
        'periode': {
            'debut': debut.isoformat() if debut else None,
            'fin': fin.isoformat() if fin else None,
        },
        'taux_conversion': _taux_conversion(courses_qs, consultations_qs),
        'ca_total': _ca_total(courses_qs),
        'ca_par_periode': _ca_par_periode(courses_qs),
        'repartition_demandeurs': _repartition_demandeurs(courses_qs),
        'top_villes': _top_villes(courses_qs),
        'top_quartiers_depart': _top_quartiers_depart(courses_qs),
        'top_categories_partenaire': _top_categories_partenaire(courses_qs),
    }


def export_tableau_de_bord_lignes(debut=None, fin=None):
    """Prépare (entetes, lignes) pour l'export CSV du tableau de bord.

    Format générique (section ; clé ; valeur) car le tableau de bord mélange
    des totaux scalaires et plusieurs listes classées de nature différente.
    """
    donnees = tableau_de_bord(debut, fin)
    entetes = ['section', 'cle', 'valeur']
    lignes = []

    tc = donnees['taux_conversion']
    lignes.append(['resume', 'nb_consultations', tc['nb_consultations']])
    lignes.append(['resume', 'nb_courses', tc['nb_courses']])
    lignes.append(['resume', 'ratio_courses_par_consultation',
                    tc['ratio_courses_par_consultation']])
    lignes.append(['resume', 'ca_total_fcfa', donnees['ca_total']])

    for l in donnees['ca_par_periode']['par_jour']:
        lignes.append(['ca_par_jour', l['periode'], l['total']])
    for l in donnees['ca_par_periode']['par_mois']:
        lignes.append(['ca_par_mois', l['periode'], l['total']])
    for l in donnees['ca_par_periode']['par_heure']:
        lignes.append(['ca_par_heure', f"{l['heure']}h", l['total']])

    for l in donnees['repartition_demandeurs']:
        lignes.append(['repartition_demandeurs', l['type_demandeur'], l['nb_courses']])
    for l in donnees['top_villes']:
        lignes.append(['top_villes', l['ville'], l['nb_courses']])
    for l in donnees['top_quartiers_depart']:
        lignes.append(['top_quartiers_depart', l['quartier'], l['nb_courses']])
    for l in donnees['top_categories_partenaire']:
        lignes.append(['top_categories_partenaire', l['categorie'], l['nb_courses']])

    return entetes, lignes
