"""Statistiques de connexion (lecture seule) pour le tableau de bord admin.

Tout est dérivé de l'existant, sans nouvelle table :
  - TempsSessionUtilisateur : 1 ligne par ouverture de l'app (début, dernier_ping),
    une nouvelle session étant créée à chaque démarrage.
  - User.role : ventilation client / partenaire / livreur / admin.

Définition retenue avec Tenelo :
  - "connexion" = démarrage de l'app (arrivée sur l'accueil) => 1 session.
  - "en ligne maintenant" = dernier_ping de moins de N secondes
    (N = ParametresAnalytics.seuil_en_ligne_secondes, défaut 120).
  - une personne = comptée une seule fois pour le "distinct", même si
    elle ouvre l'app plusieurs fois.

Ces fonctions alimenteront aussi le dashboard super-admin G5 côté Angular.
"""
import statistics

from django.contrib.auth import get_user_model
from django.db.models import Count
from django.utils import timezone
from datetime import timedelta

from .models import TempsSessionUtilisateur, ParametresAnalytics

User = get_user_model()

# Rôles ventilés dans les stats (les autres restent comptés dans le total).
ROLES = ['client', 'partenaire', 'livreur', 'admin']


def _ventiler_par_role(queryset_valeurs):
    """Transforme un values('utilisateur__role').annotate(n) en dict complet."""
    par_role = {r: 0 for r in ROLES}
    for ligne in queryset_valeurs:
        role = ligne['utilisateur__role']
        if role in par_role:
            par_role[role] = ligne['n']
    return par_role


def en_ligne_maintenant():
    """Utilisateurs actuellement dans l'app, total + ventilation par rôle.

    Personnes DISTINCTES (pas les sessions) dont le dernier ping est récent.
    """
    seuil = ParametresAnalytics.obtenir().seuil_en_ligne_secondes
    limite = timezone.now() - timedelta(seconds=seuil)
    actives = TempsSessionUtilisateur.objects.filter(
        est_active=True, dernier_ping__gte=limite,
    )
    # Distinct par utilisateur : une personne avec 2 sessions ne compte qu'une fois.
    ventilation = _ventiler_par_role(
        actives.values('utilisateur__role')
        .annotate(n=Count('utilisateur', distinct=True))
    )
    total = actives.values('utilisateur').distinct().count()
    return {'total': total, 'par_role': ventilation}


def connexions_distinctes(depuis):
    """Personnes distinctes ayant ouvert l'app depuis `depuis`, + ventilation."""
    sessions = TempsSessionUtilisateur.objects.filter(debut__gte=depuis)
    ventilation = _ventiler_par_role(
        sessions.values('utilisateur__role')
        .annotate(n=Count('utilisateur', distinct=True))
    )
    total = sessions.values('utilisateur').distinct().count()
    return {'total': total, 'par_role': ventilation}


def ouvertures(depuis):
    """Nombre total d'ouvertures (sessions) depuis `depuis`, + moyenne/personne.

    Répond au besoin de Tenelo : savoir si quelqu'un ouvre l'app 4-5x/jour.
    """
    sessions = TempsSessionUtilisateur.objects.filter(debut__gte=depuis)
    total = sessions.count()
    personnes = sessions.values('utilisateur').distinct().count()
    moyenne = round(total / personnes, 1) if personnes else 0.0
    return {'total': total, 'personnes': personnes, 'moyenne_par_personne': moyenne}


def comptes_crees():
    """Total des comptes créés + ventilation par rôle."""
    par_role = {r: 0 for r in ROLES}
    for ligne in User.objects.values('role').annotate(n=Count('id')):
        if ligne['role'] in par_role:
            par_role[ligne['role']] = ligne['n']
    return {'total': User.objects.count(), 'par_role': par_role}


def tableau_de_bord():
    """Assemble le tableau de bord complet des stats de connexion."""
    maintenant = timezone.now()
    debut_jour = timezone.localtime().replace(
        hour=0, minute=0, second=0, microsecond=0)
    il_y_a_7j = maintenant - timedelta(days=7)
    il_y_a_30j = maintenant - timedelta(days=30)

    return {
        'genere_le': maintenant.isoformat(),
        'en_ligne': en_ligne_maintenant(),
        'comptes': comptes_crees(),
        'connexions_distinctes': {
            'aujourdhui': connexions_distinctes(debut_jour),
            'sept_jours': connexions_distinctes(il_y_a_7j),
            'trente_jours': connexions_distinctes(il_y_a_30j),
        },
        'ouvertures': {
            'aujourdhui': ouvertures(debut_jour),
            'sept_jours': ouvertures(il_y_a_7j),
            'trente_jours': ouvertures(il_y_a_30j),
        },
    }


