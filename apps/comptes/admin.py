"""Admin du bloc COMPTES : 4 listes proxy filtrées par rôle.

Regroupe Clients / Partenaires / Livreurs / Admins dans un bloc de menu
distinct de USERS. Réutilise les services de modération et de traitement
des demandes de partenariat (apps.administration).
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.users.models import ProfilPartenaire
from apps.comptes.models import Client, Partenaire, Administrateur, Livreur
from apps.administration.admin import PermissionsAdminInline
from apps.administration import moderation, partenaires as svc_partenaires


# ── Listes séparées par rôle (modèles proxy) ─────────────────────────
# On retire l'entrée générique "Utilisateurs" au profit de 4 listes
# claires : Clients / Partenaires / Admins / Livreurs.


class _BaseRoleAdmin(DjangoUserAdmin):
    """Base commune : réutilise les fieldsets/gestion mot de passe de
    UserAdmin, mais filtrée sur un rôle donné."""
    role_cible = None
    list_display = ('telephone', 'get_full_name', 'is_active', 'date_joined')
    search_fields = ('telephone', 'username', 'first_name', 'last_name', 'email')
    ordering = ('-date_joined',)
    actions = ['action_reactiver', 'action_restaurer',
               'action_suspendre', 'action_bannir', 'action_supprimer_soft']

    def has_module_permission(self, request):
        return request.user.is_superuser

    # ── Coeur : execution avec confirmation ──────────────────────────
    def _executer(self, request, queryset, fn, verbe, solo=False):
        """Affiche une page de confirmation, puis applique l'action.

        solo=True : refuse si plus d'un compte est coche (suspendre,
        bannir, supprimer). solo=False : lot autorise (reactiver, restaurer).
        Reserve au super-admin.
        """
        from django.template.response import TemplateResponse

        if not request.user.is_superuser:
            self.message_user(request, "Action reservee au super-admin.", level='error')
            return None

        if solo and queryset.count() > 1:
            self.message_user(
                request,
                f"L'action « {verbe} » ne peut viser qu'UN seul compte a la fois.",
                level='error')
            return None

        # Etape 2 : l'utilisateur a confirme
        if request.POST.get('confirmation') == 'oui':
            n = 0
            for cible in queryset:
                if cible == request.user:
                    continue  # on ne se modere pas soi-meme
                fn(request.user, cible, motif='Action via Django admin')
                n += 1
            self.message_user(request, f"{n} compte(s) : {verbe}.")
            return None

        # Etape 1 : page de confirmation
        contexte = {
            **self.admin_site.each_context(request),
            'titre': f"Confirmer : {verbe}",
            'verbe': verbe,
            'comptes': queryset,
            'action_name': request.POST.get('action'),
            'selection': queryset.values_list('pk', flat=True),
            'opts': self.model._meta,
        }
        return TemplateResponse(
            request, 'admin/confirmation_moderation.html', contexte)

    # ── Lot autorise ─────────────────────────────────────────────────
    @admin.action(description="Réactiver")
    def action_reactiver(self, request, queryset):
        return self._executer(request, queryset, moderation.reactiver, "Réactivé")

    @admin.action(description="Restaurer")
    def action_restaurer(self, request, queryset):
        return self._executer(request, queryset, moderation.restaurer, "Restauré")

    # ── Un seul a la fois ────────────────────────────────────────────
    @admin.action(description="Suspendre")
    def action_suspendre(self, request, queryset):
        return self._executer(request, queryset, moderation.suspendre, "Suspendu", solo=True)

    @admin.action(description="Bannir")
    def action_bannir(self, request, queryset):
        return self._executer(request, queryset, moderation.bannir, "Banni", solo=True)

    @admin.action(description="Supprimer")
    def action_supprimer_soft(self, request, queryset):
        return self._executer(request, queryset, moderation.supprimer_soft, "Supprimé", solo=True)

    def get_actions(self, request):
        """Retire l'action « supprimer » native de Django (dangereuse)."""
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(role=self.role_cible)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.role = self.role_cible
        super().save_model(request, obj, form, change)


@admin.register(Client)
class ClientAdmin(_BaseRoleAdmin):
    role_cible = 'client'


