from django.contrib import admin

from .models import JournalModeration, PermissionsAdmin


@admin.register(JournalModeration)
class JournalModerationAdmin(admin.ModelAdmin):
    list_display = ('cree_le', 'action', 'cible_identifiant', 'cible_role',
                    'acteur', 'motif')
    list_filter = ('action', 'cible_role', 'cree_le')
    search_fields = ('cible_identifiant', 'motif')
    readonly_fields = ('acteur', 'cible', 'cible_identifiant', 'cible_role',
                       'action', 'motif', 'cree_le', 'modifie_le')

    def has_add_permission(self, request):
        # Le journal se remplit uniquement via les actions de modération.
        return False

    def has_delete_permission(self, request, obj=None):
        # Audit : on ne supprime pas les entrées.
        return False


class PermissionsAdminInline(admin.StackedInline):
    """Grille de cases à cocher, groupée par sections, sur la fiche admin.

    N'apparaît que pour les comptes staff (admins). Super-admin = tout,
    donc l'inline est masqué pour lui (ses cases ne servent à rien).
    """
    model = PermissionsAdmin
    can_delete = False
    verbose_name_plural = 'Permissions granulaires (admin)'
    fieldsets = (
        ('A. Modération — suspendre', {
            'fields': ('suspendre_client', 'suspendre_partenaire', 'suspendre_admin')}),
        ('A. Modération — réactiver', {
            'fields': ('reactiver_client', 'reactiver_partenaire', 'reactiver_admin')}),
        ('A. Modération — bannir', {
            'fields': ('bannir_client', 'bannir_partenaire', 'bannir_admin')}),
        ('A. Modération — supprimer (douce)', {
            'fields': ('supprimer_soft_client', 'supprimer_soft_partenaire', 'supprimer_soft_admin')}),
        ('A. Modération — supprimer (définitive)', {
            'fields': ('supprimer_hard_client', 'supprimer_hard_partenaire', 'supprimer_hard_admin')}),
        ('A. Modération — restaurer', {
            'fields': ('restaurer_client', 'restaurer_partenaire', 'restaurer_admin')}),
        ('B. Partenaires', {
            'fields': ('masquer_partenaire', 'certifier_partenaire',
                       'accorder_faveur', 'valider_devenir_partenaire')}),
        ('C. Publicités', {
            'fields': ('valider_publicite', 'offrir_campagne')}),
        ('D. Commandes & paiements', {
            'fields': ('valider_commande', 'valider_paiement')}),
        ('E. Configuration', {
            'fields': ('modifier_plans_formules',)}),
        ('F. Consultation & données', {
            'fields': ('voir_stats', 'voir_indicateurs', 'lire_journal', 'exporter_csv')}),
    )

