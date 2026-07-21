from django.urls import path

from .views import (
    BandeauBasView, CarrouselView, EnregistrerImpressionView, FormulesView,
    InterstitielView, MesPublicitesView, PagePublicitesView,
    PubliciteDetailView, TransitionPubliciteView,
)

app_name = 'publicites'

urlpatterns = [
    path('formules/', FormulesView.as_view(), name='formules'),
    path('carrousel/', CarrouselView.as_view(), name='carrousel'),
    path('interstitiel/', InterstitielView.as_view(), name='interstitiel'),
    path('bandeau-bas/', BandeauBasView.as_view(), name='bandeau-bas'),
    path('mes-publicites/', MesPublicitesView.as_view(), name='mes-publicites'),
    path('', PagePublicitesView.as_view(), name='liste'),
    path('<uuid:pk>/', PubliciteDetailView.as_view(), name='detail'),
    path('<uuid:pk>/impression/', EnregistrerImpressionView.as_view(), name='impression'),
    path('<uuid:pk>/transition/<str:action>/', TransitionPubliciteView.as_view(), name='transition'),
]
