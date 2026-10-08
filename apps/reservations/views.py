"""Vues client et loueur des demandes de visite/réservation."""
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import DemandeReservation, HistoriqueDemande
from .serializers import CreerDemandeSerializer, DemandeLoueurSerializer, DemandeSerializer


def _qs_base():
    return (DemandeReservation.objects
            .select_related('partenaire', 'objet', 'client')
            .prefetch_related('historique', 'historique__acteur'))


class CreerDemandeView(APIView):
    """POST /api/v1/reservations/ {"objet_id", "nature", ...} — le client
    crée une demande de visite ou de réservation."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        ser = CreerDemandeSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'erreur': True, 'details': ser.errors}, status=400)
        v = ser.validated_data
        objet = v['objet']
        demande = DemandeReservation.objects.create(
            numero=services.numero_demande(), client=request.user, partenaire=objet.partenaire,
            objet=objet, nature=v['nature'], date_souhaitee=v.get('date_souhaitee'),
            date_debut=v.get('date_debut'), date_fin=v.get('date_fin'),
            nb_personnes=v.get('nb_personnes'), message=v.get('message', ''),
            telephone_contact=v.get('telephone_contact', ''),
            avec_chauffeur=v.get('avec_chauffeur'), lieu_prise_en_charge=v.get('lieu_prise_en_charge', ''),
            montant_estime=v.get('montant_estime'),
        )
        HistoriqueDemande.objects.create(
            demande=demande, statut=demande.statut, acteur=request.user,
            acteur_role=HistoriqueDemande.ActeurRole.CLIENT, commentaire='Demande créée.')
        services._notifier_admins_demande(
            demande, 'reservation_nouvelle', 'Nouvelle demande',
            f'{demande.numero} — {request.user.get_full_name() or request.user.telephone} '
            f'→ {demande.partenaire.nom_commerce} ({demande.get_nature_display()}).')
        return Response(DemandeSerializer(demande, context={'request': request}).data, status=201)


class MesDemandesView(generics.ListAPIView):
    """GET /api/v1/reservations/mes-demandes/?statut= — les demandes du client connecté."""
    serializer_class = DemandeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = _qs_base().filter(client=self.request.user)
        statut = self.request.query_params.get('statut')
        return qs.filter(statut=statut) if statut else qs


class AnnulerDemandeView(APIView):
    """POST /api/v1/reservations/<id>/annuler/ {"commentaire"?} — le client
    annule sa propre demande."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None):
        demande = DemandeReservation.objects.filter(pk=pk, client=request.user).select_related('partenaire').first()
        if demande is None:
            return Response({'erreur': True, 'message': 'Demande introuvable.'}, status=404)
        commentaire = (request.data.get('commentaire') or '').strip()
        ok, message = services.appliquer_transition_demande(
            demande, DemandeReservation.Statut.ANNULEE, request.user,
            HistoriqueDemande.ActeurRole.CLIENT, commentaire=commentaire, request=request)
        if not ok:
            return Response({'erreur': True, 'message': message}, status=400)
        return Response(DemandeSerializer(demande, context={'request': request}).data)


class MonEspaceLoueurView(generics.ListAPIView):
    """GET /api/v1/reservations/mon-espace/?statut= — les demandes reçues
    par le loueur connecté, avec transitions_possibles par demande."""
    serializer_class = DemandeLoueurSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        profil = getattr(self.request.user, 'profil_partenaire', None)
        if profil is None:
            return DemandeReservation.objects.none()
        qs = _qs_base().filter(partenaire=profil)
        statut = self.request.query_params.get('statut')
        return qs.filter(statut=statut) if statut else qs


class TransitionLoueurView(APIView):
    """POST /api/v1/reservations/<id>/transition/ {"action", "commentaire"?}
    — le loueur fait transiter une demande qui lui est adressée (mode
    parallèle à apps.orders : même machine d'état, acteur_role='loueur')."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None):
        profil = getattr(request.user, 'profil_partenaire', None)
        if profil is None:
            return Response({'erreur': True, 'message': 'Réservé aux partenaires.'}, status=403)
        demande = DemandeReservation.objects.filter(pk=pk, partenaire=profil).first()
        if demande is None:
            return Response({'erreur': True, 'message': 'Demande introuvable.'}, status=404)
        action = request.data.get('action')
        commentaire = (request.data.get('commentaire') or '').strip()
        if action == DemandeReservation.Statut.REFUSEE and not commentaire:
            return Response({'erreur': True, 'message': 'Le motif est obligatoire pour refuser.'}, status=400)
        ok, message = services.appliquer_transition_demande(
            demande, action, request.user, HistoriqueDemande.ActeurRole.LOUEUR,
            commentaire=commentaire, request=request)
        if not ok:
            return Response({'erreur': True, 'message': message}, status=400)
        return Response(DemandeSerializer(demande, context={'request': request}).data)
