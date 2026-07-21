from django.urls import path

from .views import (
    CarrouselView, EnregistrerImpressionView, FormulesView,
    MesPublicitesView, PagePublicitesView, PubliciteDetailView,
)

app_name = 'publicites'

urlpatterns = [
    path('formules/', FormulesView.as_view(), name='formules'),
    path('carrousel/', CarrouselView.as_view(), name='carrousel'),
    path('', PagePublicitesView.as_view(), name='liste'),
    path('<uuid:pk>/', PubliciteDetailView.as_view(), name='detail'),
    path('<uuid:pk>/impression/', EnregistrerImpressionView.as_view(), name='impression'),
    path('mes-publicites/', MesPublicitesView.as_view(), name='mes-publicites'),
]