def duree_sessions(depuis=None):
    """Indicateurs de durée de session : globale, médiane, par utilisateur,
    par jour.

    `depuis` : datetime optionnelle bornant la période (None = toutes les
    sessions, comme export_sessions_lignes).

    Règle de calcul (identique à TempsSessionUtilisateur.duree_secondes,
    réutilisée telle quelle, pas de nouveau calcul inventé) : durée =
    dernier_ping - debut, en secondes, jamais négative.

    Sessions sans fin : AUCUNE exclusion. Une session encore ouverte
    (est_active=True) a un dernier_ping mis à jour par le heartbeat
    (PingSessionView, toutes les 60s) — dernier_ping - debut mesure donc
    une durée réellement écoulée et fiable, pas une valeur incomplète à
    écarter. C'est aussi le choix déjà fait par export_sessions_lignes,
    qui inclut toutes les sessions (colonne 'active' informative
    seulement, jamais un filtre) : on reste cohérent avec l'existant
    plutôt que d'introduire une nouvelle règle.
    """
    qs = TempsSessionUtilisateur.objects.select_related('utilisateur')
    if depuis is not None:
        qs = qs.filter(debut__gte=depuis)

    durees = []
    par_utilisateur = {}
    par_jour_brut = {}

    for s in qs.iterator():
        d = max(0, int((s.dernier_ping - s.debut).total_seconds()))
        durees.append(d)

        u = s.utilisateur
        entry = par_utilisateur.get(u.id)
        if entry is None:
            entry = par_utilisateur[u.id] = {
                'utilisateur_id': u.id,
                'telephone': getattr(u, 'telephone', ''),
                'nom': u.get_full_name() or u.username or getattr(u, 'telephone', ''),
                'nb_sessions': 0,
                'duree_totale_secondes': 0,
            }
        entry['nb_sessions'] += 1
        entry['duree_totale_secondes'] += d

        jour = timezone.localtime(s.debut).date().isoformat()
        bucket = par_jour_brut.setdefault(jour, {'total': 0, 'n': 0})
        bucket['total'] += d
        bucket['n'] += 1

    nb_sessions = len(durees)
    moyenne = round(statistics.mean(durees), 1) if durees else 0.0
    mediane = round(statistics.median(durees), 1) if durees else 0.0

    par_utilisateur_liste = []
    for entry in par_utilisateur.values():
        entry['duree_moyenne_secondes'] = round(
            entry['duree_totale_secondes'] / entry['nb_sessions'], 1)
        par_utilisateur_liste.append(entry)
    # Tri par défaut : durée totale décroissante (engagement le plus fort
    # en tête) ; liste plate, librement re-triable côté front.
    par_utilisateur_liste.sort(key=lambda e: -e['duree_totale_secondes'])

    par_jour = [
        {
            'date': jour,
            'duree_moyenne_secondes': round(b['total'] / b['n'], 1),
            'nb_sessions': b['n'],
        }
        for jour, b in sorted(par_jour_brut.items())
    ]

    return {
        'duree_moyenne_globale_secondes': moyenne,
        'duree_mediane_globale_secondes': mediane,
        'nb_sessions': nb_sessions,
        'par_utilisateur': par_utilisateur_liste,
        'par_jour': par_jour,
    }


def export_duree_sessions_lignes(depuis=None):
    """Prépare (entetes, lignes) pour l'export CSV des durées par utilisateur."""
    donnees = duree_sessions(depuis)
    entetes = ['utilisateur_id', 'telephone', 'nom', 'nb_sessions',
               'duree_moyenne_secondes', 'duree_totale_secondes']
    lignes = [
        [e['utilisateur_id'], e['telephone'], e['nom'], e['nb_sessions'],
         e['duree_moyenne_secondes'], e['duree_totale_secondes']]
        for e in donnees['par_utilisateur']
    ]
    return entetes, lignes


def export_sessions_lignes(depuis=None):
    """Prépare (entetes, lignes) pour l'export CSV détaillé des sessions.

    Une ligne par ouverture d'app : de quoi recalculer librement dans Excel
    (connexions distinctes, ouvertures/jour, durées, ventilation par rôle).
    `depuis` : datetime optionnelle pour borner la période (None = tout).
    """
    qs = TempsSessionUtilisateur.objects.select_related('utilisateur')
    if depuis is not None:
        qs = qs.filter(debut__gte=depuis)
    qs = qs.order_by('-debut')

    entetes = ['id', 'utilisateur', 'role', 'source', 'debut',
               'dernier_ping', 'duree_secondes', 'active']
    lignes = []
    for x in qs.iterator():
        u = x.utilisateur
        lignes.append([
            str(x.id),
            getattr(u, 'telephone', ''),
            getattr(u, 'role', ''),
            x.source,
            timezone.localtime(x.debut).strftime('%Y-%m-%d %H:%M:%S'),
            timezone.localtime(x.dernier_ping).strftime('%Y-%m-%d %H:%M:%S'),
            x.duree_secondes,
            'oui' if x.est_active else 'non',
        ])
    return entetes, lignes
