"""Permissions réutilisables Poufiret."""
from rest_framework import permissions


def _partenaire_de(obj):
    p = getattr(obj, 'partenaire', None)
    if p is not None:
        return p
    art = getattr(obj, 'article', None)
    return getattr(art, 'partenaire', None) if art is not None else None


class LectureSeuleOuAuthentifie(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated)


class EstPartenaireProprietaireOuLectureSeule(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        u = request.user
        return bool(u and u.is_authenticated and u.role == u.Role.PARTENAIRE)

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        p = _partenaire_de(obj)
        return p is not None and p.user_id == request.user.id


class EstAuteurOuModerateurOuLectureSeule(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        u = request.user
        if obj.user_id == u.id:
            return True
        if u.role == u.Role.ADMIN or u.is_staff:
            return True
        cible_part = _partenaire_de(obj)
        return cible_part is not None and cible_part.user_id == u.id
