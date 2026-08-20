from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import generics, permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView
from waffle import flag_is_active

from . import credits as credits_pub
from .models import (CreditFormulePub, FormulePublicite, ImpressionPublicite,
                     ParametresPublicite, Publicite, TypeAffichage)
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
        type_affichage = request.data.get('type_affichage',
                                          TypeAffichage.CARROUSEL)
        # Personne deja touchee ? On regarde AVANT d'inserer, tous
        # emplacements confondus : la meme personne vue au carrousel puis
        # en bandeau reste une seule personne touchee.
        deja_vue = bool(utilisateur) and ImpressionPublicite.objects.filter(
            publicite=pub, utilisateur=utilisateur).exists()

        # Deduplication par session : un aller-retour vers l'accueil ne
        # doit pas regonfler les compteurs ni bruler un passage. Un clic
        # est toujours enregistre, c'est un acte volontaire distinct.
        session = None
        session_id = request.data.get('session_id')
        if session_id:
            from apps.analytics.models import TempsSessionUtilisateur
            session = TempsSessionUtilisateur.objects.filter(
                pk=session_id).first()
        if session is not None and not cliquee:
            deja = ImpressionPublicite.objects.filter(
                publicite=pub, session=session,
                type_affichage=type_affichage, cliquee=False,
            ).exists()
            if deja:
                return Response({'message': 'Impression déjà comptée.'},
                                status=status.HTTP_200_OK)

        ImpressionPublicite.objects.create(
            publicite=pub,
            utilisateur=utilisateur,
            type_affichage=type_affichage,
            minute_session=request.data.get('minute_session'),
            session=session,
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


class MesCreditsView(APIView):
    """Crédits de formule pub du partenaire connecté (consultation).

    GET ?statut=disponible|consomme — sans filtre, renvoie tous les crédits.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        profil = getattr(request.user, 'profil_partenaire', None)
        if profil is None:
            return Response({'erreur': True, 'message': 'Réservé aux partenaires.'},
                            status=status.HTTP_403_FORBIDDEN)

        qs = CreditFormulePub.objects.filter(
            partenaire=profil).select_related('formule')
        statut_filtre = request.query_params.get('statut')
        if statut_filtre:
            qs = qs.filter(statut=statut_filtre)
        qs = qs.order_by('-cree_le')

        resultats = [{
            'id': str(c.id),
            'formule_id': c.formule_id,
            'formule_nom': c.formule.nom,
            'formule_prix': c.formule.prix,
            'formule_types_affichage': c.formule.types_affichage,
            'statut': c.statut,
            'cree_le': c.cree_le,
            'consomme_le': c.consomme_le,
            'publicite_consommatrice_id': (
                str(c.publicite_consommatrice_id)
                if c.publicite_consommatrice_id else None
            ),
        } for c in qs]
        return Response({'resultats': resultats})


class MesPublicitesView(generics.ListCreateAPIView):
    """Parcours partenaire : lister ses pubs / en créer une.

    Sans `credit_id` dans le body : comportement inchangé, la pub est créée
    en brouillon (cycle normal soumission/paiement).
    Avec `credit_id` : la pub créée est immédiatement activée gratuitement
    en consommant ce crédit (voir apps.publicites.credits.consommer_credit).
    `credit_id` n'est pas un champ du modèle Publicite, donc pas déclaré
    sur PubliciteCreationSerializer — simplement lu depuis request.data.
    """
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

        with transaction.atomic():
            pub = serializer.save(partenaire=profil)

            credit_id = self.request.data.get('credit_id')
            if not credit_id:
                return

            try:
                credit = CreditFormulePub.objects.select_related(
                    'formule').filter(pk=credit_id).first()
            except (ValueError, TypeError, DjangoValidationError):
                credit = None
            if credit is None:
                raise serializers.ValidationError(
                    {'credit_id': 'Crédit introuvable.'})

            try:
                credits_pub.consommer_credit(profil, credit, pub)
            except ValueError as exc:
                raise serializers.ValidationError({'credit_id': str(exc)})


class TransitionPubliciteView(APIView):
    """Transitions de statut d'une publicite.

    Partenaire : soumettre (brouillon -> en attente de paiement).
    Admin : confirmer_paiement, valider, rejeter, terminer.
    La logique vit dans services.appliquer_transition (source unique,
    partagee avec l'admin Django et la future plateforme Angular).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None, action=None):
        from .services import TRANSITIONS, appliquer_transition

        regle = TRANSITIONS.get(action)
        if regle is None:
            return Response({'erreur': True, 'message': 'Action inconnue.'},
                            status=status.HTTP_400_BAD_REQUEST)
        est_autorise = request.user.is_superuser or (
            request.user.is_staff
            and getattr(getattr(request.user, 'permissions_admin', None),
                       'valider_publicite', False)
        )
        if regle['admin'] and not est_autorise:
            return Response({'erreur': True,
                             'message': 'Réservé aux administrateurs.'},
                            status=status.HTTP_403_FORBIDDEN)

        filtres = {'pk': pk}
        if not regle['admin']:
            filtres['partenaire__user'] = request.user
        pub = (Publicite.objects.filter(**filtres)
               .select_related('formule').first())
        if pub is None:
            return Response({'erreur': True,
                             'message': 'Publicité introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)

        ok, message = appliquer_transition(pub, action)
        if not ok:
            code = (status.HTTP_409_CONFLICT if 'Quota' in message
                    else status.HTTP_400_BAD_REQUEST)
            return Response({'erreur': True, 'message': message}, status=code)
        return Response({'statut': pub.statut, 'message': message})
