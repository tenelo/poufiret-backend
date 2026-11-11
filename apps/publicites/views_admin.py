"""Vues admin (CRUD) des formules pub et des paramètres généraux de
diffusion. Distinctes de FormulesQuotasAdminView (apps.publicites.stats,
lecture seule, permission voir_stats, INCHANGÉE) : ici, l'édition,
réservée à ADroitDe('gerer_formules_pub').

Plus : création et reconduction d'une pub PAR l'admin POUR un partenaire
(capacité gerer_pubs_partenaires), activée directement aux dates choisies.
"""
from django.db import transaction
from django.db.models import Count, ProtectedError, Q
from django.utils import timezone
from rest_framework import generics, permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import ADroitDe

from . import services
from .models import FormulePublicite, ParametresPublicite, Publicite
from .serializers import PubliciteCreationAdminSerializer
from .serializers_admin import (
    FormulePubliciteAdminSerializer, ParametresPubliciteAdminSerializer,
)

_PERMISSION = [permissions.IsAuthenticated, ADroitDe('gerer_formules_pub')]

# Libellés FR pour le journal d'audit ; prix/quota_partenaires sont traités
# à part (ancien -> nouveau), les autres champs sont juste nommés.
_CHAMPS_LIBELLES = {
    'nom': 'nom', 'prix': 'prix', 'priorite': 'priorité',
    'duree_jours': 'durée (jours)', 'passages_par_jour': 'passages/jour',
    'duree_affichage_secondes': "durée d'un passage",
    'passages_par_type': 'passages par emplacement',
    'quota_partenaires': 'quota', 'acces_heures_affluence': 'accès heures affluence',
    'types_affichage': "types d'affichage", 'nb_images_max': 'nb images max',
    'video_autorisee': 'vidéo autorisée',
    'duree_video_max_secondes': 'durée vidéo max',
    'cible_pourcentage_actifs': 'cible %',
}


def _journaliser_formule(acteur, action, motif):
    """Best-effort, même pattern que apps.publicites.services.journaliser_transition.
    cible=None : une formule n'est rattachée à aucun utilisateur, tout
    l'identifiant utile est dans le motif."""
    try:
        from apps.administration.moderation import _journaliser
        _journaliser(acteur, None, action, motif)
    except Exception:
        pass


def _formules_qs_annotees():
    """Toutes les formules (actives et inactives), avec compteurs en une
    seule requête (sans N+1) : nb_actives, nb_en_attente (soumises, pas
    encore activées), nb_pubs_total (hors brouillon, historique compris —
    sert à l'affichage ; la suppression, elle, vérifie TOUTES les pubs,
    brouillons compris, voir FormuleGestionDetailView.destroy)."""
    Statut = Publicite.Statut
    return FormulePublicite.objects.annotate(
        nb_actives=Count('publicites', filter=Q(publicites__statut=Statut.ACTIVE)),
        nb_en_attente=Count('publicites', filter=Q(publicites__statut__in=[
            Statut.EN_ATTENTE_PAIEMENT, Statut.EN_ATTENTE_VALIDATION])),
        nb_pubs_total=Count(
            'publicites', filter=~Q(publicites__statut=Statut.BROUILLON)),
    )


class FormuleGestionListCreateView(generics.ListCreateAPIView):
    """GET liste toutes les formules (actives et inactives) + compteurs.
    POST en crée une. Réservée à ADroitDe('gerer_formules_pub')."""
    serializer_class = FormulePubliciteAdminSerializer
    permission_classes = _PERMISSION

    def get_queryset(self):
        return _formules_qs_annotees()

    def perform_create(self, serializer):
        formule = serializer.save()
        _journaliser_formule(
            self.request.user, 'pub_formule_creer',
            f'Formule « {formule.nom} » créée (prix {formule.prix} FCFA, '
            f'quota {formule.quota_partenaires}).')


class FormuleGestionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE une formule. Réservée à ADroitDe('gerer_formules_pub').

    PATCH autorisé même avec des pubs actives (décision 3A) : les
    fin_diffusion des campagnes en cours ne sont pas recalculées, les
    nouvelles limites s'appliquent immédiatement. Baisser quota_partenaires
    sous nb_actives est permis (bloque seulement les prochaines
    activations) — la réponse renvoie nb_actives pour l'avertissement
    Angular.

    DELETE réel seulement si AUCUNE pub, brouillons compris, ne référence
    la formule (décision 2A) — cohérent avec le PROTECT déjà posé sur
    Publicite.formule (apps/publicites/models.py).
    """
    serializer_class = FormulePubliciteAdminSerializer
    permission_classes = _PERMISSION

    def get_queryset(self):
        return _formules_qs_annotees()

    def perform_update(self, serializer):
        avant = FormulePublicite.objects.get(pk=serializer.instance.pk)
        formule = serializer.save()

        if avant.est_active != formule.est_active:
            action = 'pub_formule_react' if formule.est_active else 'pub_formule_desact'
            etat = 'réactivée' if formule.est_active else 'désactivée'
            _journaliser_formule(
                self.request.user, action, f'Formule « {formule.nom} » {etat}.')

        champs_modifies = []
        for champ, libelle in _CHAMPS_LIBELLES.items():
            v_avant, v_apres = getattr(avant, champ), getattr(formule, champ)
            if v_avant != v_apres:
                if champ in ('prix', 'quota_partenaires'):
                    champs_modifies.append(f'{libelle} {v_avant} → {v_apres}')
                else:
                    champs_modifies.append(libelle)
        if champs_modifies:
            _journaliser_formule(
                self.request.user, 'pub_formule_modif',
                f'Formule « {formule.nom} » modifiée : '
                f'{", ".join(champs_modifies)}.')

    def destroy(self, request, *args, **kwargs):
        formule = self.get_object()
        nb_references = Publicite.objects.filter(formule=formule).count()
        if nb_references:
            return Response(
                {'erreur': True, 'message': (
                    f'Impossible de supprimer : cette formule est utilisée '
                    f'par {nb_references} campagne(s). Désactivez-la à la '
                    'place.')},
                status=status.HTTP_409_CONFLICT)
        nom = formule.nom
        try:
            formule.delete()
        except ProtectedError:
            return Response(
                {'erreur': True, 'message': (
                    'Impossible de supprimer : des éléments y sont '
                    'rattachés. Désactivez-la à la place.')},
                status=status.HTTP_409_CONFLICT)
        _journaliser_formule(request.user, 'pub_formule_suppr',
                             f'Formule « {nom} » supprimée.')
        return Response(status=status.HTTP_204_NO_CONTENT)


class ParametresPubliciteAdminView(APIView):
    """GET/PATCH des paramètres généraux de diffusion (singleton).
    Réservée à ADroitDe('gerer_formules_pub')."""
    permission_classes = _PERMISSION

    def get(self, request):
        params = ParametresPublicite.obtenir()
        return Response(ParametresPubliciteAdminSerializer(params).data)

    def patch(self, request):
        params = ParametresPublicite.obtenir()
        serializer = ParametresPubliciteAdminSerializer(
            params, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        champs = [c for c in serializer.Meta.fields if c != 'id']
        avant = {c: getattr(params, c) for c in champs}
        params = serializer.save()
        modifies = [c for c in champs if avant[c] != getattr(params, c)]
        if modifies:
            _journaliser_formule(
                request.user, 'pub_parametres_maj',
                f'Paramètres publicité modifiés : {", ".join(modifies)}.')
        return Response(ParametresPubliciteAdminSerializer(params).data)


# ═══════════════════════════════════════════════════════════════════════
# Création / reconduction d'une pub par l'admin pour un partenaire
# ═══════════════════════════════════════════════════════════════════════

_PERMISSION_PUBS_PARTENAIRES = [permissions.IsAuthenticated, ADroitDe('gerer_pubs_partenaires')]


class ActivationAdminSerializer(serializers.Serializer):
    """Dates de diffusion et règlement choisis par l'admin."""
    date_debut = serializers.DateField()
    date_fin = serializers.DateField(required=False, allow_null=True)
    reglement = serializers.ChoiceField(choices=[
        (services.REGLEMENT_PAYEE, 'Payée'), (services.REGLEMENT_OFFERTE, 'Offerte')])
    motif = serializers.CharField(required=False, allow_blank=True)

    def validate_date_debut(self, valeur):
        if valeur < timezone.localdate():
            raise serializers.ValidationError(
                "La date de début doit être aujourd'hui ou plus tard.")
        return valeur

    def validate(self, donnees):
        fin = donnees.get('date_fin')
        if fin is not None and fin <= donnees['date_debut']:
            raise serializers.ValidationError(
                {'date_fin': ['La date de fin doit être postérieure à la date de début.']})
        return donnees


