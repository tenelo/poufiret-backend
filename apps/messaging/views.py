"""Vues messaging — bloc C : DemandeIntervention."""
from datetime import datetime
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.users.models import ProfilPartenaire, AdresseClient
from .models import DemandeIntervention, DemandeInterventionPhoto
from .serializers import DemandeInterventionSerializer, DemandeInterventionPhotoSerializer

TRANSITIONS = {
    'en_attente': ['acceptee', 'refusee', 'annulee'],
    'acceptee': ['en_cours', 'annulee'],
    'en_cours': ['terminee', 'annulee'],
    'terminee': [], 'refusee': [], 'annulee': [],
}


def _numero():
    annee = datetime.now().year
    n = DemandeIntervention.objects.filter(numero__startswith=f'INT-{annee}-').count() + 1
    return f'INT-{annee}-{n:05d}'


class DemandesView(APIView):
    """GET liste (client) / POST créer une demande."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = (DemandeIntervention.objects.filter(user=request.user)
              .select_related('artisan').prefetch_related('photos'))
        s = request.query_params.get('statut')
        if s: qs = qs.filter(statut=s)
        return Response(DemandeInterventionSerializer(qs, many=True, context={'request': request}).data)

    def post(self, request):
        artisan = get_object_or_404(ProfilPartenaire, pk=request.data.get('artisan'))
        adresse_id = request.data.get('adresse')
        adresse_obj, snap = None, ''
        if adresse_id:
            adresse_obj = AdresseClient.objects.filter(pk=adresse_id, user=request.user).first()
            if adresse_obj: snap = adresse_obj.adresse
        demande = DemandeIntervention.objects.create(
            numero=_numero(), user=request.user, artisan=artisan,
            type_intervention=request.data.get('type_intervention', 'reparation'),
            type_libre=request.data.get('type_libre', ''),
            description=request.data.get('description', ''),
            urgence=request.data.get('urgence', 'flexible'),
            adresse=adresse_obj, adresse_snapshot=snap,
            description_acces=request.data.get('description_acces', ''),
            disponibilite_preferee=request.data.get('disponibilite_preferee', 'indifferent'),
        )
        return Response(DemandeInterventionSerializer(demande, context={'request': request}).data,
                        status=status.HTTP_201_CREATED)


class DemandesArtisanView(APIView):
    """GET /interventions/artisan/ — demandes reçues par l'artisan connecté."""
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        if not hasattr(request.user, 'profil_partenaire'):
            return Response({'erreur': True, 'message': 'Réservé aux artisans.'}, status=403)
        qs = (DemandeIntervention.objects.filter(artisan=request.user.profil_partenaire)
              .select_related('user').prefetch_related('photos'))
        s = request.query_params.get('statut')
        if s: qs = qs.filter(statut=s)
        return Response(DemandeInterventionSerializer(qs, many=True, context={'request': request}).data)


class DemandeDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def _acces(self, request, d):
        u = request.user
        return d.user_id == u.id or (hasattr(u, 'profil_partenaire') and d.artisan_id == u.profil_partenaire.id)
    def get(self, request, pk=None):
        d = get_object_or_404(DemandeIntervention, pk=pk)
        if not self._acces(request, d):
            return Response({'erreur': True, 'message': 'Accès refusé.'}, status=403)
        return Response(DemandeInterventionSerializer(d, context={'request': request}).data)


class TransitionDemandeView(APIView):
    """POST /interventions/<id>/transition/ — body: statut, date_proposee?, prix_propose?, raison_refus?"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None):
        d = get_object_or_404(DemandeIntervention, pk=pk)
        u = request.user
        est_client = d.user_id == u.id
        est_artisan = hasattr(u, 'profil_partenaire') and d.artisan_id == u.profil_partenaire.id
        if not (est_client or est_artisan):
            return Response({'erreur': True, 'message': 'Accès refusé.'}, status=403)
        cible = request.data.get('statut')
        if cible not in TRANSITIONS.get(d.statut, []):
            return Response({'erreur': True, 'message': f"Transition {d.statut} → {cible} non autorisée."}, status=400)
        # Le client ne peut qu'annuler
        if est_client and not est_artisan and cible != 'annulee':
            return Response({'erreur': True, 'message': "En tant que client, vous ne pouvez qu'annuler."}, status=403)
        if cible == 'acceptee':
            d.date_proposee = request.data.get('date_proposee') or None
            d.prix_propose = request.data.get('prix_propose') or None
        elif cible == 'refusee':
            d.raison_refus = request.data.get('raison_refus', '')
        d.statut = cible
        d.save()
        return Response(DemandeInterventionSerializer(d, context={'request': request}).data)


class AjouterPhotoView(APIView):
    """POST /interventions/<id>/photos/ — le client propriétaire ajoute une photo."""
    permission_classes = [permissions.IsAuthenticated]
    def post(self, request, pk=None):
        d = get_object_or_404(DemandeIntervention, pk=pk, user=request.user)
        data = {**request.data, 'demande': d.id}
        ser = DemandeInterventionPhotoSerializer(data=data)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data, status=status.HTTP_201_CREATED)
