"""Centre de gestion admin des demandes d'intervention (comme les commandes).

Lecture (meta, détail) : voir_interventions OU gerer_interventions.
Écritures (transition, assigner, notes) : gerer_interventions.
Super-admin toujours autorisé (ADroitDe / ADroitDeUnDe). La machine
d'état, l'historique et les notifications client/artisan sont ceux de
apps.messaging.services (aucune duplication).
"""
from django.db.models import Prefetch
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import ADroitDe, ADroitDeUnDe
from apps.messaging import services as services_interventions
from apps.messaging.models import (
    DemandeIntervention, HistoriqueIntervention, NoteAdminIntervention,
)
from apps.users.models import ProfilPartenaire

_LECTURE = [IsAuthenticated, ADroitDeUnDe('voir_interventions', 'gerer_interventions')]
_ECRITURE = [IsAuthenticated, ADroitDe('gerer_interventions')]


def _choix(choices):
    return [{'valeur': v, 'libelle': str(l)} for v, l in choices]


def _nom(user):
    if user is None:
        return ''
    return user.get_full_name() or user.username or user.telephone


def _url(champ, request):
    if not champ:
        return None
    try:
        return request.build_absolute_uri(champ.url)
    except ValueError:
        return None


def _demande_ou_none(pk):
    return (DemandeIntervention.objects
            .select_related('user', 'artisan__user', 'adresse')
            .prefetch_related(
                'photos',
                Prefetch('historique', queryset=HistoriqueIntervention.objects
                         .select_related('acteur').order_by('cree_le')),
                Prefetch('notes_admin', queryset=NoteAdminIntervention.objects
                         .select_related('auteur').order_by('-cree_le')))
            .filter(pk=pk).first())


def _note_dict(n):
    return {'id': n.id, 'texte': n.texte, 'auteur_nom': _nom(n.auteur), 'cree_le': n.cree_le}


def _detail(d, request):
    artisan = d.artisan
    return {
        'id': d.id, 'numero': d.numero,
        'statut': d.statut, 'statut_libelle': d.get_statut_display(),
        'type_intervention': d.type_intervention,
        'type_libelle': d.get_type_intervention_display(), 'type_libre': d.type_libre,
        'urgence': d.urgence, 'urgence_libelle': d.get_urgence_display(),
        'disponibilite_preferee': d.disponibilite_preferee,
        'disponibilite_libelle': d.get_disponibilite_preferee_display(),
        'description': d.description,
        'client': {'id': d.user_id, 'nom': _nom(d.user), 'telephone': d.user.telephone},
        'artisan': {
            'id': artisan.id, 'nom': artisan.nom_commerce,
            'telephone': artisan.telephone_pro or getattr(artisan.user, 'telephone', ''),
            'type_partenaire': artisan.type_partenaire,
            'type_partenaire_libelle': artisan.get_type_partenaire_display(),
        },
        'adresse': {
            'adresse': d.adresse_snapshot or getattr(d.adresse, 'adresse', ''),
            'description_acces': d.description_acces,
            'latitude': d.latitude, 'longitude': d.longitude,
        },
        'date_proposee': d.date_proposee, 'prix_propose': d.prix_propose,
        'raison_refus': d.raison_refus,
        'photos': [{'id': p.id, 'image': _url(p.image, request), 'legende': p.legende}
                   for p in d.photos.all()],
        'historique': [{
            'statut': h.statut, 'statut_libelle': h.get_statut_display(),
            'acteur_nom': _nom(h.acteur), 'acteur_role': h.acteur_role,
            'commentaire': h.commentaire, 'cree_le': h.cree_le,
        } for h in d.historique.all()],
        'notes_admin': [_note_dict(n) for n in d.notes_admin.all()],
        'transitions_possibles': [{
            'action': a, 'libelle': services_interventions.ACTIONS_LIBELLES.get(a, a),
            'commentaire_obligatoire': a in services_interventions.ACTIONS_COMMENTAIRE_OBLIGATOIRE,
        } for a in services_interventions.TRANSITIONS.get(d.statut, [])],
        'peut_reassigner': d.statut in services_interventions.STATUTS_REASSIGNABLES,
        'cree_le': d.created_at, 'acceptee_le': d.acceptee_le, 'terminee_le': d.terminee_le,
    }


def _introuvable():
    return Response({'erreur': True, 'message': "Demande d'intervention introuvable."},
                    status=status.HTTP_404_NOT_FOUND)


