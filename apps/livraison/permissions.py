"""Permissions du personnel de gestion TeneLivr (hiérarchie à 3 niveaux).

Regroupées ici plutôt que dans apps.core.permissions pour garder le module
livraison isolé et facilement extractible (voir la docstring de
apps.livraison.models.ProfilLivraison) : TeneLivr est amené à devenir une
plateforme potentiellement détachable de Poufiret.

Hiérarchie (du plus large au plus restreint) :
- coordonnateur_livraison : niveau national, voit toutes les villes.
  Pas de departement sur son profil_livraison.
- superviseur_livraison : responsable du bureau d'UNE ville (departement).
- gestionnaire_livraison : agent du bureau d'une ville (departement).
"""
from rest_framework import permissions


class EstCoordonnateurLivraison(permissions.BasePermission):
    """Coordonnateur de livraison (niveau national, toutes les villes).

    Le super-admin Poufiret (is_superuser) passe aussi, court-circuit.
    """
    message = 'Réservé aux coordonnateurs de livraison.'

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if u.is_superuser:
            return True
        return u.role == u.Role.COORDONNATEUR_LIVRAISON


class EstSuperviseurLivraison(permissions.BasePermission):
    """Superviseur de livraison actif, responsable du bureau d'UNE ville.

    Comme un gestionnaire, mais avec plus de droits sur son département.
    """
    message = 'Réservé aux superviseurs de livraison.'

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if u.role != u.Role.SUPERVISEUR_LIVRAISON:
            return False
        profil = getattr(u, 'profil_livraison', None)
        return bool(profil and profil.est_actif and profil.departement_id)


class EstGestionnaireLivraison(permissions.BasePermission):
    """Gestionnaire de livraison actif, rattaché à une ville.

    Un gestionnaire ne gère que la ville (departement) de son profil.
    """
    message = 'Réservé aux gestionnaires de livraison.'

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if u.role != u.Role.GESTIONNAIRE_LIVRAISON:
            return False
        profil = getattr(u, 'profil_livraison', None)
        return bool(profil and profil.est_actif and profil.departement_id)


class EstPersonnelLivraison(permissions.BasePermission):
    """Gestionnaire, superviseur OU coordonnateur de livraison — endpoints partagés."""
    message = 'Réservé au personnel de livraison.'

    def has_permission(self, request, view):
        return (EstGestionnaireLivraison().has_permission(request, view)
                or EstSuperviseurLivraison().has_permission(request, view)
                or EstCoordonnateurLivraison().has_permission(request, view))
