"""Visibilité publique des partenaires — règle UNIQUE.

Un partenaire n'apparaît dans une réponse publique (annuaire, vitrine,
articles, restaurants, locations, recherche, carte, publicités…) que s'il est
à la fois :
- actif (ProfilPartenaire.statut = « actif » : ni en attente, ni suspendu,
  ni banni, ni rejeté) ;
- visible (ProfilPartenaire.est_visible ; « inactif » = est_visible False,
  bascule admin masquer_partenaire) ;
- porté par un compte utilisable (User.is_active, et ni est_suspendu, ni
  est_banni, ni est_supprime — la modération synchronise déjà le profil, ces
  drapeaux sont une ceinture de sécurité).
"""
from django.db.models import Q


def q_partenaire_public(prefixe=''):
    """Q() sur ProfilPartenaire (prefixe='') ou via une relation
    (ex. prefixe='partenaire__', 'article__partenaire__')."""
    p = prefixe
    return Q(**{
        f'{p}statut': 'actif',
        f'{p}est_visible': True,
        f'{p}user__is_active': True,
        f'{p}user__est_suspendu': False,
        f'{p}user__est_banni': False,
        f'{p}user__est_supprime': False,
    })


def partenaire_est_public(partenaire):
    """Même règle sur une instance (déjà chargée)."""
    if partenaire is None:
        return False
    u = partenaire.user
    return (partenaire.statut == 'actif' and partenaire.est_visible and u.is_active
            and not u.est_suspendu and not u.est_banni and not u.est_supprime)


def filtrer_liste_admin(qs, params, prefixe=''):
    """Listes admin de partenaires : ?visible=1|0 (est_visible) ; supprimés
    (soft) exclus par défaut, ?supprimes=1 → uniquement les supprimés
    (corbeille, pour les restaurer)."""
    p = prefixe
    if params.get('visible') in ('1', '0'):
        qs = qs.filter(**{f'{p}est_visible': params['visible'] == '1'})
    qs = qs.filter(**{f'{p}user__est_supprime': params.get('supprimes') == '1'})
    return qs


def etat_admin(partenaire):
    """Colonnes d'état pour les listes admin."""
    return {'est_visible': partenaire.est_visible, 'est_supprime': partenaire.user.est_supprime,
            'est_public': partenaire_est_public(partenaire)}
