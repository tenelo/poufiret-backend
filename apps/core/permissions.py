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


class EstAdmin(permissions.BasePermission):
    """Accès réservé aux administrateurs (is_staff).

    Niveau ADMIN : accès de gestion, mais pas forcément à tout. Les données
    et actions les plus sensibles sont réservées au super-admin (voir
    EstSuperAdmin). Remplace les checks manuels `if not request.user.is_staff`.
    """
    message = 'Réservé aux administrateurs.'

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_staff)


class EstSuperAdmin(permissions.BasePermission):
    """Accès réservé au super-admin (is_superuser = Tenelo).

    Niveau SUPER-ADMIN : accès total aux données et aux manipulations
    sensibles (modération de comptes, suppression, suspension d'un admin).
    Un simple admin (is_staff) ne passe PAS cette permission.
    """
    message = 'Réservé au super-administrateur.'

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_superuser)


class PeutGererAdmins(permissions.BasePermission):
    """Accès réservé à qui peut gérer les comptes admins (créer, éditer
    leurs capacités, révoquer).

    Autorise si l'utilisateur est super-admin (accès total), OU s'il est
    admin (is_staff) ET possède la capacité `gerer_admins` cochée dans son
    PermissionsAdmin. Même logique que ADroitDe, en classe dédiée pour un
    usage explicite (gestion des admins eux-mêmes, distincte des autres
    capacités métier).
    """
    message = "Vous n'avez pas la permission de gérer les comptes admins."

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if u.is_superuser:
            return True
        if not u.is_staff:
            return False
        perms = getattr(u, 'permissions_admin', None)
        if perms is None:
            return False
        return bool(getattr(perms, 'gerer_admins', False))


def ADroitDe(*capacites):
    """Fabrique de permission basée sur la grille PermissionsAdmin.

    Autorise si l'utilisateur est super-admin (accès total), OU s'il est
    admin (is_staff) ET possède TOUTES les capacités demandées cochées
    dans son PermissionsAdmin.

    Usage :
        permission_classes = [IsAuthenticated, ADroitDe('valider_paiement')]
        permission_classes = [IsAuthenticated, ADroitDe('voir_stats')]

    Plusieurs capacités = toutes requises (ET logique).
    """
    class _ADroitDe(permissions.BasePermission):
        message = "Vous n'avez pas la permission pour cette action."

        def has_permission(self, request, view):
            u = request.user
            if not (u and u.is_authenticated):
                return False
            if u.is_superuser:
                return True
            if not u.is_staff:
                return False
            perms = getattr(u, 'permissions_admin', None)
            if perms is None:
                return False
            return all(getattr(perms, cap, False) for cap in capacites)

    _ADroitDe.__name__ = 'ADroitDe_' + '_'.join(capacites)
    return _ADroitDe
