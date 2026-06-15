"""Routes du module Social (préfixées /api/v1/social/)."""
from django.urls import path
from .views import (
    ToggleLikeArticle, ToggleFavoriArticle, ToggleLikePartenaire,
    ToggleFavoriPartenaire, MesFavorisView, MesLikesView,
    CommentaireArticleViewSet, CommentaireArticleDetail,
    CommentairePartenaireViewSet, CommentairePartenaireDetail,
    ToggleLikeCommentaire,
)

urlpatterns = [
    # Likes / favoris
    path('articles/<int:pk>/like/', ToggleLikeArticle.as_view(), name='like-article'),
    path('articles/<int:pk>/favori/', ToggleFavoriArticle.as_view(), name='favori-article'),
    path('partenaires/<int:pk>/like/', ToggleLikePartenaire.as_view(), name='like-partenaire'),
    path('partenaires/<int:pk>/favori/', ToggleFavoriPartenaire.as_view(), name='favori-partenaire'),
    path('mes-favoris/', MesFavorisView.as_view(), name='mes-favoris'),
    path('mes-likes/', MesLikesView.as_view(), name='mes-likes'),
    # Commentaires articles
    path('commentaires/articles/', CommentaireArticleViewSet.as_view(), name='comm-article-liste'),
    path('commentaires/articles/<int:pk>/', CommentaireArticleDetail.as_view(), name='comm-article-detail'),
    # Commentaires partenaires
    path('commentaires/partenaires/', CommentairePartenaireViewSet.as_view(), name='comm-partenaire-liste'),
    path('commentaires/partenaires/<int:pk>/', CommentairePartenaireDetail.as_view(), name='comm-partenaire-detail'),
    # Like de commentaire
    path('commentaires/<str:type_comm>/<int:pk>/like/', ToggleLikeCommentaire.as_view(), name='like-commentaire'),
]
