from django.urls import path

from .views import DepartementsView

app_name = 'geo'

urlpatterns = [
    path('departements/', DepartementsView.as_view(), name='departements'),
]
