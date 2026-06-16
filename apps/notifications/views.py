"""Vues notifications : enregistrement du token FCM de l'appareil."""
from rest_framework import permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response


class EnregistrerTokenFCMView(APIView):
    """POST /notifications/token/ — l'app mobile enregistre son token FCM.
    Body: token_fcm. Fonctionne indépendamment de l'activation FCM (on stocke toujours)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        token = (request.data.get('token_fcm') or '').strip()
        if not token:
            return Response({'erreur': True, 'message': 'token_fcm requis.'}, status=400)
        request.user.token_fcm = token
        request.user.save(update_fields=['token_fcm'])
        return Response({'message': 'Token FCM enregistré.'}, status=status.HTTP_200_OK)

    def delete(self, request):
        """Désenregistre (déconnexion / désactivation des notifs)."""
        request.user.token_fcm = None
        request.user.save(update_fields=['token_fcm'])
        return Response({'message': 'Token FCM supprimé.'}, status=status.HTTP_200_OK)
