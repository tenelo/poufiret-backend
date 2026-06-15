"""
Routes du module Catalogue (préfixées /api/v1/catalogue/).
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CategorieViewSet, ArticleViewSet, EnregistrerVueView

router = DefaultRouter()
router.register(r'categories', CategorieViewSet, basename='categorie')
router.register(r'articles', ArticleViewSet, basename='article')

urlpatterns = [
    path('articles/<slug:slug>/vue/', EnregistrerVueView.as_view(), name='article-vue'),
    path('', include(router.urls)),
]
