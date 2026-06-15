"""Routes messaging (préfixées /api/v1/messaging/)."""
from django.urls import path
from .views import (
    DemandesView, DemandesArtisanView, DemandeDetailView,
    TransitionDemandeView, AjouterPhotoView,
    ConversationsView, MessagesView, ContacterView,
)

urlpatterns = [
    path('interventions/', DemandesView.as_view(), name='interventions'),
    path('interventions/artisan/', DemandesArtisanView.as_view(), name='interventions-artisan'),
    path('interventions/<int:pk>/', DemandeDetailView.as_view(), name='intervention-detail'),
    path('interventions/<int:pk>/transition/', TransitionDemandeView.as_view(), name='intervention-transition'),
    path('interventions/<int:pk>/photos/', AjouterPhotoView.as_view(), name='intervention-photo'),
    path('contacter/', ContacterView.as_view(), name='contacter'),
    path('conversations/', ConversationsView.as_view(), name='conversations'),
    path('conversations/<int:pk>/messages/', MessagesView.as_view(), name='conversation-messages'),
]
