"""Visibilité d'un partenaire côté admin : actif / inactif (est_visible),
suppression douce et restauration — endpoints dédiés au partenaire
(pk = id du ProfilPartenaire, comme l'édition), sur les capacités
existantes masquer_partenaire / supprimer_soft_partenaire /
restaurer_partenaire (super-admin toujours). Journalisés.

Effet public : apps.users.visibilite (un partenaire inactif, suspendu,
banni ou supprimé disparaît de toutes les réponses publiques)."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import ErreurMetier
from apps.core.permissions import ADroitDe
from apps.users.models import ProfilPartenaire
from apps.users.visibilite import partenaire_est_public

from . import moderation
from .models import JournalModeration


def _profil(pk):
    profil = ProfilPartenaire.objects.select_related('user').filter(pk=pk).first()
    if profil is None:
        raise ErreurMetier('Partenaire introuvable.', status_code=404)
    return profil


def _etat(profil):
    profil.refresh_from_db()
    profil.user.refresh_from_db()
    u = profil.user
    return {
        'id': profil.id, 'nom_commerce': profil.nom_commerce,
        'statut': profil.statut, 'statut_libelle': profil.get_statut_display(),
        'est_visible': profil.est_visible, 'est_supprime': u.est_supprime, 'supprime_le': u.supprime_le,
        'est_public': partenaire_est_public(profil),
    }


class PartenaireVisibiliteView(APIView):
    """PATCH /administration/partenaires/<id>/visibilite/ {"est_visible": bool, "motif"?}
    — actif / inactif (masqué de toute l'app). Capacité masquer_partenaire."""
    permission_classes = [IsAuthenticated, ADroitDe('masquer_partenaire')]

    def get(self, request, pk=None):
        return Response(_etat(_profil(pk)))

    def patch(self, request, pk=None):
        profil = _profil(pk)
        visible = request.data.get('est_visible')
        if not isinstance(visible, bool):
            raise ErreurMetier('est_visible (booléen) requis.')
        if visible and profil.user.est_supprime:
            raise ErreurMetier('Partenaire supprimé : restaurez-le avant de le réafficher.', status_code=409)
        if visible != profil.est_visible:
            profil.est_visible = visible
            profil.save(update_fields=['est_visible'])
            motif = (request.data.get('motif') or '').strip()
            moderation._journaliser(
                request.user, profil.user,
                JournalModeration.Action.PARTENAIRE_AFFICHE if visible else JournalModeration.Action.PARTENAIRE_MASQUE,
                (f'« {profil.nom_commerce} »' + (f' : {motif}' if motif else ''))[:255])
        return Response(_etat(profil))


class PartenaireSupprimerView(APIView):
    """POST /administration/partenaires/<id>/supprimer/ {"motif"?} — suppression
    douce (récupérable) : compte désactivé, sessions révoquées, partenaire
    masqué. Capacité supprimer_soft_partenaire. Même action que la
    modération de comptes (apps.administration.moderation.supprimer_soft)."""
    permission_classes = [IsAuthenticated, ADroitDe('supprimer_soft_partenaire')]

    def post(self, request, pk=None):
        profil = _profil(pk)
        if profil.user_id == request.user.id:
            raise ErreurMetier('Vous ne pouvez pas supprimer votre propre compte.')
        if not profil.user.est_supprime:
            moderation.supprimer_soft(request.user, profil.user, motif=(request.data.get('motif') or '').strip())
        return Response(_etat(profil))


class PartenaireRestaurerView(APIView):
    """POST /administration/partenaires/<id>/restaurer/ {"motif"?} — annule la
    suppression douce (le partenaire redevient actif et visible s'il n'est
    pas suspendu / banni par ailleurs). Capacité restaurer_partenaire."""
    permission_classes = [IsAuthenticated, ADroitDe('restaurer_partenaire')]

    def post(self, request, pk=None):
        profil = _profil(pk)
        if not profil.user.est_supprime:
            raise ErreurMetier("Ce partenaire n'est pas supprimé.", status_code=409)
        moderation.restaurer(request.user, profil.user, motif=(request.data.get('motif') or '').strip())
        return Response(_etat(profil))
