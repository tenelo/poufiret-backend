"""Vues Paiement (Module 5). Inertes tant que le flag waffle 'paiement_actif' est off."""
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.generics import get_object_or_404
from waffle import flag_is_active
from .models import Paiement
from .serializers import PaiementSerializer

FLAG = 'paiement_actif'


def _desactive(request):
    """True si le module paiement n'est pas activé pour cette requête."""
    base = getattr(request, '_request', request)
    return not flag_is_active(base, FLAG)


class PaiementsView(APIView):
    """GET liste (admin: tous ; user: les siens) / POST créer un paiement (en_attente)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if _desactive(request):
            return Response({'erreur': True, 'message': 'Module paiement désactivé.'}, status=503)
        u = request.user
        qs = Paiement.objects.all() if (u.is_staff or u.role == u.Role.ADMIN) \
            else Paiement.objects.filter(user=u)
        s = request.query_params.get('statut')
        if s: qs = qs.filter(statut=s)
        return Response(PaiementSerializer(qs, many=True).data)

    def post(self, request):
        if _desactive(request):
            return Response({'erreur': True, 'message': 'Module paiement désactivé.'}, status=503)
        ser = PaiementSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save(user=request.user, statut=Paiement.Statut.EN_ATTENTE)
        return Response(ser.data, status=status.HTTP_201_CREATED)


class ValiderPaiementView(APIView):
    """POST /paiements/<id>/valider/ — admin confirme/rejette/rembourse. Body: statut, note?"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None):
        if _desactive(request):
            return Response({'erreur': True, 'message': 'Module paiement désactivé.'}, status=503)
        u = request.user
        if not (u.is_staff or u.role == u.Role.ADMIN):
            return Response({'erreur': True, 'message': 'Réservé aux administrateurs.'}, status=403)
        p = get_object_or_404(Paiement, pk=pk)
        cible = request.data.get('statut')
        if cible not in [Paiement.Statut.CONFIRME, Paiement.Statut.REJETE, Paiement.Statut.REMBOURSE]:
            return Response({'erreur': True, 'message': 'Statut cible invalide.'}, status=400)
        p.statut = cible
        p.valide_par = u
        p.valide_le = timezone.now()
        if request.data.get('note'): p.note = request.data['note']
        p.save()
        return Response(PaiementSerializer(p).data)
