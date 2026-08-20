from django.contrib import admin, messages

from .models import (
    CreditFormulePub, FormulePublicite, ImagePublicite, ImpressionPublicite,
    ParametresPublicite, Publicite,
)


@admin.register(FormulePublicite)
class FormuleAdmin(admin.ModelAdmin):
    def get_list_display(self, request):
        base = list(super().get_list_display(request))
        for colonne in ('occupation', 'quotas_par_emplacement', 'detail_statuts'):
            if colonne not in base:
                base.insert(1, colonne)
        return base

    @admin.display(description='passages / jour')
    def quotas_par_emplacement(self, obj):
        """Detail des passages par emplacement, ou quota global si vide."""
        from django.utils.html import format_html
        par_type = obj.passages_par_type or {}
        if not par_type:
            return format_html(
                '<span style="font-size:11px;color:#e8590c">{} '
                '(tous emplacements confondus)</span>',
                obj.passages_par_jour)
        libelles = {'carrousel': 'Carrousel', 'interstitiel': 'Plein écran',
                    'bandeau_bas': 'Bandeau', 'page_publicites': 'Page pubs'}
        texte = ' · '.join(
            f'{libelles.get(k, k)} : {v}' for k, v in par_type.items())
        return format_html('<span style="font-size:11px">{}</span>', texte)

    @admin.display(description='places occupées')
    def occupation(self, obj):
        """Pubs actives / quota d'annonceurs simultanes."""
        from django.utils.html import format_html
        from .models import Publicite
        actives = Publicite.objects.filter(
            formule=obj, statut=Publicite.Statut.ACTIVE).count()
        quota = obj.quota_partenaires or 0
        if quota <= 0:
            return format_html('<b>{}</b> / illimité', actives)
        couleur = ('#c92a2a' if actives >= quota
                   else '#e8590c' if actives / quota >= 0.75
                   else '#2b8a3e')
        return format_html(
            '<b style="color:{}">{} / {}</b>', couleur, actives, quota)

    @admin.display(description='campagnes (tous statuts)')
    def detail_statuts(self, obj):
        """Repartition des campagnes de cette formule par statut."""
        from django.db.models import Count
        from django.utils.html import format_html
        from .models import Publicite
        libelles = dict(Publicite.Statut.choices)
        lignes = (Publicite.objects.filter(formule=obj)
                  .values('statut').annotate(n=Count('id')))
        if not lignes:
            return '—'
        texte = ' · '.join(
            f"{libelles.get(l['statut'], l['statut'])} : {l['n']}"
            for l in lignes)
        return format_html('<span style="font-size:11px">{}</span>', texte)

    list_display = ('nom', 'prix', 'priorite', 'duree_jours', 'passages_par_jour',
                    'quota_partenaires', 'acces_heures_affluence',
                    'cible_pourcentage_actifs', 'est_active')
    list_filter = ('est_active', 'acces_heures_affluence', 'video_autorisee')


class ImagePubliciteInline(admin.TabularInline):
    model = ImagePublicite
    extra = 0


