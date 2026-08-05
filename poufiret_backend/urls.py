"""
Routage principal Poufiret.
Toutes les routes API sont préfixées /api/v1/ (versioning).
"""
from django.contrib import admin
from django.urls import path, include
from apps.administration.dashboard_admin import vue_tableau_de_bord
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/tableau-de-bord/', vue_tableau_de_bord, name='tableau-de-bord'),
    path('admin/', admin.site.urls),
    path('api/v1/auth/', include('apps.users.urls')),
    path('api/v1/catalogue/', include('apps.catalog.urls')),
    path('api/v1/social/', include('apps.social.urls')),
    path('api/v1/orders/', include('apps.orders.urls')),
    path('api/v1/messaging/', include('apps.messaging.urls')),
    path('api/v1/payments/', include('apps.payments.urls')),
    path('api/v1/notifications/', include('apps.notifications.urls')),
    path('api/v1/analytics/', include('apps.analytics.urls')),
    path('api/v1/publicites/', include('apps.publicites.urls')),
    path('api/v1/geo/', include('apps.geo.urls')),
    path('api/v1/version/', include('apps.version.urls')),
    path('api/v1/administration/', include('apps.administration.urls')),
]

# Service des fichiers médias en développement uniquement
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
