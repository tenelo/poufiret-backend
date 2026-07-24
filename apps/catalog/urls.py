"""Routes du module Catalogue (préfixées /api/v1/catalogue/)."""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PartenairesParCategorieView, StatsVuesPartenaireView, RechercheUnifieeView,
    CategorieViewSet, ArticleViewSet, EnregistrerVueView,
    ArticleImageViewSet, VarianteViewSet, SupplementViewSet,
    PanoramaViewSet, LogementView, VehiculeView,
)

router = DefaultRouter()
router.register(r'categories', CategorieViewSet, basename='categorie')
router.register(r'articles', ArticleViewSet, basename='article')
router.register(r'images', ArticleImageViewSet, basename='image')
router.register(r'variantes', VarianteViewSet, basename='variante')
router.register(r'supplements', SupplementViewSet, basename='supplement')
router.register(r'panoramas', PanoramaViewSet, basename='panorama')

urlpatterns = [
    path('recherche/', RechercheUnifieeView.as_view(), name='recherche-unifiee'),
    path('partenaire/stats-vues/', StatsVuesPartenaireView.as_view(), name='partenaire-stats-vues'),
    path('categories/<slug:slug>/partenaires/', PartenairesParCategorieView.as_view(), name='categorie-partenaires'),
    path('articles/<slug:slug>/vue/', EnregistrerVueView.as_view(), name='article-vue'),
    path('articles/<slug:slug>/logement/', LogementView.as_view(), name='article-logement'),
    path('articles/<slug:slug>/vehicule/', VehiculeView.as_view(), name='article-vehicule'),
    path('', include(router.urls)),
]