@admin.register(Publicite)
class PubliciteAdmin(admin.ModelAdmin):
    list_display = ('titre', 'partenaire', 'formule', 'statut',
                    'nb_personnes_touchees', 'nb_impressions', 'nb_clics',
                    'stats_visibles_partenaire', 'debut_diffusion', 'fin_diffusion')
    list_filter = ('statut', 'formule', 'stats_visibles_partenaire')
    search_fields = ('titre', 'partenaire__nom_commerce')
    inlines = [ImagePubliciteInline]
    readonly_fields = ('debut_diffusion', 'fin_diffusion')

    def get_list_display(self, request):
        return ('titre', 'partenaire', 'formule', 'statut', 'boutons',
                'nb_personnes_touchees', 'nb_impressions', 'nb_clics',
                'personnes_ayant_clique', 'debut_diffusion', 'fin_diffusion')

    @admin.display(description='personnes ayant cliqué')
    def personnes_ayant_clique(self, obj):
        """Cliqueurs distincts : un utilisateur qui reclique compte une fois.

        Compare a nb_clics, cela distingue un interet reel et large d'un
        seul utilisateur insistant. Les visiteurs non connectes ne sont
        pas comptes ici (pas d'identite a dedupliquer).
        """
        from django.utils.html import format_html
        from .models import ImpressionPublicite
        if not obj.nb_clics:
            return '—'
        distincts = (ImpressionPublicite.objects
                     .filter(publicite=obj, cliquee=True,
                             utilisateur__isnull=False)
                     .values('utilisateur').distinct().count())
        # round() avant format_html : les arguments deviennent des
        # SafeString, que les codes de format numeriques rejettent.
        taux = (round(distincts / obj.nb_personnes_touchees * 100)
                if obj.nb_personnes_touchees else 0)
        return format_html(
            '<b>{}</b> <span style="font-size:11px;color:#868e96">'
            '({}% des touchés)</span>', distincts, taux)

    def get_urls(self):
        from django.urls import path
        perso = [
            path('<uuid:pk>/faire/<str:action>/',
                 self.admin_site.admin_view(self.vue_transition),
                 name='publicites_publicite_transition'),
        ]
        return perso + super().get_urls()

    def vue_transition(self, request, pk, action):
        """Applique une transition depuis un bouton de la liste."""
        from django.shortcuts import redirect
        from .models import Publicite
        from .services import appliquer_transition

        pub = Publicite.objects.filter(pk=pk).select_related('formule').first()
        if pub is None:
            self.message_user(request, 'Publicité introuvable.', messages.ERROR)
        else:
            ok, message = appliquer_transition(pub, action)
            self.message_user(
                request, f'{pub.titre} — {message}',
                messages.SUCCESS if ok else messages.WARNING)
        retour = request.META.get('HTTP_REFERER')
        return redirect(retour or '../../')

    @admin.display(description='actions')
    def boutons(self, obj):
        """Boutons contextuels : seules les transitions possibles."""
        from django.urls import reverse
        from django.utils.html import format_html_join
        from .services import TRANSITIONS

        style = ('padding:3px 8px;margin:0 2px;border-radius:4px;'
                 'text-decoration:none;font-size:11px;white-space:nowrap;'
                 'display:inline-block;background:{};color:#fff;')
        couleurs = {
            'confirmer_paiement': '#0b7285',
            'valider': '#2b8a3e',
            'rejeter': '#c92a2a',
            'terminer': '#5f3dc4',
        }
        liens = []
        for action, regle in TRANSITIONS.items():
            if not regle['admin'] or obj.statut not in regle['depuis']:
                continue
            url = reverse('admin:publicites_publicite_transition',
                          args=[obj.pk, action])
            liens.append((style.format(couleurs.get(action, '#495057')),
                          url, regle['libelle']))
        if not liens:
            return '—'
        return format_html_join(
            ' ', '<a style="{}" href="{}">{}</a>', liens)


@admin.register(ImpressionPublicite)
class ImpressionAdmin(admin.ModelAdmin):
    list_display = ('publicite', 'utilisateur', 'type_affichage', 'minute_session', 'cliquee', 'cree_le')
    list_filter = ('type_affichage', 'cliquee')


@admin.register(CreditFormulePub)
class CreditFormulePubAdmin(admin.ModelAdmin):
    list_display = ('partenaire', 'formule', 'statut', 'accorde_par', 'cree_le')
    list_filter = ('statut', 'formule')
    search_fields = ('partenaire__nom_commerce',)


@admin.register(ParametresPublicite)
class ParametresPubliciteAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'affluence_debut', 'affluence_fin',
                    'calcul_affluence_auto', 'validation_auto',
                    'interstitiel_minute_min', 'interstitiel_minute_max',
                    'interstitiel_ratio_session_courte')

    def has_add_permission(self, request):
        return not ParametresPublicite.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
