"""Routes admin (CRUD) de la géographie — montées sous
/api/v1/administration/geo/ (voir apps.administration.urls).

Distinctes des routes publiques (apps.geo.urls, INCHANGÉES).
"""
from django.urls import path

from .admin_views import (
    DepartementAdminDetailView, DepartementAdminExportView,
    DepartementAdminListCreateView, DepartementOptionsView,
    DistrictOptionsView,
    LocaliteAdminDetailView, LocaliteAdminExportView,
    LocaliteAdminListCreateView, LocaliteOptionsView,
    QuartierAdminDetailView, QuartierAdminExportView,
    QuartierAdminListCreateView, QuartierOptionsView,
    RegionAdminDetailView, RegionAdminExportView,
    RegionAdminListCreateView, RegionOptionsView,
)

app_name = 'geo_admin'

urlpatterns = [
    path('districts/options/', DistrictOptionsView.as_view(), name='districts-options'),

    path('regions/', RegionAdminListCreateView.as_view(), name='regions'),
    path('regions/options/', RegionOptionsView.as_view(), name='regions-options'),
    path('regions/export/', RegionAdminExportView.as_view(), name='regions-export'),
    path('regions/<int:pk>/', RegionAdminDetailView.as_view(), name='region-detail'),

    path('departements/', DepartementAdminListCreateView.as_view(), name='departements'),
    path('departements/options/', DepartementOptionsView.as_view(), name='departements-options'),
    path('departements/export/', DepartementAdminExportView.as_view(), name='departements-export'),
    path('departements/<int:pk>/', DepartementAdminDetailView.as_view(), name='departement-detail'),

    path('localites/', LocaliteAdminListCreateView.as_view(), name='localites'),
    path('localites/options/', LocaliteOptionsView.as_view(), name='localites-options'),
    path('localites/export/', LocaliteAdminExportView.as_view(), name='localites-export'),
    path('localites/<int:pk>/', LocaliteAdminDetailView.as_view(), name='localite-detail'),

    path('quartiers/', QuartierAdminListCreateView.as_view(), name='quartiers'),
    path('quartiers/options/', QuartierOptionsView.as_view(), name='quartiers-options'),
    path('quartiers/export/', QuartierAdminExportView.as_view(), name='quartiers-export'),
    path('quartiers/<int:pk>/', QuartierAdminDetailView.as_view(), name='quartier-detail'),
]
