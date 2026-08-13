"""Vues de l'app livreurs : position (telephone/transpondeur) + statut.

Cote demandeur, la liste des livreurs proches sert a la carte (phase 2).
"""
from django.utils import timezone
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from rest_framework import permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import Livreur
from .sources import SourceTelephone, SourceTranspondeur, enregistrer_position


def _profil_livreur(user):
    return getattr(user, 'profil_livreur', None)


class MaPositionView(APIView):
    """POST /livreurs/position/ — le livreur (app) envoie sa position.
    Body: latitude, longitude. Passe par l'abstraction SourceTelephone."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        livreur = _profil_livreur(request.user)
        if livreur is None:
            return Response({'erreur': True, 'message': 'Reserve aux livreurs.'},
                            status=403)
        lat = request.data.get('latitude')
        lng = request.data.get('longitude')
        if lat is None or lng is None:
            return Response({'erreur': True, 'message': 'latitude et longitude requises.'},
                            status=400)
        try:
            enregistrer_position(livreur, lat, lng, SourceTelephone())
        except (ValueError, TypeError) as e:
            return Response({'erreur': True, 'message': str(e)}, status=400)
        return Response({'message': 'Position enregistree.'}, status=200)


class PositionTranspondeurView(APIView):
    """POST /livreurs/position-transpondeur/ — un boitier envoie sa position.
    Body: transpondeur_id, latitude, longitude. Pas d'auth JWT : identifie
    par le transpondeur_id (a securiser par un token device plus tard)."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        tid = (request.data.get('transpondeur_id') or '').strip()
        lat = request.data.get('latitude')
        lng = request.data.get('longitude')
        if not tid or lat is None or lng is None:
            return Response({'erreur': True,
                             'message': 'transpondeur_id, latitude, longitude requis.'},
                            status=400)
        try:
            livreur = Livreur.objects.get(transpondeur_id=tid)
        except Livreur.DoesNotExist:
            return Response({'erreur': True, 'message': 'Transpondeur inconnu.'}, status=404)
        try:
            enregistrer_position(livreur, lat, lng, SourceTranspondeur(tid))
        except (ValueError, TypeError) as e:
            return Response({'erreur': True, 'message': str(e)}, status=400)
        return Response({'message': 'Position enregistree.'}, status=200)


class MonStatutView(APIView):
    """POST /livreurs/statut/ — le livreur passe en ligne / hors ligne.
    Body: statut ('en_ligne' | 'hors_ligne')."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        livreur = _profil_livreur(request.user)
        if livreur is None:
            return Response({'erreur': True, 'message': 'Reserve aux livreurs.'},
                            status=403)
        cible = request.data.get('statut')
        if cible not in (Livreur.Statut.EN_LIGNE, Livreur.Statut.HORS_LIGNE):
            return Response({'erreur': True, 'message': 'statut invalide.'}, status=400)
        livreur.statut = cible
        livreur.save(update_fields=['statut'])
        return Response({'message': f'Statut: {cible}.'}, status=200)


class LivreursProchesView(APIView):
    """GET /livreurs/proches/ — livreurs EN LIGNE de la ville du demandeur,
    tries par distance a une position donnee (?lat=&lng=). Sert a la carte."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        lat = request.query_params.get('lat')
        lng = request.query_params.get('lng')
        qs = Livreur.objects.filter(
            statut=Livreur.Statut.EN_LIGNE, position__isnull=False)
        # Filtre ville du demandeur si renseignee.
        dep = getattr(request.user, 'departement_id', None)
        if dep:
            qs = qs.filter(ville_id=dep)
        if lat is not None and lng is not None:
            point = Point(float(lng), float(lat), srid=4326)
            qs = qs.annotate(distance=Distance('position', point)).order_by('distance')
        donnees = [{
            'id': str(l.id),
            'nom': str(l.user),
            'type_vehicule': l.type_vehicule,
            'latitude': l.position.y if l.position else None,
            'longitude': l.position.x if l.position else None,
            'position_maj_le': l.position_maj_le.isoformat() if l.position_maj_le else None,
        } for l in qs[:50]]
        return Response(donnees, status=200)
