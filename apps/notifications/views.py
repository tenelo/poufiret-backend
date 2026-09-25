"""Vues notifications : token FCM de l'appareil + notifications in-app admin."""
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response

from apps.moderation.models import Notification

from .serializers import NotificationAdminSerializer


class EstAdminOuSuperAdmin(permissions.BasePermission):
    """Compte admin connecté uniquement (is_staff ou is_superuser)."""
    message = 'Réservé aux comptes admin.'

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (u.is_staff or u.is_superuser))


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


class NotificationsAdminListView(generics.ListAPIView):
    """GET /notifications/admin/?non_lues=1 — notifications in-app du compte
    admin connecté (isolées par destinataire), paginées (StandardPagination),
    plus `nb_non_lues` ajouté à l'enveloppe de pagination."""
    serializer_class = NotificationAdminSerializer
    permission_classes = [permissions.IsAuthenticated, EstAdminOuSuperAdmin]

    def get_queryset(self):
        qs = Notification.objects.filter(user=self.request.user)
        if self.request.query_params.get('non_lues') in ('1', 'true', 'True'):
            qs = qs.filter(lu=False)
        return qs

    def list(self, request, *args, **kwargs):
        reponse = super().list(request, *args, **kwargs)
        reponse.data['nb_non_lues'] = Notification.objects.filter(
            user=request.user, lu=False).count()
        return reponse


class NotificationsAdminCompteurView(APIView):
    """GET /notifications/admin/compteur/ — très léger (1 requête, COUNT
    seul), pensé pour un polling fréquent (ex. toutes les 30 s)."""
    permission_classes = [permissions.IsAuthenticated, EstAdminOuSuperAdmin]

    def get(self, request):
        n = Notification.objects.filter(user=request.user, lu=False).count()
        return Response({'nb_non_lues': n})


class NotificationAdminLireView(APIView):
    """POST /notifications/admin/<id>/lire/ — marque UNE notification lue.
    Isolée par destinataire (404 si elle n'appartient pas au compte)."""
    permission_classes = [permissions.IsAuthenticated, EstAdminOuSuperAdmin]

    def post(self, request, pk=None):
        notif = Notification.objects.filter(pk=pk, user=request.user).first()
        if notif is None:
            return Response({'erreur': True, 'message': 'Notification introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)
        if not notif.lu:
            notif.lu = True
            notif.lu_le = timezone.now()
            notif.save(update_fields=['lu', 'lu_le'])
        return Response(NotificationAdminSerializer(notif).data)


class NotificationsAdminToutLireView(APIView):
    """POST /notifications/admin/tout-lire/ — marque toutes les
    notifications non lues du compte connecté comme lues."""
    permission_classes = [permissions.IsAuthenticated, EstAdminOuSuperAdmin]

    def post(self, request):
        maintenant = timezone.now()
        n = Notification.objects.filter(
            user=request.user, lu=False).update(lu=True, lu_le=maintenant)
        return Response({'nb_mises_a_jour': n, 'nb_non_lues': 0})
