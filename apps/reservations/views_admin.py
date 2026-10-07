"""Centre de gestion admin des demandes — mode parallèle à
apps.orders.views_admin (même structure : meta, liste filtrable avec
compteurs par groupe, détail, transition, notes internes, export)."""
from datetime import datetime

from django.db.models import Count, Q
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exports import reponse_csv
from apps.core.permissions import ADroitDe

from .models import DemandeReservation, HistoriqueDemande, NoteAdminDemande
from .serializers import (
    DemandeAdminDetailSerializer, DemandeAdminListSerializer, NoteAdminDemandeSerializer,
)
from .services import GROUPE_PAR_STATUT, LIBELLES_GROUPE, STATUTS_PAR_GROUPE, appliquer_transition_demande

_PERMISSION = [permissions.IsAuthenticated, ADroitDe('gerer_reservations')]


def _parser_date(valeur):
    if not valeur:
        return None
    try:
        return datetime.strptime(valeur[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _demandes_admin_qs(request, avec_groupe_statut=True):
    qs = (DemandeReservation.objects
          .select_related('client', 'partenaire', 'objet')
          .prefetch_related('historique', 'historique__acteur'))
    p = request.query_params
    if avec_groupe_statut:
        groupe = p.get('groupe')
        if groupe:
            if groupe not in STATUTS_PAR_GROUPE:
                return qs.none(), f'Groupe inconnu : {groupe}.'
            qs = qs.filter(statut__in=STATUTS_PAR_GROUPE[groupe])
        statut = p.get('statut')
        if statut:
            valeurs = {v for v, _ in DemandeReservation.Statut.choices}
            if statut not in valeurs:
                return qs.none(), f'Statut inconnu : {statut}.'
            qs = qs.filter(statut=statut)
    nature = p.get('nature')
    if nature:
        valeurs = {v for v, _ in DemandeReservation.Nature.choices}
        if nature not in valeurs:
            return qs.none(), f'Nature inconnue : {nature}.'
        qs = qs.filter(nature=nature)
    partenaire = p.get('partenaire')
    if partenaire:
        try:
            qs = qs.filter(partenaire_id=int(partenaire))
        except (ValueError, TypeError):
            return qs.none(), 'Partenaire invalide.'
    search = (p.get('search') or '').strip()
    if search:
        qs = qs.filter(
            Q(numero__icontains=search)
            | Q(client__first_name__icontains=search)
            | Q(client__last_name__icontains=search)
            | Q(client__telephone__icontains=search)
            | Q(partenaire__nom_commerce__icontains=search))
    du = _parser_date(p.get('du'))
    if du:
        qs = qs.filter(created_at__date__gte=du)
    au = _parser_date(p.get('au'))
    if au:
        qs = qs.filter(created_at__date__lte=au)
    return qs, None


def _compteurs_groupe(request):
    qs, _ = _demandes_admin_qs(request, avec_groupe_statut=False)
    compteurs = {g: 0 for g in LIBELLES_GROUPE}
    for statut, n in qs.order_by().values_list('statut').annotate(n=Count('id', distinct=True)):
        groupe = GROUPE_PAR_STATUT.get(statut)
        if groupe:
            compteurs[groupe] += n
    compteurs['total'] = sum(compteurs.values())
    return compteurs


class MetaAdminDemandesView(APIView):
    """GET /reservations/admin/meta/ — statuts, groupes, natures."""
    permission_classes = _PERMISSION

    def get(self, request):
        statuts = [{'valeur': v, 'libelle': l, 'groupe': GROUPE_PAR_STATUT.get(v, '')}
                  for v, l in DemandeReservation.Statut.choices]
        groupes = [{'code': c, 'libelle': l} for c, l in LIBELLES_GROUPE.items()]
        natures = [{'valeur': v, 'libelle': l} for v, l in DemandeReservation.Nature.choices]
        return Response({'statuts': statuts, 'groupes': groupes, 'natures': natures})


class DemandesAdminListView(generics.ListAPIView):
    """GET /reservations/admin/demandes/?groupe=&nature=&partenaire=&search=&du=&au="""
    serializer_class = DemandeAdminListSerializer
    permission_classes = _PERMISSION

    def get_queryset(self):
        qs, erreur = _demandes_admin_qs(self.request)
        self._erreur = erreur
        if erreur:
            return qs
        if self.request.query_params.get('groupe') == 'a_traiter':
            return qs.order_by('created_at')
        return qs.order_by('-created_at')

    def list(self, request, *args, **kwargs):
        self.get_queryset()
        if getattr(self, '_erreur', None):
            return Response({'erreur': True, 'message': self._erreur}, status=400)
        reponse = super().list(request, *args, **kwargs)
        reponse.data['compteurs_groupe'] = _compteurs_groupe(request)
        return reponse


class DemandeAdminDetailView(generics.RetrieveAPIView):
    """GET /reservations/admin/demandes/<id>/ — détail complet (+ notes internes)."""
    serializer_class = DemandeAdminDetailSerializer
    permission_classes = _PERMISSION

    def get_queryset(self):
        qs, _ = _demandes_admin_qs(self.request, avec_groupe_statut=False)
        return qs.prefetch_related('notes_admin', 'notes_admin__auteur')


class TransitionAdminView(APIView):
    """POST /reservations/admin/demandes/<id>/transition/ {"action", "commentaire"?}
    Refus/annulation : motif obligatoire."""
    permission_classes = _PERMISSION

    def post(self, request, pk=None):
        demande = DemandeReservation.objects.filter(pk=pk).select_related('partenaire').first()
        if demande is None:
            return Response({'erreur': True, 'message': 'Demande introuvable.'}, status=404)
        action = request.data.get('action')
        commentaire = (request.data.get('commentaire') or '').strip()
        if action in (DemandeReservation.Statut.REFUSEE, DemandeReservation.Statut.ANNULEE) and not commentaire:
            return Response({'erreur': True, 'message': 'Le motif est obligatoire pour cette action.'}, status=400)

        ok, message = appliquer_transition_demande(
            demande, action, request.user, HistoriqueDemande.ActeurRole.ADMIN,
            commentaire=commentaire, request=request)
        if not ok:
            return Response({'erreur': True, 'message': message}, status=400)

        demande = (DemandeReservation.objects
                   .select_related('client', 'partenaire', 'objet')
                   .prefetch_related('historique', 'historique__acteur', 'notes_admin', 'notes_admin__auteur')
                   .get(pk=demande.pk))
        return Response(DemandeAdminDetailSerializer(demande, context={'request': request}).data)


class NotesAdminDemandeView(APIView):
    """POST /reservations/admin/demandes/<id>/notes/ {"texte"} — note
    interne, invisible du client et du loueur."""
    permission_classes = _PERMISSION

    def post(self, request, pk=None):
        demande = DemandeReservation.objects.filter(pk=pk).first()
        if demande is None:
            return Response({'erreur': True, 'message': 'Demande introuvable.'}, status=404)
        texte = (request.data.get('texte') or '').strip()
        if not texte:
            return Response({'erreur': True, 'message': 'Le texte de la note est requis.'}, status=400)
        note = NoteAdminDemande.objects.create(demande=demande, auteur=request.user, texte=texte)
        return Response(NoteAdminDemandeSerializer(note).data, status=201)


class ExportAdminDemandesView(APIView):
    """GET /reservations/admin/demandes/export/ — CSV, mêmes filtres que la liste."""
    permission_classes = _PERMISSION

    def get(self, request):
        qs, erreur = _demandes_admin_qs(request)
        if erreur:
            return Response({'erreur': True, 'message': erreur}, status=400)
        entetes = ['Numero', 'Nature', 'Statut', 'Client', 'Telephone', 'Partenaire', 'Objet',
                  'Date souhaitee', 'Date debut', 'Date fin', 'Cree le']
        lignes = [[
            d.numero, d.get_nature_display(), d.get_statut_display(),
            d.client.get_full_name() or d.client.username, d.client.telephone,
            d.partenaire.nom_commerce, d.objet.nom, d.date_souhaitee, d.date_debut, d.date_fin,
            d.created_at,
        ] for d in qs.order_by('-created_at')]
        return reponse_csv('demandes_reservation', entetes, lignes)
