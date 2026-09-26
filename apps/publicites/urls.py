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
from .views_admin import (
    FormuleGestionDetailView, FormuleGestionListCreateView,
    ParametresPubliciteAdminView,
)

app_name = 'publicites'

urlpatterns = [
    path('formules/', FormulesView.as_view(), name='formules'),
    path('mes-stats/', StatsPartenaireView.as_view(), name='mes-stats'),
    path('admin/stats/', StatsAdminView.as_view(), name='admin-stats'),
    path('admin/export/', ExportCSVView.as_view(), name='admin-export'),
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
    path('carrousel/', CarrouselView.as_view(), name='carrousel'),
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
