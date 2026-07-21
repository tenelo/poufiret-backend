from django.db.models import F
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from waffle import flag_is_active

from .models import (FormulePublicite, ImpressionPublicite, ParametresPublicite, Publicite, TypeAffichage)
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
        from .services import selectionner_pubs
        pubs = selectionner_pubs(
            TypeAffichage.CARROUSEL,
            utilisateur=request.user if request.user.is_authenticated else None,
        )
        return Response({'publicites': PubliciteListSerializer(
            pubs, many=True, context={'request': request}).data})


class PagePublicitesView(APIView):
    """Toutes les pubs actives (onglet Publicites, public)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        if not flag_is_active(request._request, 'publicite_active'):
            return Response({'publicites': []})
        from .services import selectionner_pubs
        pubs = selectionner_pubs(
            TypeAffichage.PAGE_PUBLICITES,
            utilisateur=request.user if request.user.is_authenticated else None,
        )
        return Response({'publicites': PubliciteListSerializer(
            pubs, many=True, context={'request': request}).data})


class InterstitielView(APIView):
    """Pub plein ecran a servir maintenant, ou rien.

    Flutter appelle avec ?minute_session=N (renvoye par le ping analytics).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not flag_is_active(request._request, 'publicite_active'):
            return Response({'publicite': None})
        from .services import selectionner_pubs
        try:
            minute = int(request.query_params.get('minute_session', 0))
        except (TypeError, ValueError):
            minute = 0
        pubs = selectionner_pubs(
            TypeAffichage.INTERSTITIEL, utilisateur=request.user,
            minute_session=minute, limite=1,
        )
        if not pubs:
            return Response({'publicite': None})
        return Response({'publicite': PubliciteDetailSerializer(
            pubs[0], context={'request': request}).data})


class BandeauBasView(APIView):
    """Bandeau transparent en bas d'ecran (public)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        if not flag_is_active(request._request, 'publicite_active'):
            return Response({'publicite': None})
        from .services import selectionner_pubs
        pubs = selectionner_pubs(
            TypeAffichage.BANDEAU_BAS,
            utilisateur=request.user if request.user.is_authenticated else None,
            limite=1,
        )
        if not pubs:
            return Response({'publicite': None})
        return Response({'publicite': PubliciteListSerializer(
            pubs[0], context={'request': request}).data})


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


class TransitionPubliciteView(APIView):
    """Transitions de statut d'une publicité.

    Partenaire : soumettre (brouillon -> en_attente_paiement)
    Admin : confirmer_paiement (-> en_attente_validation, ou active si validation_auto),
            valider (-> active), rejeter (-> rejetee), terminer (-> terminee)
    """
    permission_classes = [permissions.IsAuthenticated]

    TRANSITIONS = {
        'soumettre': {
            'depuis': [Publicite.Statut.BROUILLON],
            'vers': Publicite.Statut.EN_ATTENTE_PAIEMENT,
            'admin': False,
        },
        'confirmer_paiement': {
            'depuis': [Publicite.Statut.EN_ATTENTE_PAIEMENT],
            'vers': Publicite.Statut.EN_ATTENTE_VALIDATION,
            'admin': True,
        },
        'valider': {
            'depuis': [Publicite.Statut.EN_ATTENTE_VALIDATION],
            'vers': Publicite.Statut.ACTIVE,
            'admin': True,
        },
        'rejeter': {
            'depuis': [Publicite.Statut.EN_ATTENTE_VALIDATION,
                       Publicite.Statut.EN_ATTENTE_PAIEMENT],
            'vers': Publicite.Statut.REJETEE,
            'admin': True,
        },
        'terminer': {
            'depuis': [Publicite.Statut.ACTIVE],
            'vers': Publicite.Statut.TERMINEE,
            'admin': True,
        },
    }

    def _quota_ok(self, pub):
        nb_actives = Publicite.objects.filter(
            formule=pub.formule, statut=Publicite.Statut.ACTIVE,
        ).exclude(pk=pub.pk).count()
        return nb_actives < pub.formule.quota_partenaires

    def _activer(self, pub):
        from datetime import timedelta
        pub.statut = Publicite.Statut.ACTIVE
        pub.debut_diffusion = timezone.now()
        pub.fin_diffusion = pub.debut_diffusion + timedelta(days=pub.formule.duree_jours)
        pub.save(update_fields=['statut', 'debut_diffusion', 'fin_diffusion', 'modifie_le'])

    def post(self, request, pk=None, action=None):
        regle = self.TRANSITIONS.get(action)
        if regle is None:
            return Response({'erreur': True, 'message': 'Action inconnue.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if regle['admin'] and not request.user.is_staff:
            return Response({'erreur': True, 'message': 'Réservé aux administrateurs.'},
                            status=status.HTTP_403_FORBIDDEN)

        filtres = {'pk': pk}
        if not regle['admin']:
            filtres['partenaire__user'] = request.user
        pub = Publicite.objects.filter(**filtres).select_related('formule').first()
        if pub is None:
            return Response({'erreur': True, 'message': 'Publicité introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)
        if pub.statut not in regle['depuis']:
            return Response({'erreur': True,
                             'message': f'Transition impossible depuis "{pub.get_statut_display()}".'},
                            status=status.HTTP_400_BAD_REQUEST)

        vers = regle['vers']
        if vers == Publicite.Statut.ACTIVE or (
            action == 'confirmer_paiement'
            and ParametresPublicite.obtenir().validation_auto
        ):
            if not self._quota_ok(pub):
                return Response({'erreur': True,
                                 'message': 'Quota de la formule atteint, activation impossible.'},
                                status=status.HTTP_409_CONFLICT)
            self._activer(pub)
        else:
            pub.statut = vers
            pub.save(update_fields=['statut', 'modifie_le'])

        return Response({'statut': pub.statut})
