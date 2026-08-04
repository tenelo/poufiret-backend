from django.urls import path

from .views import (DashboardG5View, AppareilsExportView, ModerationView,
                    JournalModerationView, JournalExportView)

app_name = 'administration'

urlpatterns = [
    path('dashboard/', DashboardG5View.as_view(), name='dashboard'),
    path('appareils/export/', AppareilsExportView.as_view(), name='appareils-export'),
    path('moderation/', ModerationView.as_view(), name='moderation'),
    path('moderation/journal/', JournalModerationView.as_view(), name='moderation-journal'),
    path('moderation/journal/export/', JournalExportView.as_view(), name='moderation-journal-export'),
]
