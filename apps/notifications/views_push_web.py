"""Web Push de l'admin web (admins et partenaires) — /api/v1/notifications/push-web/.

GET    cle-publique/  -> {"cle_publique": "<VAPID publique>" | null, "actif": bool}
POST   abonnement/    PushSubscription.toJSON() : {"endpoint", "keys": {"p256dh", "auth"}}
                      -> 201 (nouveau) / 200 (déjà connu : mis à jour, rattaché au compte)
DELETE abonnement/    {"endpoint"} -> 204 (supprime l'abonnement de CE compte s'il existe)
POST   test/          -> 202 {"nb_abonnements": n} ; 400 si push inactif ou aucun abonnement
"""
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import push_web
from .models import AbonnementPushWeb


class EstAdminOuPartenaire(permissions.BasePermission):
    """Admin web : admins (staff / super-admin) et partenaires. Les clients
    (app mobile, FCM) ne sont pas concernés."""
    message = 'Notifications web réservées aux admins et aux partenaires.'

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (u.is_staff or u.is_superuser
                                                  or getattr(u, 'role', '') == 'partenaire'))


_PERMISSIONS = [permissions.IsAuthenticated, EstAdminOuPartenaire]


def _erreur(message):
    return Response({'erreur': True, 'message': message}, status=status.HTTP_400_BAD_REQUEST)


class ClePubliquePushWebView(APIView):
    permission_classes = _PERMISSIONS

    def get(self, request):
        publique = push_web.cles_vapid()[0]
        return Response({'cle_publique': publique or None, 'actif': push_web.est_actif()})


class AbonnementPushWebView(APIView):
    permission_classes = _PERMISSIONS

    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        cles = d.get('keys') if isinstance(d.get('keys'), dict) else {}
        endpoint = str(d.get('endpoint') or '').strip()
        p256dh = str(cles.get('p256dh') or d.get('p256dh') or '').strip()
        auth = str(cles.get('auth') or d.get('auth') or '').strip()
        if not endpoint.startswith('https://') or len(endpoint) > 1000:
            return _erreur('endpoint invalide (URL https attendue).')
        if not p256dh or not auth or len(p256dh) > 200 or len(auth) > 100:
            return _erreur('Clés p256dh et auth obligatoires.')
        _abonnement, cree = AbonnementPushWeb.objects.update_or_create(
            endpoint=endpoint,
            defaults={'user': request.user, 'p256dh': p256dh, 'auth': auth, 'nb_echecs': 0,
                      'user_agent': (request.META.get('HTTP_USER_AGENT') or '')[:300]})
        return Response({'abonne': True, 'nb_abonnements': AbonnementPushWeb.objects.filter(
            user=request.user).count()}, status=status.HTTP_201_CREATED if cree else status.HTTP_200_OK)

    def delete(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        endpoint = str(d.get('endpoint') or request.query_params.get('endpoint') or '').strip()
        if not endpoint:
            return _erreur('endpoint obligatoire.')
        AbonnementPushWeb.objects.filter(user=request.user, endpoint=endpoint).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TestPushWebView(APIView):
    permission_classes = _PERMISSIONS

    def post(self, request):
        if not push_web.est_actif():
            return _erreur('Notifications web inactives (flag push_web_actif ou clés VAPID absentes).')
        nb = AbonnementPushWeb.objects.filter(user=request.user).count()
        if not nb:
            return _erreur('Aucun abonnement pour ce compte : activez les notifications sur cet appareil.')
        push_web.envoyer_push_web([request.user], 'Notification de test',
                                  'Les notifications Poufiret fonctionnent sur cet appareil.')
        return Response({'nb_abonnements': nb}, status=status.HTTP_202_ACCEPTED)
