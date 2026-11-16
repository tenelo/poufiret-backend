from django.urls import path

from .views import (
    BandeauBasView, CarrouselView, EnregistrerImpressionView, FormulesView,
    InterstitielView, MesCreditsView, MesPublicitesView, PagePublicitesView,
    PubliciteDetailView, TransitionPubliciteView, ReconduirePubliciteView,
    ModifierImagePubliciteView, MasquerPubliciteView, AnnulerSoumissionView,
)

from .stats import (ExportCSVView, FormulesQuotasAdminView, StatsAdminView,
                    StatistiquesGlobalesAdminView, StatsPartenaireView,
                    StatsVisiblesAdminView)
from .views_poufiret import (
    DecouvrirView, EcranDecouverteAdminDetailView, EcransDecouverteAdminView,
    ImpressionPubPoufiretView, OrdreEcransDecouverteView, OrdrePubsPoufiretView,
    PubPoufiretAdminDetailView, PubsPoufiretAdminView, PublierParcoursView,
    ReglagesPoufiretView, StatsPoufiretAdminView, StatsPubPoufiretView,
)
from .views_liste_admin import (CompteursPublicitesAdminView, ListePublicitesAdminView,
                                PartenairesPublicitesAdminView)
from .views_admin import (
    CreerPubliciteAdminView, FormuleGestionDetailView, FormuleGestionListCreateView,
    ParametresPubliciteAdminView, ReconduirePubliciteAdminView,
)

app_name = 'publicites'

urlpatterns = [
    path('formules/', FormulesView.as_view(), name='formules'),
    path('mes-stats/', StatsPartenaireView.as_view(), name='mes-stats'),
    path('admin/stats/', StatsAdminView.as_view(), name='admin-stats'),
    path('admin/export/', ExportCSVView.as_view(), name='admin-export'),
    path('admin/liste/', ListePublicitesAdminView.as_view(), name='admin-liste'),
    # Pubs Poufiret et parcours « Découvrir Poufiret » (gerer_pubs_poufiret)
    path('admin/poufiret/pubs/', PubsPoufiretAdminView.as_view(), name='admin-poufiret-pubs'),
    path('admin/poufiret/pubs/ordre/', OrdrePubsPoufiretView.as_view(), name='admin-poufiret-pubs-ordre'),
    path('admin/poufiret/pubs/<uuid:pk>/', PubPoufiretAdminDetailView.as_view(), name='admin-poufiret-pub'),
    path('admin/poufiret/pubs/<uuid:pk>/stats/', StatsPubPoufiretView.as_view(),
         name='admin-poufiret-pub-stats'),
    path('admin/poufiret/stats/', StatsPoufiretAdminView.as_view(), name='admin-poufiret-stats'),
    path('admin/poufiret/ecrans/', EcransDecouverteAdminView.as_view(), name='admin-poufiret-ecrans'),
    path('admin/poufiret/ecrans/ordre/', OrdreEcransDecouverteView.as_view(),
         name='admin-poufiret-ecrans-ordre'),
    path('admin/poufiret/ecrans/<uuid:pk>/', EcranDecouverteAdminDetailView.as_view(),
         name='admin-poufiret-ecran'),
    path('admin/poufiret/parcours/publier/', PublierParcoursView.as_view(),
         name='admin-poufiret-parcours-publier'),
    path('admin/poufiret/reglages/', ReglagesPoufiretView.as_view(), name='admin-poufiret-reglages'),
    path('admin/compteurs/', CompteursPublicitesAdminView.as_view(), name='admin-compteurs'),
    path('admin/partenaires/', PartenairesPublicitesAdminView.as_view(), name='admin-partenaires'),
    path('admin/statistiques/', StatistiquesGlobalesAdminView.as_view(),
         name='admin-statistiques'),
    path('admin/formules/', FormulesQuotasAdminView.as_view(), name='admin-formules'),
    path('admin/<uuid:pk>/stats-visibles/', StatsVisiblesAdminView.as_view(),
         name='admin-stats-visibles'),
    path('admin/formules/gestion/', FormuleGestionListCreateView.as_view(),
         name='admin-formules-gestion'),
    path('admin/formules/gestion/<uuid:pk>/', FormuleGestionDetailView.as_view(),
         name='admin-formule-gestion-detail'),
    path('admin/parametres/', ParametresPubliciteAdminView.as_view(),
         name='admin-parametres'),
    path('admin/creer/', CreerPubliciteAdminView.as_view(), name='admin-creer'),
    path('admin/<uuid:pk>/reconduire/', ReconduirePubliciteAdminView.as_view(),
         name='admin-reconduire'),
    path('carrousel/', CarrouselView.as_view(), name='carrousel'),
    path('poufiret/<uuid:pk>/impression/', ImpressionPubPoufiretView.as_view(), name='poufiret-impression'),
    path('decouvrir/', DecouvrirView.as_view(), name='decouvrir'),
    path('interstitiel/', InterstitielView.as_view(), name='interstitiel'),
    path('bandeau-bas/', BandeauBasView.as_view(), name='bandeau-bas'),
    path('mes-publicites/', MesPublicitesView.as_view(), name='mes-publicites'),
    path('mes-publicites/<uuid:pk>/reconduire/', ReconduirePubliciteView.as_view(),
         name='mes-publicites-reconduire'),
    path('mes-publicites/<uuid:pk>/image/', ModifierImagePubliciteView.as_view(),
         name='mes-publicites-image'),
    path('mes-publicites/<uuid:pk>/masquer/', MasquerPubliciteView.as_view(),
         name='mes-publicites-masquer'),
    path('mes-publicites/<uuid:pk>/annuler-soumission/', AnnulerSoumissionView.as_view(),
         name='mes-publicites-annuler-soumission'),
    path('mes-credits/', MesCreditsView.as_view(), name='mes-credits'),
    path('', PagePublicitesView.as_view(), name='liste'),
    path('<uuid:pk>/', PubliciteDetailView.as_view(), name='detail'),
    path('<uuid:pk>/impression/', EnregistrerImpressionView.as_view(), name='impression'),
    path('<uuid:pk>/transition/<str:action>/', TransitionPubliciteView.as_view(), name='transition'),
]
