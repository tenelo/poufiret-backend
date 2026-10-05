from django.urls import path

from .views import DepartementsView, LocalitesView, QuartiersView

app_name = 'geo'

urlpatterns = [
    path('departements/', DepartementsView.as_view(), name='departements'),
    path('localites/', LocalitesView.as_view(), name='localites'),
    path('quartiers/', QuartiersView.as_view(), name='quartiers'),
]
