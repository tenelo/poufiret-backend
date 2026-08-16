"""
Configuration de l'admin Django pour l'app users.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import (User, PlanAbonnement, ProfilPartenaire, HoraireOuverture,
                     AdresseClient, NumeroVerifie, CodeOTP, ParametresSecurite)

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

    def get_urls(self):
        from django.urls import path
        perso = [
            path('creer-partenaire/',
                 self.admin_site.admin_view(self.vue_creer_partenaire),
                 name='users_user_creer_partenaire'),
        ]
        return perso + super().get_urls()

    def vue_creer_partenaire(self, request):
        from django.shortcuts import render, redirect
        from django.contrib import messages
        from apps.users.serializers import CreerPartenaireParAdminSerializer
        from apps.users.models import User, PlanAbonnement, ProfilPartenaire
        from apps.geo.models import Departement

        # Permission : super-admin, ou grille PermissionsAdmin.creer_partenaire
        autorise = request.user.is_superuser
        if not autorise:
            perms = getattr(request.user, 'permissions_admin', None)
            autorise = bool(perms and perms.creer_partenaire)
        if not autorise:
            messages.error(request, "Vous n'avez pas la permission de créer un partenaire.")
            return redirect('admin:users_user_changelist')

        contexte = {
            **self.admin_site.each_context(request),
            'title': 'Créer un partenaire',
            'types_partenaire': ProfilPartenaire.TypePartenaire.choices,
            'plans': PlanAbonnement.objects.all(),
            'departements': Departement.objects.all().order_by('nom'),
            'valeurs': {},
        }

        if request.method == 'POST':
            data = {k: v for k, v in request.POST.items() if k != 'csrfmiddlewaretoken'}
            contexte['valeurs'] = data
            serializer = CreerPartenaireParAdminSerializer(data=data)
            if serializer.is_valid():
                serializer.save()
                contexte['succes'] = serializer.data
                contexte['valeurs'] = {}
                # journalisation best-effort
                try:
                    from apps.administration.models import JournalModeration
                    JournalModeration.objects.create(
                        acteur=request.user, cible=serializer._user,
                        cible_identifiant=serializer._user.telephone,
                        cible_role=serializer._user.role,
                        action=JournalModeration.Action.CREER_PARTENAIRE,
                        motif=f"Création partenaire « {serializer._profil.nom_commerce} » (admin Django)",
                    )
                except Exception:
                    pass
            else:
                contexte['erreurs'] = serializer.errors

        return render(request, 'admin/users/creer_partenaire.html', contexte)

    def get_inline_instances(self, request, obj=None):
        """Affiche les permissions granulaires uniquement pour un admin
        (is_staff, non super-admin). Inutile pour clients/partenaires et
        pour le super-admin (qui peut déjà tout)."""
        if obj and obj.is_staff and not obj.is_superuser:
            return [PermissionsAdminInline(self.model, self.admin_site)]
        return []


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

class HoraireOuvertureInline(admin.TabularInline):
    """Inline pour afficher les horaires sur la fiche du commerçant."""
    model = HoraireOuverture
    extra = 1
    fields = ('jour_semaine', 'ouvert', 'heure_ouverture',
              'heure_fermeture', 'pause_debut', 'pause_fin', 'note')



class CategoriePartenaireInline(admin.TabularInline):
    """Categories du partenaire, gerables depuis sa fiche."""
    from apps.catalog.models import PartenaireCategorie as _PC
    model = _PC
    extra = 1
    autocomplete_fields = ('categorie',)
    fields = ('categorie', 'est_principale', 'image_couverture')
    verbose_name = 'catégorie'
    verbose_name_plural = 'catégories du partenaire'


@admin.register(ProfilPartenaire)
class ProfilPartenaireAdmin(admin.ModelAdmin):
    """Admin pour les profils commerçants — point de contrôle central."""

    
    inlines = [CategoriePartenaireInline, HoraireOuvertureInline]
    list_display = (
        'nom_commerce', 'categories_affichees', 'telephone_user', 'plan', 'statut',
        'est_visible', 'badge_certifie', 'est_faveur', 'created_at',
    )

    @admin.display(description='catégories')
    def categories_affichees(self, obj):
        """Categories du partenaire, la principale marquee d'une etoile."""
        liens = obj.liens_categories.select_related('categorie').all()
        if not liens:
            return '—'
        return ', '.join(
            f'{l.categorie.nom}★' if l.est_principale else l.categorie.nom
            for l in liens
        )
    list_filter = (
        'statut', 'est_visible', 'badge_certifie', 'taxes_communales_ok',
        'est_faveur', 'paye_publicite', 'plan', 'departement', 'ville',
        'source_inscription', 'liens_categories__categorie',
    )
    search_fields = (
        'nom_commerce', 'user__telephone', 'user__username',
        'quartier', 'secteur', 'adresse', 'id_kobo',
    )
    list_editable = ('statut', 'est_visible', 'badge_certifie', 'est_faveur')
    autocomplete_fields = ('user', 'plan', 'faveur_accordee_par')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-created_at',)

    fieldsets = (
        (None, {
            'fields': ('user', 'nom_commerce', 'description', 'logo', 'photo_couverture'),
        }),
        (_('Localisation'), {
            'fields': ('adresse', 'quartier', 'secteur', 'departement', 'ville',
                       'description_acces', 'localisation'),
        }),
        (_('Contact professionnel'), {
            'fields': ('telephone_pro', 'whatsapp', 'email_pro'),
        }),
        (_('Plan & abonnement'), {
            'fields': ('plan', 'abonnement_debut', 'abonnement_fin'),
        }),
        (_('Visibilité & statut'), {
            'fields': ('statut', 'est_visible', 'visibilite_jusquau', 'score_priorite'),
        }),
        (_('Publicité'), {
            'fields': ('paye_publicite', 'pub_active_jusquau'),
        }),
        (_('Certification & taxes'), {
            'fields': ('badge_certifie', 'taxes_communales_ok', 'date_verif_taxes'),
        }),
        (_('Faveur (visibilité offerte)'), {
            'fields': ('est_faveur', 'faveur_accordee_par', 'faveur_motif'),
            'classes': ('collapse',),  # repliable par défaut
        }),
        (_('Notes admin'), {
            'fields': ('notes_admin', 'derniere_verif'),
            'classes': ('collapse',),
        }),
        (_('Traçabilité'), {
            'fields': ('source_inscription', 'id_kobo', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def telephone_user(self, obj):
        """Affiche le téléphone du User lié dans la liste."""
        return obj.user.telephone
    telephone_user.short_description = _('Téléphone')
    telephone_user.admin_order_field = 'user__telephone'



@admin.register(HoraireOuverture)
class HoraireOuvertureAdmin(admin.ModelAdmin):
    """Vue standalone des horaires (utile pour les rares besoins admin)."""
    list_display = ('partenaire', 'jour_semaine', 'ouvert',
                    'heure_ouverture', 'heure_fermeture')
    list_filter = ('jour_semaine', 'ouvert')
    search_fields = ('partenaire__nom_commerce',)
    autocomplete_fields = ('partenaire',)
    ordering = ('partenaire', 'jour_semaine')


@admin.register(AdresseClient)
class AdresseClientAdmin(admin.ModelAdmin):
    """Admin des adresses sauvegardées des clients."""
    list_display = ('libelle', 'user', 'adresse', 'est_principale', 'est_active', 'updated_at')
    list_filter = ('est_principale', 'est_active')
    search_fields = ('libelle', 'adresse', 'user__telephone', 'user__username')
    autocomplete_fields = ('user',)
    list_editable = ('est_principale', 'est_active')
    ordering = ('-updated_at',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(NumeroVerifie)
class NumeroVerifieAdmin(admin.ModelAdmin):
    """
    Registre des numeros deja verifies (anti-double-OTP).
    Un admin peut pre-saisir un numero ici : il ne recevra plus d'OTP.
    """
    list_display = ('telephone', 'prenom', 'nom', 'source', 'cree_le')
    list_filter = ('source',)
    search_fields = ('telephone', 'nom', 'prenom')
    ordering = ('-cree_le',)
    readonly_fields = ('cree_le', 'modifie_le')


@admin.register(CodeOTP)
class CodeOTPAdmin(admin.ModelAdmin):
    """Codes OTP (lecture pratique en dev faux-SMS)."""
    list_display = ('telephone', 'code', 'but', 'est_utilise',
                    'pin_consomme', 'tentatives', 'expire_le', 'cree_le')
    list_filter = ('but', 'est_utilise', 'pin_consomme')
    search_fields = ('telephone',)
    ordering = ('-cree_le',)
    readonly_fields = ('cree_le', 'modifie_le', 'valide_le')


@admin.register(ParametresSecurite)
class ParametresSecuriteAdmin(admin.ModelAdmin):
    """Singleton : parametres de securite des comptes (PIN interdits, suites)."""
    list_display = ('__str__', 'bloquer_suites')

    def has_add_permission(self, request):
        # Un seul enregistrement autorise.
        return not ParametresSecurite.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
