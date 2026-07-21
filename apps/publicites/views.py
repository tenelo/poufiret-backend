from django.db.models import F
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from waffle import flag_is_active

from .models import FormulePublicite, ImpressionPublicite, Publicite, TypeAffichage
from .serializers import (
    FormulePubliciteSerializer, PubliciteCreationSerializer,
    PubliciteDetailSerializer, PubliciteListSerializer,
)


def _pubs_actives():
    maintenant = timezone.now()
    return Publicite.objects.filter(
        statut=Publicite.Statut.ACTIVE,
        debut_diffusion__lte=maintenant,
    ).filter(
        # fin dépassée MAIS cible non atteinte => reste diffusée
        # (le passage en TERMINEE est géré au moment de l'impression)
    ).select_related('formule', 'partenaire')


class FormulesView(generics.ListAPIView):
    """Liste des formules actives (page choix du forfait, partenaire)."""
    serializer_class = FormulePubliciteSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return FormulePublicite.objects.filter(est_active=True).order_by('prix')


class CarrouselView(APIView):
    """Pubs actives pour le carrousel (public)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        if not flag_is_active(request._request, 'publicite_active'):
            return Response({'publicites': []})
        pubs = _pubs_actives().filter(
            formule__types_affichage__contains='carrousel',
        ).order_by('-formule__priorite', 'cree_le')
        return Response({'publicites': PubliciteListSerializer(
            pubs, many=True, context={'request': request}).data})


class PagePublicitesView(APIView):
    """Toutes les pubs actives (onglet Publicités, public)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        if not flag_is_active(request._request, 'publicite_active'):
            return Response({'publicites': []})
        pubs = _pubs_actives().order_by('-formule__priorite', 'cree_le')
        return Response({'publicites': PubliciteListSerializer(
            pubs, many=True, context={'request': request}).data})


class PubliciteDetailView(generics.RetrieveAPIView):
    """Détail d'une pub (page details_publicites)."""
    serializer_class = PubliciteDetailSerializer
    permission_classes = [permissions.AllowAny]
    queryset = Publicite.objects.filter(statut=Publicite.Statut.ACTIVE)


class EnregistrerImpressionView(APIView):
    """POST impression/ — trace un affichage ou un clic."""
    permission_classes = [permissions.AllowAny]

    def post(self, request, pk=None):
        pub = Publicite.objects.filter(pk=pk, statut=Publicite.Statut.ACTIVE).first()
        if not pub:
            return Response({'erreur': True, 'message': 'Publicité introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)
        utilisateur = request.user if request.user.is_authenticated else None
        cliquee = bool(request.data.get('cliquee', False))
        deja_vue = utilisateur and ImpressionPublicite.objects.filter(
            publicite=pub, utilisateur=utilisateur).exists()

        ImpressionPublicite.objects.create(
            publicite=pub,
            utilisateur=utilisateur,
            type_affichage=request.data.get('type_affichage', TypeAffichage.CARROUSEL),
            minute_session=request.data.get('minute_session'),
            cliquee=cliquee,
        )
        maj = {'nb_impressions': F('nb_impressions') + 1}
        if utilisateur and not deja_vue:
            maj['nb_personnes_touchees'] = F('nb_personnes_touchees') + 1
        if cliquee:
            maj['nb_clics'] = F('nb_clics') + 1
        Publicite.objects.filter(pk=pub.pk).update(**maj)

        # Clôture si durée dépassée ET cible atteinte
        pub.refresh_from_db()
        if pub.fin_diffusion and timezone.now() >= pub.fin_diffusion and pub.cible_atteinte:
            pub.statut = Publicite.Statut.TERMINEE
            pub.save(update_fields=['statut', 'modifie_le'])

        return Response({'message': 'Impression enregistrée.'},
                        status=status.HTTP_201_CREATED)


class MesPublicitesView(generics.ListCreateAPIView):
    """Parcours partenaire : lister ses pubs / en créer une (brouillon)."""
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        return PubliciteCreationSerializer

    def get_queryset(self):
        return Publicite.objects.filter(
            partenaire__user=self.request.user).order_by('-cree_le')

    def perform_create(self, serializer):
        profil = getattr(self.request.user, 'profil_partenaire', None)
        if profil is None:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Réservé aux partenaires.')
        serializer.save(partenaire=profil)
