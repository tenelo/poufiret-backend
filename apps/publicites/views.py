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
    """Détail d'une pub (page details_publicites).

    Exclut les pubs masquées par leur partenaire — cohérence avec le
    reste de la diffusion mobile (voir _pubs_diffusables), au cas où un
    client aurait gardé l'id d'une pub masquée après coup.
    """
    serializer_class = PubliciteDetailSerializer
    permission_classes = [permissions.AllowAny]
    queryset = Publicite.objects.filter(
        statut=Publicite.Statut.ACTIVE).exclude(masquee_par_partenaire=True)


class EnregistrerImpressionView(APIView):
    """POST impression/ — trace un affichage ou un clic."""
    permission_classes = [permissions.AllowAny]

    def post(self, request, pk=None):
        pub = Publicite.objects.filter(
            pk=pk, statut=Publicite.Statut.ACTIVE,
            masquee_par_partenaire=False).first()
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
            partenaire__user=self.request.user,
        ).exclude(masquee_par_partenaire=True).order_by('-cree_le')

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


class ReconduirePubliciteView(APIView):
    """POST /mes-publicites/<pk>/reconduire/ — reconduit une pub terminée.

    Crée une NOUVELLE Publicite en brouillon, copie du contenu de
    l'ancienne (titre, description, portée, image, vidéo) ; l'ancienne
    n'est jamais modifiée, elle reste "terminee" avec ses stats intactes
    dans l'historique. Body optionnel : {"formule_id": ...} — sinon
    reprend la formule de l'ancienne pub.

    Choix de copie image/vidéo (signalé) : réutilise la RÉFÉRENCE du
    fichier déjà stocké (même chemin) plutôt que de dupliquer le fichier
    physique — le plus simple, et sans risque puisqu'aucun signal ne
    supprime les fichiers à la suppression d'une Publicite dans ce projet.
    ImagesOptimiseesMixin ne réoptimise que les fichiers fraîchement
    uploadés (FieldFile._committed=False) ; une réaffectation du chemin
    existant est donc traitée comme déjà optimisée et n'est pas retraitée.

    `image_couverture` (multipart, optionnel) : si fournie, remplace
    l'image copiée de l'ancienne pub. Aucun parser custom nécessaire —
    MultiPartParser fait partie des DEFAULT_PARSER_CLASSES de DRF, déjà
    actif sur toutes les vues (c'est ce qui permet déjà l'upload d'image
    sur MesPublicitesView).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None):
        profil = getattr(request.user, 'profil_partenaire', None)
        if profil is None:
            return Response({'erreur': True, 'message': 'Réservé aux partenaires.'},
                            status=403)

        ancienne = Publicite.objects.filter(
            pk=pk, partenaire=profil).select_related('formule').first()
        if ancienne is None:
            return Response({'erreur': True, 'message': 'Publicité introuvable.'},
                            status=404)

        if ancienne.statut != Publicite.Statut.TERMINEE:
            return Response(
                {'erreur': True,
                 'message': ('Seule une publicité terminée peut être reconduite '
                            f'(statut actuel : "{ancienne.get_statut_display()}").')},
                status=400)

        formule_id = request.data.get('formule_id')
        if formule_id:
            try:
                formule = FormulePublicite.objects.filter(
                    pk=formule_id, est_active=True).first()
            except (ValueError, TypeError, DjangoValidationError):
                formule = None
            if formule is None:
                return Response(
                    {'erreur': True, 'message': 'Formule introuvable ou inactive.'},
                    status=400)
        else:
            formule = ancienne.formule

        nouvelle_image = request.FILES.get('image_couverture')
        image_a_utiliser = nouvelle_image or ancienne.image_couverture.name

        nouvelle = Publicite.objects.create(
            partenaire=profil,
            formule=formule,
            titre=ancienne.titre,
            description=ancienne.description,
            image_couverture=image_a_utiliser,
            video=ancienne.video.name if ancienne.video else None,
            portee=ancienne.portee,
        )

        return Response(
            PubliciteCreationSerializer(nouvelle, context={'request': request}).data,
            status=201)


class ModifierImagePubliciteView(APIView):
    """POST /mes-publicites/<pk>/image/ (multipart) — remplace l'image de
    couverture d'une publicité. Body : image_couverture (fichier, requis).

    Règle métier :
    - brouillon / en_attente_paiement / en_attente_validation : remplace
      simplement l'image, statut inchangé.
    - rejetee : remplace l'image ET repasse en brouillon. Choix signalé :
      TRANSITIONS (services.py) n'autorise 'soumettre' que depuis
      brouillon — sans repasser par là, une pub rejetée resterait
      définitivement bloquée une fois son image corrigée. Repasser en
      brouillon est donc le seul choix qui laisse le partenaire
      resoumettre normalement via le cycle existant.
    - active : remplace l'image, repasse en en_attente_validation (sort
      de la diffusion en attendant la revalidation admin de la nouvelle
      image) et vide debut_diffusion/fin_diffusion — symétrique de ce que
      pose services.activer_publicite() à l'activation (ces deux champs
      ne sont pertinents que pendant une diffusion active ; on ne
      réinvente pas leur calcul, on se contente de les vider, la
      prochaine validation admin les recalculera via activer_publicite()
      comme pour toute activation). Journalisé (best-effort, même
      mécanisme que apps.publicites.credits.consommer_credit).
    - terminee : refusée (400) — il faut passer par Reconduire.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None):
        profil = getattr(request.user, 'profil_partenaire', None)
        if profil is None:
            return Response({'erreur': True, 'message': 'Réservé aux partenaires.'},
                            status=403)

        pub = Publicite.objects.filter(pk=pk, partenaire=profil).first()
        if pub is None:
            return Response({'erreur': True, 'message': 'Publicité introuvable.'},
                            status=404)

        if pub.statut == Publicite.Statut.TERMINEE:
            return Response(
                {'erreur': True,
                 'message': 'Une pub terminée ne se modifie pas, utilisez Reconduire.'},
                status=400)

        nouvelle_image = request.FILES.get('image_couverture')
        if not nouvelle_image:
            return Response({'erreur': True, 'message': 'image_couverture requis.'},
                            status=400)

        ancien_statut = pub.statut
        pub.image_couverture = nouvelle_image
        champs = ['image_couverture', 'modifie_le']

        if ancien_statut == Publicite.Statut.REJETEE:
            pub.statut = Publicite.Statut.BROUILLON
            champs.append('statut')
        elif ancien_statut == Publicite.Statut.ACTIVE:
            pub.statut = Publicite.Statut.EN_ATTENTE_VALIDATION
            pub.debut_diffusion = None
            pub.fin_diffusion = None
            champs += ['statut', 'debut_diffusion', 'fin_diffusion']

        pub.save(update_fields=champs)

        if ancien_statut == Publicite.Statut.ACTIVE:
            try:
                from apps.administration.moderation import _journaliser
                _journaliser(
                    request.user, profil.user, 'modifier_image_pub',
                    f"Pub « {pub.titre} » : image modifiée, repassée en "
                    "attente de validation.",
                )
            except Exception:
                pass

        return Response(
            PubliciteCreationSerializer(pub, context={'request': request}).data,
            status=200)