class InterventionsMetaView(APIView):
    """GET /administration/interventions/meta/ — statuts, urgences, types."""
    permission_classes = _LECTURE

    def get(self, request):
        return Response({
            'statuts': _choix(DemandeIntervention.Statut.choices),
            'urgences': _choix(DemandeIntervention.Urgence.choices),
            'types': _choix(DemandeIntervention.Type.choices),
        })


class InterventionAdminDetailView(APIView):
    """GET /administration/interventions/<id>/ — détail complet."""
    permission_classes = _LECTURE

    def get(self, request, pk=None):
        d = _demande_ou_none(pk)
        return Response(_detail(d, request)) if d else _introuvable()


class InterventionAdminTransitionView(APIView):
    """POST /administration/interventions/<id>/transition/ {action, commentaire}
    — machine d'état partagée, acteur_role=admin ; motif obligatoire pour
    annuler/refuser. Client et artisan notifiés."""
    permission_classes = _ECRITURE

    def post(self, request, pk=None):
        d = DemandeIntervention.objects.select_related('user', 'artisan__user').filter(pk=pk).first()
        if d is None:
            return _introuvable()
        action = request.data.get('action')
        commentaire = (request.data.get('commentaire') or '').strip()
        if action in services_interventions.ACTIONS_COMMENTAIRE_OBLIGATOIRE and not commentaire:
            return Response({'erreur': True, 'message': 'Le motif est obligatoire pour cette action.'},
                            status=status.HTTP_400_BAD_REQUEST)
        ok, message = services_interventions.appliquer_transition_intervention(
            d, action, request.user, HistoriqueIntervention.ActeurRole.ADMIN,
            commentaire=commentaire, request=request)
        if not ok:
            return Response({'erreur': True, 'message': message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_detail(_demande_ou_none(d.pk), request))


class InterventionAdminAssignerView(APIView):
    """POST /administration/interventions/<id>/assigner/ {artisan_id, commentaire?}
    — réassigne à un partenaire actif du même type (statut en_attente ou
    refusee) ; la demande repasse en_attente, historique + notifications."""
    permission_classes = _ECRITURE

    def post(self, request, pk=None):
        d = DemandeIntervention.objects.select_related('user', 'artisan').filter(pk=pk).first()
        if d is None:
            return _introuvable()
        try:
            artisan = ProfilPartenaire.objects.select_related('user').filter(
                pk=int(request.data.get('artisan_id'))).first()
        except (TypeError, ValueError):
            artisan = None
        if artisan is None:
            return Response({'erreur': True, 'message': 'artisan_id invalide ou introuvable.'},
                            status=status.HTTP_400_BAD_REQUEST)
        ok, message = services_interventions.assigner_intervention(
            d, artisan, request.user, commentaire=(request.data.get('commentaire') or '').strip(),
            request=request)
        if not ok:
            return Response({'erreur': True, 'message': message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_detail(_demande_ou_none(d.pk), request))


class InterventionAdminArtisansCompatiblesView(APIView):
    """GET /administration/interventions/<id>/artisans-compatibles/ — choix
    proposés pour la réassignation (même type, actifs, hors artisan actuel)."""
    permission_classes = _ECRITURE

    def get(self, request, pk=None):
        d = DemandeIntervention.objects.select_related('artisan').filter(pk=pk).first()
        if d is None:
            return _introuvable()
        qs = services_interventions.artisans_compatibles(d).select_related('user').order_by('nom_commerce')
        return Response({'resultats': [{
            'id': p.id, 'nom': p.nom_commerce, 'ville': p.ville,
            'telephone': p.telephone_pro or p.user.telephone,
        } for p in qs]})


class InterventionAdminNotesView(APIView):
    """POST /administration/interventions/<id>/notes/ {texte} — note interne
    (jamais exposée au client ni à l'artisan)."""
    permission_classes = _ECRITURE

    def post(self, request, pk=None):
        d = DemandeIntervention.objects.filter(pk=pk).first()
        if d is None:
            return _introuvable()
        texte = (request.data.get('texte') or '').strip()
        if not texte:
            return Response({'erreur': True, 'message': 'Le texte de la note est requis.'},
                            status=status.HTTP_400_BAD_REQUEST)
        note = NoteAdminIntervention.objects.create(demande=d, auteur=request.user, texte=texte)
        return Response(_note_dict(note), status=status.HTTP_201_CREATED)
