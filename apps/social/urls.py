"""Routes du module Social (préfixées /api/v1/social/)."""
from django.urls import path
from .views import (
    ToggleLikeArticle, ToggleFavoriArticle, ToggleLikePartenaire,
    ToggleFavoriPartenaire, MesFavorisView, MesLikesView,
)

urlpatterns = [
    path('articles/<int:pk>/like/', ToggleLikeArticle.as_view(), name='like-article'),
    path('articles/<int:pk>/favori/', ToggleFavoriArticle.as_view(), name='favori-article'),
    path('partenaires/<int:pk>/like/', ToggleLikePartenaire.as_view(), name='like-partenaire'),
    path('partenaires/<int:pk>/favori/', ToggleFavoriPartenaire.as_view(), name='favori-partenaire'),
    path('mes-favoris/', MesFavorisView.as_view(), name='mes-favoris'),
    path('mes-likes/', MesLikesView.as_view(), name='mes-likes'),
]
