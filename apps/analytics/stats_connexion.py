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
