"""Vérification de version (endpoint public, appelé au démarrage de l'app)."""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ControleVersion


class VerifierVersionView(APIView):
    """GET ?version=X.Y.Z&plateforme=android|ios

    Réponse : statut (a_jour | conseillee | obligatoire), lien store adapté,
    message et versions de référence. Public : appelé avant toute auth,
    en arrière-plan, au lancement de l'app.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        version = request.query_params.get('version', '')
        plateforme = request.query_params.get('plateforme', 'android')
        contexte = ControleVersion.obtenir()
        statut = contexte.statut_pour(version)
        return Response({
            'statut': statut,
            'obligatoire': statut == 'obligatoire',
            'lien_store': contexte.lien_pour(plateforme),
            'message': contexte.message,
            'version_min_obligatoire': contexte.version_min_obligatoire,
            'version_conseillee': contexte.version_conseillee,
        })
