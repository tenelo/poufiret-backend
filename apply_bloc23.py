#!/usr/bin/env python3
"""Applique le Bloc 2 (stats individuelles) + Bloc 3 (tableau de bord admin)
du tracking analytics livraison, sur le dessus du Bloc 1 (VueServiceLivraison)
deja applique.

A lancer depuis la racine du projet (~/data/poufiret-backend) :
    python3 apply_bloc23.py

Idempotent : si les fichiers ont deja ete modifies, le script le detecte
et ne touche a rien (message "deja applique").
Ne fait AUCUN commit, AUCUN push, AUCUNE commande docker.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
VIEWS = ROOT / 'apps' / 'analytics' / 'views.py'
URLS = ROOT / 'apps' / 'analytics' / 'urls.py'
STATS_LIVRAISON = ROOT / 'apps' / 'analytics' / 'stats_livraison.py'


STATS_LIVRAISON_CONTENU = '''"""Statistiques de livraison (lecture seule) pour le tableau de bord admin.

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
from django.db.models import Count, Sum
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


def tableau_de_bord(debut=None, fin=None):
    """Assemble le tableau de bord complet des stats de livraison.

    debut / fin : objets date() optionnels, bornent la période (incluses).
    """
    courses_qs = _courses_periode(debut, fin)
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
'''


VIEWS_AJOUT = '''

