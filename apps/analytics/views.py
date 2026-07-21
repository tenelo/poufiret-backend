from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from waffle import flag_is_active

from .models import ProfilNavigation, TempsSessionUtilisateur


def _profil(utilisateur):
    aujourdhui = timezone.localdate()
    mois = aujourdhui.replace(day=1)
    profil, _ = ProfilNavigation.objects.get_or_create(
        utilisateur=utilisateur, defaults={'mois_reference': mois},
    )
    if profil.mois_reference != mois:
        # Nouveau mois : remise à zéro des compteurs mensuels
        profil.mois_reference = mois
        profil.nb_articles_vus_mois = 0
        profil.temps_cumule_secondes_mois = 0
    return profil


class DemarrerSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not flag_is_active(request._request, 'analytics_actif'):
            return Response({'detail': 'Analytics désactivé.'}, status=status.HTTP_403_FORBIDDEN)
        # Clôturer les sessions restées actives (app tuée sans fin propre)
        TempsSessionUtilisateur.objects.filter(
            utilisateur=request.user, est_active=True,
        ).update(est_active=False)
        session = TempsSessionUtilisateur.objects.create(
            utilisateur=request.user,
            source=request.data.get('source', TempsSessionUtilisateur.Source.MOBILE),
        )
        return Response({'session_id': str(session.id)}, status=status.HTTP_201_CREATED)


class PingSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not flag_is_active(request._request, 'analytics_actif'):
            return Response({'detail': 'Analytics désactivé.'}, status=status.HTTP_403_FORBIDDEN)
        session_id = request.data.get('session_id')
        try:
            session = TempsSessionUtilisateur.objects.get(
                id=session_id, utilisateur=request.user, est_active=True,
            )
        except (TempsSessionUtilisateur.DoesNotExist, ValueError, TypeError):
            return Response({'detail': 'Session introuvable.'}, status=status.HTTP_404_NOT_FOUND)

        maintenant = timezone.now()
        delta = int((maintenant - session.dernier_ping).total_seconds())
        # Ignorer les deltas aberrants (> 5 min = app revenue après longue pause)
        delta = min(max(delta, 0), 300)
        session.dernier_ping = maintenant
        session.save(update_fields=['dernier_ping', 'modifie_le'])

        profil = _profil(request.user)
        profil.temps_cumule_secondes_mois += delta
        profil.derniere_activite = maintenant
        profil.save()

        return Response({
            'duree_secondes': session.duree_secondes,
            'minute_session': session.minute_session,
        })
