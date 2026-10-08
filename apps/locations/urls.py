"""Routes du module locations (préfixées /api/v1/locations/)."""
from django.urls import path

from .views_admin_liste import LoueursAdminListeView
from .views_prive import (
    AdminLogementDetailView, AdminLogementDisponibiliteView,
    AdminLogementImageDetailView, AdminLogementImagesView,
    AdminLogementPanoramaDetailView, AdminLogementPanoramasView,
    AdminLogementsView,
    MonLogementDetailView, MonLogementDisponibiliteView,
    MonLogementImageDetailView, MonLogementImagesView,
    MonLogementPanoramaDetailView, MonLogementPanoramasView,
    MonLogementsView,
    AdminVehiculeDetailView, AdminVehiculeDisponibiliteView,
    AdminVehiculeImageDetailView, AdminVehiculeImagesView,
    AdminVehiculePanoramaDetailView, AdminVehiculePanoramasView,
    AdminVehiculesView,
    MonVehiculeDetailView, MonVehiculeDisponibiliteView,
    MonVehiculeImageDetailView, MonVehiculeImagesView,
    MonVehiculePanoramaDetailView, MonVehiculePanoramasView,
    MonVehiculesView,
)
from .views_public import (
    LogementDetailPublicView, LogementsParPartenaireView, MetaLocationsView,
    VehiculeDetailPublicView, VehiculesParPartenaireView,
)

app_name = 'locations'

urlpatterns = [
    # ── Lecture publique ──────────────────────────────────────────────
    path('meta/', MetaLocationsView.as_view(), name='meta'),
    path('partenaires/<int:partenaire_id>/logements/', LogementsParPartenaireView.as_view(),
         name='partenaire-logements'),
    path('logements/<int:pk>/', LogementDetailPublicView.as_view(), name='logement-detail'),
    path('partenaires/<int:partenaire_id>/vehicules/', VehiculesParPartenaireView.as_view(),
         name='partenaire-vehicules'),
    path('vehicules/<int:pk>/', VehiculeDetailPublicView.as_view(), name='vehicule-detail'),

    # ── Loueur de maisons (ses propres logements) ─────────────────────────────────
    path('mon-espace/logements/', MonLogementsView.as_view(), name='mon-logements'),
    path('mon-espace/logements/<int:pk>/', MonLogementDetailView.as_view(), name='mon-logement-detail'),
    path('mon-espace/logements/<int:pk>/disponibilite/', MonLogementDisponibiliteView.as_view(),
         name='mon-logement-disponibilite'),
    path('mon-espace/logements/<int:logement_id>/images/', MonLogementImagesView.as_view(),
         name='mon-logement-images'),
    path('mon-espace/logements/<int:logement_id>/images/<int:pk>/',
         MonLogementImageDetailView.as_view(), name='mon-logement-image-detail'),
    path('mon-espace/logements/<int:logement_id>/panoramas/', MonLogementPanoramasView.as_view(),
         name='mon-logement-panoramas'),
    path('mon-espace/logements/<int:logement_id>/panoramas/<int:pk>/',
         MonLogementPanoramaDetailView.as_view(), name='mon-logement-panorama-detail'),

    # ── Loueur de véhicules (ses propres véhicules) ───────────────────
    path('mon-espace/vehicules/', MonVehiculesView.as_view(), name='mon-vehicules'),
    path('mon-espace/vehicules/<int:pk>/', MonVehiculeDetailView.as_view(), name='mon-vehicule-detail'),
    path('mon-espace/vehicules/<int:pk>/disponibilite/', MonVehiculeDisponibiliteView.as_view(),
         name='mon-vehicule-disponibilite'),
    path('mon-espace/vehicules/<int:vehicule_id>/images/', MonVehiculeImagesView.as_view(),
         name='mon-vehicule-images'),
    path('mon-espace/vehicules/<int:vehicule_id>/images/<int:pk>/',
         MonVehiculeImageDetailView.as_view(), name='mon-vehicule-image-detail'),
    path('mon-espace/vehicules/<int:vehicule_id>/panoramas/', MonVehiculePanoramasView.as_view(),
         name='mon-vehicule-panoramas'),
    path('mon-espace/vehicules/<int:vehicule_id>/panoramas/<int:pk>/',
         MonVehiculePanoramaDetailView.as_view(), name='mon-vehicule-panorama-detail'),

    # ── Admin (à la place d'un loueur donné) ──────────────────────────
    path('admin/', LoueursAdminListeView.as_view(), name='admin-liste'),
    path('admin/<int:partenaire_id>/logements/', AdminLogementsView.as_view(), name='admin-logements'),
    path('admin/<int:partenaire_id>/logements/<int:pk>/', AdminLogementDetailView.as_view(),
         name='admin-logement-detail'),
    path('admin/<int:partenaire_id>/logements/<int:pk>/disponibilite/',
         AdminLogementDisponibiliteView.as_view(), name='admin-logement-disponibilite'),
    path('admin/<int:partenaire_id>/logements/<int:logement_id>/images/',
         AdminLogementImagesView.as_view(), name='admin-logement-images'),
    path('admin/<int:partenaire_id>/logements/<int:logement_id>/images/<int:pk>/',
         AdminLogementImageDetailView.as_view(), name='admin-logement-image-detail'),
    path('admin/<int:partenaire_id>/logements/<int:logement_id>/panoramas/',
         AdminLogementPanoramasView.as_view(), name='admin-logement-panoramas'),
    path('admin/<int:partenaire_id>/logements/<int:logement_id>/panoramas/<int:pk>/',
         AdminLogementPanoramaDetailView.as_view(), name='admin-logement-panorama-detail'),
    path('admin/<int:partenaire_id>/vehicules/', AdminVehiculesView.as_view(), name='admin-vehicules'),
    path('admin/<int:partenaire_id>/vehicules/<int:pk>/', AdminVehiculeDetailView.as_view(),
         name='admin-vehicule-detail'),
    path('admin/<int:partenaire_id>/vehicules/<int:pk>/disponibilite/',
         AdminVehiculeDisponibiliteView.as_view(), name='admin-vehicule-disponibilite'),
    path('admin/<int:partenaire_id>/vehicules/<int:vehicule_id>/images/',
         AdminVehiculeImagesView.as_view(), name='admin-vehicule-images'),
    path('admin/<int:partenaire_id>/vehicules/<int:vehicule_id>/images/<int:pk>/',
         AdminVehiculeImageDetailView.as_view(), name='admin-vehicule-image-detail'),
    path('admin/<int:partenaire_id>/vehicules/<int:vehicule_id>/panoramas/',
         AdminVehiculePanoramasView.as_view(), name='admin-vehicule-panoramas'),
    path('admin/<int:partenaire_id>/vehicules/<int:vehicule_id>/panoramas/<int:pk>/',
         AdminVehiculePanoramaDetailView.as_view(), name='admin-vehicule-panorama-detail'),
]