class _QuotaAtteint(Exception):
    """Activation refusée pour quota : annule la création (rollback)."""


def _premier_message(erreurs):
    """Premier message lisible d'un dict d'erreurs DRF (pour 'message')."""
    for valeur in erreurs.values():
        while isinstance(valeur, (list, tuple)) and valeur:
            valeur = valeur[0]
        if isinstance(valeur, dict):
            return _premier_message(valeur)
        if valeur:
            return str(valeur)
    return 'Données invalides.'


def _erreur_400(erreurs):
    return Response({'erreur': True, 'message': _premier_message(erreurs), 'details': erreurs},
                    status=status.HTTP_400_BAD_REQUEST)


def _url(request, champ):
    if not champ:
        return None
    try:
        return request.build_absolute_uri(champ.url)
    except ValueError:
        return None


def _pub_admin_dict(pub, request):
    """Réponse admin (jamais servie au partenaire)."""
    return {
        'id': str(pub.id),
        'partenaire_id': pub.partenaire_id,
        'partenaire_nom': pub.partenaire.nom_commerce,
        'formule_id': str(pub.formule_id),
        'formule_nom': pub.formule.nom,
        'titre': pub.titre,
        'description': pub.description,
        'image_couverture': _url(request, pub.image_couverture),
        'video': _url(request, pub.video),
        'portee': pub.portee,
        'portee_effective': pub.portee_effective,
        'statut': pub.statut,
        'debut_diffusion': pub.debut_diffusion,
        'fin_diffusion': pub.fin_diffusion,
        'reglement': services.REGLEMENT_OFFERTE if pub.est_faveur else services.REGLEMENT_PAYEE,
        'est_faveur': pub.est_faveur,
        'faveur_motif': pub.faveur_motif,
        'cree_par_admin_id': pub.cree_par_admin_id,
    }


def _journaliser_pub_admin(acteur, pub, code, texte):
    """Best-effort, même pattern que services.journaliser_transition."""
    try:
        from apps.administration.moderation import _journaliser
        _journaliser(acteur, pub.partenaire.user, code, texte)
    except Exception:
        pass


def _resume_journal(pub):
    reglement = (f'offerte ({pub.faveur_motif})' if pub.est_faveur else 'payée')
    return (f'Publicité « {pub.titre} » (id {pub.pk}) pour « {pub.partenaire.nom_commerce} » — '
            f'{pub.formule.nom}, {reglement}, du {timezone.localtime(pub.debut_diffusion):%d/%m/%Y} '
            f'au {timezone.localtime(pub.fin_diffusion):%d/%m/%Y}')


