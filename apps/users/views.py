"""Vues de l'app users : authentification JWT, profil, sessions appareils."""
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User, SessionAppareil, ProfilPartenaire
from apps.core.permissions import ADroitDe
from .serializers import (
    ConnexionSerializer, UtilisateurSerializer, LogoutSerializer,
    InscriptionSerializer, SessionAppareilSerializer, DevenirPartenaireSerializer,
    VitrinePartenaireSerializer,
    DemandeOTPSerializer, VerifierOTPSerializer, DefinirPINSerializer,
    ChangerPINSerializer,
    CreerPartenaireParAdminSerializer,
)


def _ip_client(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


class InscriptionView(generics.CreateAPIView):
    """POST /auth/inscription/ — créer un compte (client). Public."""
    serializer_class = InscriptionSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'utilisateur': UtilisateurSerializer(user).data,
        }, status=status.HTTP_201_CREATED)


class ConnexionView(TokenObtainPairView):
    """POST /auth/connexion/ — login téléphone + mot de passe + trace SessionAppareil."""
    serializer_class = ConnexionSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            user = User.objects.filter(telephone=request.data.get('telephone')).first()
            if user:
                appareil_id = request.data.get('appareil_id', '')
                defaults = {
                    'appareil_nom': request.data.get('appareil_nom', ''),
                    'plateforme': request.data.get('plateforme', SessionAppareil.Plateforme.AUTRE),
                    'adresse_ip': _ip_client(request),
                    'est_active': True,
                    'revoque_le': None,
                }
                if appareil_id:
                    SessionAppareil.objects.update_or_create(
                        user=user, appareil_id=appareil_id, defaults=defaults)
                else:
                    SessionAppareil.objects.create(user=user, **defaults)
        return response


class DeconnexionView(APIView):
    """POST /auth/deconnexion/ — blackliste le refresh token et marque la session inactive."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # Marquer la session de cet appareil inactive (si appareil_id fourni)
        appareil_id = request.data.get('appareil_id')
        if appareil_id:
            SessionAppareil.objects.filter(
                user=request.user, appareil_id=appareil_id, est_active=True
            ).update(est_active=False, revoque_le=timezone.now())
        return Response({'message': 'Déconnexion réussie.'}, status=status.HTTP_200_OK)


class MonProfilView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /auth/moi/ — consulter ou modifier son profil."""
    serializer_class = UtilisateurSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class MesAppareilsView(generics.ListAPIView):
    """GET /auth/appareils/ — liste les sessions appareils de l'utilisateur."""
    serializer_class = SessionAppareilSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return SessionAppareil.objects.filter(user=self.request.user)


class RevoquerAppareilView(APIView):
    """POST /auth/appareils/<uuid:pk>/revoquer/ — désactive une session précise."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None):
        session = SessionAppareil.objects.filter(pk=pk, user=request.user).first()
        if not session:
            return Response({'erreur': True, 'message': 'Appareil introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)
        session.est_active = False
        session.revoque_le = timezone.now()
        session.revoque_par = request.user
        session.save(update_fields=['est_active', 'revoque_le', 'revoque_par'])
        return Response({'message': 'Appareil révoqué.'}, status=status.HTTP_200_OK)


class DevenirPartenaireView(generics.CreateAPIView):
    """POST /auth/devenir-partenaire/ — un client crée son profil partenaire."""
    serializer_class = DevenirPartenaireSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({
            'message': 'Profil partenaire créé. En attente de validation par un administrateur.',
            'utilisateur': UtilisateurSerializer(request.user).data,
        }, status=status.HTTP_201_CREATED)


class VitrinePartenaireView(generics.RetrieveAPIView):
    """Vitrine publique d'un partenaire. Accessible à tous (client connecté
    ou non). Ne renvoie que les partenaires actifs et visibles."""
    serializer_class = VitrinePartenaireSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = 'pk'

    def get_queryset(self):
        return ProfilPartenaire.objects.filter(
            statut=ProfilPartenaire.Statut.ACTIF,
            est_visible=True,
        )


class MonProfilPartenaireView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /auth/mon-profil-partenaire/ — le partenaire gere sa vitrine."""
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        from .serializers import MonProfilPartenaireSerializer
        return MonProfilPartenaireSerializer

    def get_object(self):
        profil = getattr(self.request.user, 'profil_partenaire', None)
        if profil is None:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Réservé aux partenaires.')
        return profil