@admin.register(Partenaire)
class PartenaireAdmin(_BaseRoleAdmin):
    role_cible = 'partenaire'
    actions = _BaseRoleAdmin.actions + ['action_accepter_demande',
                                        'action_rejeter_demande']
    list_display = ('telephone', 'enseigne', 'nom_complet', 'type_part',
                    'departement_part', 'categories_part', 'statut_partenaire',
                    'is_active')
    list_filter = ('profil_partenaire__statut', 'profil_partenaire__type_partenaire',
                   'is_active')

    @admin.display(description='enseigne')
    def enseigne(self, obj):
        p = getattr(obj, 'profil_partenaire', None)
        return p.nom_commerce if p else '—'

    @admin.display(description='nom & prénom')
    def nom_complet(self, obj):
        return obj.get_full_name() or '—'

    @admin.display(description='type')
    def type_part(self, obj):
        p = getattr(obj, 'profil_partenaire', None)
        return p.get_type_partenaire_display() if p else '—'

    @admin.display(description='département')
    def departement_part(self, obj):
        p = getattr(obj, 'profil_partenaire', None)
        return getattr(p.departement, 'nom', '—') if p else '—'

    @admin.display(description='catégories')
    def categories_part(self, obj):
        p = getattr(obj, 'profil_partenaire', None)
        if not p:
            return '—'
        noms = [l.categorie.nom for l in p.liens_categories.all()]
        return ', '.join(noms) if noms else '—'

    @admin.display(description='statut', ordering='profil_partenaire__statut')
    def statut_partenaire(self, obj):
        p = getattr(obj, 'profil_partenaire', None)
        return p.get_statut_display() if p else '—'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related(
            'profil_partenaire', 'profil_partenaire__departement'
        ).prefetch_related('profil_partenaire__liens_categories__categorie')

    def _decision_demande(self, request, queryset, fn, verbe):
        """Accepte/rejette des demandes EN_ATTENTE, avec confirmation."""
        from django.template.response import TemplateResponse
        from apps.users.models import ProfilPartenaire

        if not request.user.is_superuser:
            self.message_user(request, "Action reservee au super-admin.", level='error')
            return None

        # On ne traite que les profils EN_ATTENTE des users selectionnes
        profils = ProfilPartenaire.objects.select_related('user').filter(
            user__in=queryset, statut=ProfilPartenaire.Statut.EN_ATTENTE)
        if not profils:
            self.message_user(
                request, "Aucune demande en attente dans la selection.",
                level='warning')
            return None

        if request.POST.get('confirmation') == 'oui':
            n = 0
            for profil in profils:
                fn(request.user, profil, motif='Decision via Django admin')
                n += 1
            self.message_user(request, f"{n} demande(s) : {verbe}.")
            return None

        contexte = {
            **self.admin_site.each_context(request),
            'titre': f"Confirmer : {verbe}",
            'verbe': verbe,
            'comptes': [p.user for p in profils],
            'action_name': request.POST.get('action'),
            'selection': queryset.values_list('pk', flat=True),
            'opts': self.model._meta,
        }
        return TemplateResponse(
            request, 'admin/confirmation_moderation.html', contexte)

    @admin.action(description="Accepter la demande de partenariat")
    def action_accepter_demande(self, request, queryset):
        return self._decision_demande(
            request, queryset, svc_partenaires.accepter_partenaire, "acceptee(s)")

    @admin.action(description="Rejeter la demande de partenariat")
    def action_rejeter_demande(self, request, queryset):
        return self._decision_demande(
            request, queryset, svc_partenaires.rejeter_partenaire, "rejetee(s)")


@admin.register(Livreur)
class LivreurAdmin(_BaseRoleAdmin):
    role_cible = 'livreur'


@admin.register(Administrateur)
class AdministrateurAdmin(_BaseRoleAdmin):
    """Liste des admins + grille de permissions granulaires.

    Colonne 'super-admin ?' pour distinguer le propriétaire (toi) des
    admins délégués. L'inline permissions ne s'affiche que pour un admin
    délégué (is_staff, non super-admin)."""
    role_cible = 'admin'
    list_display = ('telephone', 'get_full_name', 'is_superuser',
                    'is_active', 'date_joined')
    list_filter = ('is_superuser', 'is_active')

    def get_inline_instances(self, request, obj=None):
        if obj and obj.is_staff and not obj.is_superuser:
            return [PermissionsAdminInline(self.model, self.admin_site)]
        return []


