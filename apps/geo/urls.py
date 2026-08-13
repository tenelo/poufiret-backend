from django.urls import path

from .views import DepartementsView, QuartiersView

app_name = 'geo'

urlpatterns = [
    path('departements/', DepartementsView.as_view(), name='departements'),
    path('quartiers/', QuartiersView.as_view(), name='quartiers'),
]