class MasquerPubliciteView(APIView):
    """POST /mes-publicites/<pk>/masquer/ — masquage côté partenaire (soft
    delete) : la pub disparaît des listes/stats du partenaire, mais reste
    en base intégralement (historique, stats globales, modération admin).

    Fonctionne quel que soit le statut (brouillon, active, terminée...) —
    ce n'est pas une transition de cycle de vie, juste une visibilité.
    N'affecte ni les vues admin (StatsAdminView, ExportCSVView,
    ChangerFormulePubliciteView, FaveurPubliciteView...) ni la diffusion
    mobile (déjà traitée séparément via masquee_par_partenaire).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None):
        profil = getattr(request.user, 'profil_partenaire', None)
        if profil is None:
            return Response({'erreur': True, 'message': 'Réservé aux partenaires.'},
                            status=403)

        pub = Publicite.objects.filter(pk=pk, partenaire=profil).first()
        if pub is None:
            return Response({'erreur': True, 'message': 'Publicité introuvable.'},
                            status=404)

        pub.masquee_par_partenaire = True
        pub.save(update_fields=['masquee_par_partenaire', 'modifie_le'])

        try:
            from apps.administration.moderation import _journaliser
            _journaliser(
                request.user, profil.user, 'masquer_pub',
                f"Pub « {pub.titre} » masquée par le partenaire.",
            )
        except Exception:
            pass

        return Response({'detail': 'Publicité retirée de vos listes.'}, status=200)


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