class CreerPubliciteAdminView(APIView):
    """POST /api/v1/publicites/admin/creer/ (multipart) — l'admin crée une
    pub pour un partenaire ; elle passe directement au statut active aux
    dates choisies (quota de la formule vérifié comme dans le circuit
    normal). Capacité gerer_pubs_partenaires."""
    permission_classes = _PERMISSION_PUBS_PARTENAIRES

    def post(self, request):
        from apps.users.models import ProfilPartenaire

        brut = request.data.get('partenaire')
        if brut in (None, ''):
            return _erreur_400({'partenaire': ['Ce champ est obligatoire.']})
        try:
            partenaire = ProfilPartenaire.objects.select_related('user', 'plan').filter(pk=int(brut)).first()
        except (TypeError, ValueError):
            partenaire = None
        if partenaire is None:
            return _erreur_400({'partenaire': ['Partenaire introuvable.']})

        creation = PubliciteCreationAdminSerializer(
            data=request.data, context={'request': request, 'partenaire': partenaire})
        activation = ActivationAdminSerializer(data=request.data)
        creation_ok, activation_ok = creation.is_valid(), activation.is_valid()
        if not (creation_ok and activation_ok):
            return _erreur_400({**creation.errors, **activation.errors})
        a = activation.validated_data
        debut, fin = services.bornes_diffusion(
            creation.validated_data['formule'], a['date_debut'], a.get('date_fin'))

        try:
            with transaction.atomic():
                pub = creation.save(partenaire=partenaire)
                ok, message = services.activer_publicite_aux_dates(
                    pub, debut, fin, request.user, a['reglement'], a.get('motif', ''))
                if not ok:
                    raise _QuotaAtteint(message)
        except _QuotaAtteint as exc:
            return Response({'erreur': True, 'message': str(exc)}, status=status.HTTP_409_CONFLICT)

        _journaliser_pub_admin(request.user, pub, 'pub_creee_admin', _resume_journal(pub))
        return Response(_pub_admin_dict(pub, request), status=status.HTTP_201_CREATED)


class ReconduirePubliciteAdminView(APIView):
    """POST /api/v1/publicites/admin/<id>/reconduire/ — l'admin reconduit une
    pub terminée d'un partenaire : même règle de copie que la reconduction
    partenaire (services.copier_pour_reconduction), mais la copie passe
    directement au statut active aux dates choisies. L'originale n'est
    jamais modifiée. Capacité gerer_pubs_partenaires."""
    permission_classes = _PERMISSION_PUBS_PARTENAIRES

    def post(self, request, pk=None):
        ancienne = (Publicite.objects.select_related('formule', 'partenaire__user', 'partenaire__plan')
                    .filter(pk=pk).first())
        if ancienne is None:
            return Response({'erreur': True, 'message': 'Publicité introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)
        refus = services.raison_refus_reconduction(ancienne)
        if refus:
            return Response({'erreur': True, 'message': refus}, status=status.HTTP_400_BAD_REQUEST)
        try:
            formule, nouvelle_image, portee_demandee = services.options_reconduction(
                request.data, request.FILES, ancienne)
        except services.ReconductionInvalide as exc:
            return Response({'erreur': True, 'message': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        activation = ActivationAdminSerializer(data=request.data)
        if not activation.is_valid():
            return _erreur_400(activation.errors)
        a = activation.validated_data
        debut, fin = services.bornes_diffusion(formule, a['date_debut'], a.get('date_fin'))

        try:
            with transaction.atomic():
                nouvelle = services.copier_pour_reconduction(
                    ancienne, ancienne.partenaire, formule, nouvelle_image, portee_demandee)
                ok, message = services.activer_publicite_aux_dates(
                    nouvelle, debut, fin, request.user, a['reglement'], a.get('motif', ''))
                if not ok:
                    raise _QuotaAtteint(message)
        except _QuotaAtteint as exc:
            return Response({'erreur': True, 'message': str(exc)}, status=status.HTTP_409_CONFLICT)

        _journaliser_pub_admin(
            request.user, nouvelle, 'pub_reconduite_admin',
            f'{_resume_journal(nouvelle)} — reconduction de {ancienne.pk}')
        donnees = _pub_admin_dict(nouvelle, request)
        donnees['reconduite_depuis'] = str(ancienne.pk)
        return Response(donnees, status=status.HTTP_201_CREATED)