class MesCategoriesView(generics.ListAPIView):
    """GET /auth/mes-categories/ — categories du partenaire connecte."""
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        from .serializers import MaCategorieSerializer
        return MaCategorieSerializer

    def get_queryset(self):
        from apps.catalog.models import PartenaireCategorie
        profil = getattr(self.request.user, 'profil_partenaire', None)
        if profil is None:
            return PartenaireCategorie.objects.none()
        return (PartenaireCategorie.objects.filter(partenaire=profil)
                .select_related('categorie')
                .order_by('-est_principale', 'categorie__nom'))


class MaCategorieDetailView(generics.RetrieveUpdateAPIView):
    """PATCH /auth/mes-categories/<pk>/ — image de couverture par categorie."""
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        from .serializers import MaCategorieSerializer
        return MaCategorieSerializer

    def get_queryset(self):
        from apps.catalog.models import PartenaireCategorie
        profil = getattr(self.request.user, 'profil_partenaire', None)
        if profil is None:
            return PartenaireCategorie.objects.none()
        return PartenaireCategorie.objects.filter(partenaire=profil)


class DemanderOTPView(APIView):
    """POST /auth/otp/demander/ — demande un code OTP. Public.
    Anti-facture : ne genere/envoie rien si le numero est deja verifie
    (cas inscription). Renvoie deja_verifie pour que Flutter enchaine."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = DemandeOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resultat = serializer.creer_et_envoyer()
        return Response(resultat, status=status.HTTP_200_OK)


class VerifierOTPView(APIView):
    """POST /auth/otp/verifier/ — verifie le code. Public.
    Sur succes, inscrit le numero dans NumeroVerifie et ouvre la fenetre
    pour definir le PIN."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = VerifierOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            {'verifie': True,
             'message': "Numéro vérifié. Vous pouvez définir votre code PIN."},
            status=status.HTTP_200_OK,
        )


class DefinirPINView(APIView):
    """POST /auth/pin/definir/ — definit (inscription) ou reinitialise le PIN
    apres OTP valide. Public. Renvoie les tokens pour connecter direct."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = DefinirPINSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'utilisateur': UtilisateurSerializer(user).data,
        }, status=status.HTTP_200_OK)


class ChangerPINView(APIView):
    """POST /auth/pin/changer/ — change le PIN d'un utilisateur connecte
    (ancien + nouveau PIN, pas d'OTP). Renvoie des tokens frais + profil."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangerPINSerializer(
            data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'utilisateur': UtilisateurSerializer(user).data,
        }, status=status.HTTP_200_OK)


class CreerPartenaireParAdminView(APIView):
    """POST /auth/partenaires/creer/ — cree un partenaire complet
    (User + ProfilPartenaire ACTIF) par un admin/demarcheur habilite.
    Protege par la capacite `creer_partenaire`. Renvoie le PIN par defaut
    a communiquer au partenaire."""
    permission_classes = [permissions.IsAuthenticated, ADroitDe('creer_partenaire')]

    def post(self, request):
        serializer = CreerPartenaireParAdminSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profil = serializer.save()

        # Journalisation de l'action (best-effort, ne bloque pas la creation)
        try:
            from apps.administration.models import JournalModeration
            JournalModeration.objects.create(
                acteur=request.user,
                cible=serializer._user,
                cible_identifiant=serializer._user.telephone,
                action=JournalModeration.Action.CREER_PARTENAIRE,
                cible_role=serializer._user.role,
                motif=f"Création partenaire « {profil.nom_commerce} »",
            )
        except Exception:
            pass

        return Response(serializer.data, status=status.HTTP_201_CREATED)
