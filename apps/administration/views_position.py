"""Position GPS d'un partenaire, écrite par l'admin (capacité creer_partenaire).
Le partenaire l'écrit lui-même via PATCH /auth/mon-profil-partenaire/."""
from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import ADroitDe
from apps.users.models import ProfilPartenaire
from apps.users.position import PositionSerializer, appliquer_position, position_dict, texte_position

from .moderation import _journaliser
from .models import JournalModeration


class PositionPartenaireView(APIView):
    """PATCH /administration/partenaires/<id>/position/ {latitude, longitude}
    pk = ProfilPartenaire.pk. Les deux valeurs ensemble ; null pour effacer."""
    permission_classes = [IsAuthenticated, ADroitDe('creer_partenaire')]

    def patch(self, request, pk):
        profil = ProfilPartenaire.objects.select_related('user').filter(pk=pk).first()
        if profil is None:
            return Response({'erreur': True, 'message': 'Partenaire introuvable.'}, status=404)
        if 'latitude' not in request.data or 'longitude' not in request.data:
            return Response({'erreur': True, 'details': {
                'latitude': ['latitude et longitude sont requis (null pour les deux, pour effacer).'],
                'longitude': ['latitude et longitude sont requis (null pour les deux, pour effacer).'],
            }}, status=400)
        ser = PositionSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'erreur': True, 'details': ser.errors}, status=400)
        lat, lng = ser.validated_data['latitude'], ser.validated_data['longitude']

        avant = texte_position(profil)
        with transaction.atomic():
            avertissement = appliquer_position(profil, lat, lng, 'admin')
            _journaliser(request.user, profil.user, JournalModeration.Action.PARTENAIRE_POSITION,
                         f'{avant} → {texte_position(profil)}')
        return Response({'id': profil.id, **position_dict(profil, avertissement)})
