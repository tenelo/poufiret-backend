"""
Configuration de l'admin Django pour l'app users.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import User, PlanAbonnement


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """
    Admin pour le User custom de Poufiret.
    Hérite de UserAdmin standard mais expose nos champs custom.
    """
    list_display = ('telephone', 'username', 'get_full_name', 'role',
                    'est_verifie', 'is_active', 'date_joined')
    list_filter = ('role', 'est_verifie', 'is_active', 'is_staff', 'is_superuser')
    search_fields = ('telephone', 'username', 'first_name', 'last_name', 'email')
    ordering = ('-date_joined',)

    # Champs affichés sur la fiche détail
    fieldsets = (
        (None, {'fields': ('telephone', 'username', 'password')}),
        (_('Informations personnelles'), {
            'fields': ('first_name', 'last_name', 'email', 'photo_profil')
            if False else ('first_name', 'last_name', 'email')
        }),
        (_('Rôle et vérification'), {
            'fields': ('role', 'est_verifie', 'langue_preferee', 'token_fcm'),
        }),
        (_('Permissions'), {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        (_('Dates importantes'), {
            'fields': ('last_login', 'date_joined'),
        }),
    )

    # Champs affichés lors de la création (formulaire raccourci)
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('telephone', 'username', 'password1', 'password2',
                       'role', 'first_name', 'last_name'),
        }),
    )


@admin.register(PlanAbonnement)
class PlanAbonnementAdmin(admin.ModelAdmin):
    """Admin pour les plans d'abonnement."""
    list_display = ('libelle', 'code', 'prix', 'duree_jours',
                    'nb_articles_max', 'nb_photos_par_article', 'est_actif', 'ordre')
    list_filter = ('code', 'est_actif', 'peut_publier_video', 'peut_etre_mis_en_avant')
    search_fields = ('libelle', 'code', 'description')
    list_editable = ('prix', 'est_actif', 'ordre')
    ordering = ('ordre', 'prix')

    fieldsets = (
        (None, {
            'fields': ('code', 'libelle', 'description', 'est_actif'),
        }),
        (_('Tarif et durée'), {
            'fields': ('prix', 'duree_jours'),
        }),
        (_('Limites'), {
            'fields': ('nb_articles_max', 'nb_photos_par_article'),
        }),
        (_('Avantages'), {
            'fields': ('peut_publier_video', 'peut_etre_mis_en_avant', 'boost_visibilite'),
        }),
        (_('Affichage'), {
            'fields': ('ordre',),
        }),
    )