def _bornes_periode(request):
    """Lit ?debut=YYYY-MM-DD&fin=YYYY-MM-DD. Retourne (debut, fin, erreur)."""
    from datetime import datetime
    debut = fin = None
    try:
        if request.query_params.get('debut'):
            debut = datetime.strptime(request.query_params['debut'], '%Y-%m-%d').date()
        if request.query_params.get('fin'):
            fin = datetime.strptime(request.query_params['fin'], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None, None, True
    return debut, fin, False


class LivraisonStatsClientView(APIView):
    """GET livraison/client/<user_id>/ — stats livraison d'un client (admin).

    Consultations de l'onglet livraison + usages réels (demandeur/destinataire).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id=None):
        if not request.user.is_staff:
            return Response({'detail': 'Réservé aux administrateurs.'},
                            status=status.HTTP_403_FORBIDDEN)
        from .stats_livraison import stats_client
        return Response(stats_client(user_id))


class LivraisonStatsPartenaireView(APIView):
    """GET livraison/partenaire/<partenaire_id>/ — stats livraison d'un partenaire (admin).

    Nombre de courses issues d'une commande de ce partenaire.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, partenaire_id=None):
        if not request.user.is_staff:
            return Response({'detail': 'Réservé aux administrateurs.'},
                            status=status.HTTP_403_FORBIDDEN)
        from .stats_livraison import stats_partenaire
        return Response(stats_partenaire(partenaire_id))


class LivraisonTableauDeBordView(APIView):
    """GET livraison/tableau-de-bord/ — tableau de bord livraison (admin/Angular).

    Agrège TOUTES les courses : taux de conversion, CA (courses livrées),
    CA par jour/mois/heure, répartition par type de demandeur, top villes,
    top quartiers de départ, top catégories de partenaire.
    Filtre de période optionnel : ?debut=YYYY-MM-DD&fin=YYYY-MM-DD.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.is_staff:
            return Response({'detail': 'Réservé aux administrateurs.'},
                            status=status.HTTP_403_FORBIDDEN)
        debut, fin, erreur = _bornes_periode(request)
        if erreur:
            return Response({'detail': 'Format de date invalide (attendu YYYY-MM-DD).'},
                            status=status.HTTP_400_BAD_REQUEST)
        from .stats_livraison import tableau_de_bord
        return Response(tableau_de_bord(debut, fin))


class LivraisonTableauDeBordExportView(APIView):
    """Export CSV du tableau de bord livraison (admin).

    Mêmes données que LivraisonTableauDeBordView, à plat (section ; clé ; valeur).
    Filtre de période optionnel : ?debut=YYYY-MM-DD&fin=YYYY-MM-DD.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.is_staff:
            return Response({'detail': 'Réservé aux administrateurs.'},
                            status=status.HTTP_403_FORBIDDEN)
        debut, fin, erreur = _bornes_periode(request)
        if erreur:
            return Response({'detail': 'Format de date invalide (attendu YYYY-MM-DD).'},
                            status=status.HTTP_400_BAD_REQUEST)
        from apps.core.exports import reponse_csv
        from .stats_livraison import export_tableau_de_bord_lignes
        entetes, lignes = export_tableau_de_bord_lignes(debut, fin)
        return reponse_csv('livraison_tableau_de_bord', entetes, lignes)
'''

VIEWS_ANCRE = (
    "        entetes, lignes = export_sessions_lignes(depuis)\n"
    "        return reponse_csv('stats_connexion_sessions', entetes, lignes)\n"
)

URLS_IMPORT_AVANT = (
    "from .views import (DemarrerSessionView, EngagementAdminView, "
    "OuvertureDemandeInterventionView, PingSessionView, StatsConnexionAdminView, "
    "StatsConnexionExportView, VisiteCategorieView, VueServiceLivraisonView, VueVitrineView)"
)
URLS_IMPORT_APRES = (
    "from .views import (DemarrerSessionView, EngagementAdminView, "
    "LivraisonStatsClientView, LivraisonStatsPartenaireView, "
    "LivraisonTableauDeBordExportView, LivraisonTableauDeBordView, "
    "OuvertureDemandeInterventionView, PingSessionView, StatsConnexionAdminView, "
    "StatsConnexionExportView, VisiteCategorieView, VueServiceLivraisonView, VueVitrineView)"
)

URLS_ANCRE_ROUTE = (
    "    path('livraison/vue/', VueServiceLivraisonView.as_view(), name='livraison-vue'),\n"
)
URLS_NOUVELLES_ROUTES = (
    "    path('livraison/vue/', VueServiceLivraisonView.as_view(), name='livraison-vue'),\n"
    "    path('livraison/client/<int:user_id>/', LivraisonStatsClientView.as_view(), name='livraison-stats-client'),\n"
    "    path('livraison/partenaire/<int:partenaire_id>/', LivraisonStatsPartenaireView.as_view(), name='livraison-stats-partenaire'),\n"
    "    path('livraison/tableau-de-bord/', LivraisonTableauDeBordView.as_view(), name='livraison-tableau-de-bord'),\n"
    "    path('livraison/tableau-de-bord/export/', LivraisonTableauDeBordExportView.as_view(), name='livraison-tableau-de-bord-export'),\n"
)


def echec(message):
    print(f"ERREUR : {message}", file=sys.stderr)
    sys.exit(1)


def ecrire_stats_livraison():
    if STATS_LIVRAISON.exists() and 'def tableau_de_bord' in STATS_LIVRAISON.read_text():
        print(f"[deja applique] {STATS_LIVRAISON} existe deja, inchange.")
        return
    STATS_LIVRAISON.write_text(STATS_LIVRAISON_CONTENU)
    print(f"[cree] {STATS_LIVRAISON}")


def modifier_views():
    if not VIEWS.exists():
        echec(f"{VIEWS} introuvable. Lance ce script depuis la racine du projet.")
    contenu = VIEWS.read_text()
    if 'class LivraisonTableauDeBordExportView' in contenu:
        print(f"[deja applique] {VIEWS} contient deja le Bloc 2/3, inchange.")
        return
    if contenu.count(VIEWS_ANCRE) != 1:
        echec(
            f"{VIEWS} ne correspond pas au contenu attendu (Bloc 1 introuvable "
            "ou fichier deja different). Applique d'abord le script du Bloc 1, "
            "ou verifie manuellement le fichier avant de relancer."
        )
    contenu = contenu.replace(VIEWS_ANCRE, VIEWS_ANCRE + VIEWS_AJOUT, 1)
    contenu = contenu.rstrip('\n') + '\n'
    VIEWS.write_text(contenu)
    print(f"[modifie] {VIEWS}")


def modifier_urls():
    if not URLS.exists():
        echec(f"{URLS} introuvable. Lance ce script depuis la racine du projet.")
    contenu = URLS.read_text()
    if 'LivraisonTableauDeBordExportView' in contenu:
        print(f"[deja applique] {URLS} contient deja le Bloc 2/3, inchange.")
        return
    if URLS_IMPORT_AVANT not in contenu:
        echec(
            f"{URLS} : ligne d'import attendue introuvable. Le fichier a peut-etre "
            "deja ete modifie manuellement — verifie avant de relancer."
        )
    if contenu.count(URLS_ANCRE_ROUTE) != 1:
        echec(f"{URLS} : route 'livraison/vue/' introuvable (Bloc 1 pas applique ?).")
    contenu = contenu.replace(URLS_IMPORT_AVANT, URLS_IMPORT_APRES, 1)
    contenu = contenu.replace(URLS_ANCRE_ROUTE, URLS_NOUVELLES_ROUTES, 1)
    URLS.write_text(contenu)
    print(f"[modifie] {URLS}")


def main():
    ecrire_stats_livraison()
    modifier_views()
    modifier_urls()
    print("\nTermine. Aucun commit, aucun push, aucune commande docker executee.")
    print("Prochaine etape (a lancer toi-meme) : docker restart backend-poufiret")


if __name__ == '__main__':
    main()
