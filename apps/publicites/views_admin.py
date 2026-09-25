"""Vues admin (CRUD) des formules pub et des paramètres généraux de
diffusion. Distinctes de FormulesQuotasAdminView (apps.publicites.stats,
lecture seule, permission voir_stats, INCHANGÉE) : ici, l'édition,
réservée à ADroitDe('gerer_formules_pub').
"""
from django.db.models import Count, ProtectedError, Q
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import ADroitDe

from .models import FormulePublicite, ParametresPublicite, Publicite
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
