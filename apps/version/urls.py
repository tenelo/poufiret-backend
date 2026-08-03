from django.urls import path

from .views import VerifierVersionView

app_name = 'version'

urlpatterns = [
    path('verifier/', VerifierVersionView.as_view(), name='verifier'),
]
