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
            latitude=request.data.get('latitude') or None,
            longitude=request.data.get('longitude') or None,
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


from .models import Conversation, Message
from .serializers import ConversationSerializer, MessageSerializer


class ConversationsView(APIView):
    """GET liste mes conversations / POST créer (ou récupérer) une conversation."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = Conversation.objects.filter(client=u)
        if hasattr(u, 'profil_partenaire'):
            qs = (Conversation.objects.filter(client=u) |
                  Conversation.objects.filter(partenaire=u.profil_partenaire)).distinct()
        qs = qs.select_related('partenaire', 'client').prefetch_related('messages')
        return Response(ConversationSerializer(qs, many=True, context={'request': request}).data)

    def post(self, request):
        partenaire = get_object_or_404(ProfilPartenaire, pk=request.data.get('partenaire'))
        article_id = request.data.get('article')
        conv, _ = Conversation.objects.get_or_create(
            client=request.user, partenaire=partenaire,
            defaults={'article_id': article_id} if article_id else {})
        return Response(ConversationSerializer(conv, context={'request': request}).data,
                        status=status.HTTP_201_CREATED)


class MessagesView(APIView):
    """GET /conversations/<id>/messages/ — historique (participant uniquement)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk=None):
        conv = get_object_or_404(Conversation, pk=pk)
        u = request.user
        ok = conv.client_id == u.id or (hasattr(u, 'profil_partenaire') and conv.partenaire_id == u.profil_partenaire.id)
        if not ok:
            return Response({'erreur': True, 'message': 'Accès refusé.'}, status=403)
        msgs = conv.messages.filter(est_supprime=False).order_by('created_at')
        return Response(MessageSerializer(msgs, many=True, context={'request': request}).data)


from apps.catalog.models import Article


class ContacterView(APIView):
    """POST /messaging/contacter/ — vitrine/chat : ouvre une conversation à partir
    d'un article. Body: article (id). Crée/récupère la conversation avec l'article en contexte."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """Body: article (id) OU partenaire (id). Avec article, la conversation
        garde l'article en contexte ; avec partenaire seul, conversation générale."""
        if request.data.get('article'):
            article = get_object_or_404(Article, pk=request.data['article'], est_actif=True)
            conv, cree = Conversation.objects.get_or_create(
                client=request.user, partenaire=article.partenaire,
                article=article,
            )
        elif request.data.get('partenaire'):
            from apps.users.models import ProfilPartenaire
            partenaire = get_object_or_404(
                ProfilPartenaire, pk=request.data['partenaire'], statut='actif')
            conv, cree = Conversation.objects.get_or_create(
                client=request.user, partenaire=partenaire, article=None,
            )
        else:
            return Response({'erreur': True, 'message': 'article ou partenaire requis.'},
                            status=400)
        data = ConversationSerializer(conv, context={'request': request}).data
        data['nouvelle'] = cree
        return Response(data, status=status.HTTP_201_CREATED if cree else status.HTTP_200_OK)
