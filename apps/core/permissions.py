"""
Permissions réutilisables pour toute l'API Poufiret.
"""
from rest_framework import permissions


class LectureSeuleOuAuthentifie(permissions.BasePermission):
    """Lecture publique (GET/HEAD/OPTIONS) ; écriture pour authentifiés."""
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated)


class EstPartenaireProprietaireOuLectureSeule(permissions.BasePermission):
    """
    Lecture publique pour tous.
    Écriture réservée au partenaire propriétaire de l'objet.

    L'objet doit exposer son partenaire via un attribut accessible
    (par défaut 'partenaire', dont on remonte au user proprietaire).
    """
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        # Écriture : il faut être authentifié ET partenaire
        user = request.user
        return bool(
            user and user.is_authenticated
            and user.role == user.Role.PARTENAIRE
        )

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        # obj.partenaire est un ProfilPartenaire ; son .user doit être le requérant
        partenaire = getattr(obj, 'partenaire', None)
        if partenaire is None:
            return False
        return partenaire.user_id == request.user.id
