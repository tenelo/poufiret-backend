"""Vues du centre de gestion admin des commandes.

Réservées à ADroitDe('gerer_commandes') (super-admin toujours autorisé via
le court-circuit déjà présent dans ADroitDe). Réutilise la même machine
d'état et les mêmes notifications que le flux partenaire (apps.orders.services)
— aucune duplication, mode parallèle.
"""
from datetime import datetime

from django.db.models import Count, DecimalField, DurationField, ExpressionWrapper, F, Prefetch, Q, Sum, Value
from django.db.models.functions import Coalesce, ExtractHour, ExtractIsoWeekDay, TruncDate
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exports import reponse_csv
from apps.core.permissions import ADroitDe
from apps.livraison.models import Course
from apps.users.models import ProfilPartenaire

from .models import Commande, HistoriqueCommande, NoteAdminCommande
from .serializers_admin import (
    CommandeAdminDetailSerializer, CommandeAdminListSerializer,
    NoteAdminCommandeSerializer,
)
from .services import (
    GROUPE_PAR_STATUT, LIBELLES_GROUPE, STATUTS_PAR_GROUPE,
    DemandeLivreurInvalide, LivraisonEnCoursError,
    appliquer_transition_commande, demander_livreur,
)

_PERMISSION = [permissions.IsAuthenticated, ADroitDe('gerer_commandes')]

_ORDERING_MAP = {
    'cree_le': 'created_at', '-cree_le': '-created_at',
    'montant_total': 'total', '-montant_total': '-total',
}


def _parser_date(valeur):
    if not valeur:
        return None
    try:
        return datetime.strptime(valeur[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _commandes_admin_qs(request, avec_groupe_statut=True):
    """Queryset commun à la liste, aux compteurs et à l'export. Sans N+1 :
    select_related pour client/partenaire, un seul prefetch pour les
    courses (triées, avec le livreur)."""
    qs = (Commande.objects.select_related(
              'user', 'partenaire', 'partenaire__user', 'partenaire__departement')
          .prefetch_related(
              Prefetch('courses',
                       queryset=Course.objects.select_related('livreur__user').order_by('-cree_le'),
                       to_attr='courses_triees'))
          .annotate(nb_articles=Coalesce(Sum('lignes__quantite'), Value(0))))

    p = request.query_params
    if avec_groupe_statut:
        groupe = p.get('groupe')
        if groupe:
            if groupe not in STATUTS_PAR_GROUPE:
                return qs.none(), f'Groupe inconnu : {groupe}.'
            qs = qs.filter(statut__in=STATUTS_PAR_GROUPE[groupe])
        statut = p.get('statut')
        if statut:
            valeurs = {v for v, _ in Commande.Statut.choices}
            if statut not in valeurs:
                return qs.none(), f'Statut inconnu : {statut}.'
            qs = qs.filter(statut=statut)

    partenaire = p.get('partenaire')
    if partenaire:
        try:
            qs = qs.filter(partenaire_id=int(partenaire))
        except (ValueError, TypeError):
            return qs.none(), 'Partenaire invalide.'
    client = p.get('client')
    if client:
        try:
            qs = qs.filter(user_id=int(client))
        except (ValueError, TypeError):
            return qs.none(), 'Client invalide.'
    departement = p.get('departement')
    if departement:
        try:
            qs = qs.filter(partenaire__departement_id=int(departement))
        except (ValueError, TypeError):
            return qs.none(), 'Département invalide.'
    mode_livraison = p.get('mode_livraison')
    if mode_livraison:
        valeurs = {v for v, _ in Commande.ModeLivraison.choices}
        if mode_livraison not in valeurs:
            return qs.none(), f'Mode de livraison inconnu : {mode_livraison}.'
        qs = qs.filter(mode_livraison=mode_livraison)

    search = (p.get('search') or '').strip()
    if search:
        qs = qs.filter(
            Q(numero__icontains=search)
            | Q(user__first_name__icontains=search)
            | Q(user__last_name__icontains=search)
            | Q(user__username__icontains=search)
            | Q(user__telephone__icontains=search)
            | Q(partenaire__nom_commerce__icontains=search)
            | Q(partenaire__telephone_pro__icontains=search)
            | Q(partenaire__user__telephone__icontains=search))

    du = _parser_date(p.get('du'))
    if du:
        qs = qs.filter(created_at__date__gte=du)
    au = _parser_date(p.get('au'))
    if au:
        qs = qs.filter(created_at__date__lte=au)

    return qs, None


def _compteurs_groupe(request):
    """Nombre de commandes par groupe (ignore ?groupe= et ?statut=, respecte
    les autres filtres) — pour les onglets du centre de gestion."""
    qs, _ = _commandes_admin_qs(request, avec_groupe_statut=False)
    compteurs = {g: 0 for g in LIBELLES_GROUPE}
    # distinct=True : l'annotation nb_articles (Sum via jointure 'lignes')
    # sur `qs` fait un fan-out par ligne ; sans distinct, Count('id') compterait
    # une commande plusieurs fois (autant que de lignes).
    for statut, n in qs.order_by().values_list('statut').annotate(n=Count('id', distinct=True)):
        groupe = GROUPE_PAR_STATUT.get(statut)
        if groupe:
            compteurs[groupe] += n
    compteurs['total'] = sum(compteurs.values())
    return compteurs


class MetaAdminCommandesView(APIView):
    """GET /orders/admin/meta/ — statuts, groupes, modes de livraison."""
    permission_classes = _PERMISSION

    def get(self, request):
        statuts = [{
            'valeur': v, 'libelle': l, 'groupe': GROUPE_PAR_STATUT.get(v, ''),
        } for v, l in Commande.Statut.choices]
        groupes = [{'code': c, 'libelle': l} for c, l in LIBELLES_GROUPE.items()]
        modes = [{'valeur': v, 'libelle': l} for v, l in Commande.ModeLivraison.choices]
        return Response({'statuts': statuts, 'groupes': groupes, 'modes_livraison': modes})


class CommandesAdminListView(generics.ListAPIView):
    """GET /orders/admin/commandes/ — toutes les commandes, filtrables."""
    serializer_class = CommandeAdminListSerializer
    permission_classes = _PERMISSION

    def get_queryset(self):
        qs, erreur = _commandes_admin_qs(self.request)
        self._erreur = erreur
        if erreur:
            return qs
        ordering = self.request.query_params.get('ordering')
        if ordering in _ORDERING_MAP:
            return qs.order_by(_ORDERING_MAP[ordering])
        if self.request.query_params.get('groupe') == 'a_traiter':
            return qs.order_by('created_at')  # les plus anciennes d'abord
        return qs.order_by('-created_at')

    def list(self, request, *args, **kwargs):
        self.get_queryset()
        if getattr(self, '_erreur', None):
            return Response({'erreur': True, 'message': self._erreur},
                            status=status.HTTP_400_BAD_REQUEST)
        reponse = super().list(request, *args, **kwargs)
        reponse.data['compteurs_groupe'] = _compteurs_groupe(request)
        return reponse


class CommandeAdminDetailView(generics.RetrieveAPIView):
    """GET /orders/admin/commandes/<id>/ — détail complet."""
    serializer_class = CommandeAdminDetailSerializer
    permission_classes = _PERMISSION

    def get_queryset(self):
        qs, _ = _commandes_admin_qs(self.request, avec_groupe_statut=False)
        return qs.prefetch_related(
            'lignes', 'notes_admin', 'notes_admin__auteur',
            'historique', 'historique__acteur')


class TransitionAdminView(APIView):
    """POST /orders/admin/commandes/<id>/transition/ {"action", "commentaire"?}
    — applique la transition via la machine d'état partagée
    (services.appliquer_transition_commande), acteur_role='admin'.
    Annulation : commentaire obligatoire."""
    permission_classes = _PERMISSION

    def post(self, request, pk=None):
        commande = Commande.objects.filter(pk=pk).select_related('partenaire').first()
        if commande is None:
            return Response({'erreur': True, 'message': 'Commande introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)
        action = request.data.get('action')
        commentaire = (request.data.get('commentaire') or '').strip()
        if action == Commande.Statut.ANNULEE and not commentaire:
            return Response(
                {'erreur': True, 'message': "Le motif est obligatoire pour annuler une commande."},
                status=status.HTTP_400_BAD_REQUEST)

        ok, message = appliquer_transition_commande(
            commande, action, request.user, HistoriqueCommande.ActeurRole.ADMIN,
            commentaire=commentaire, request=request)
        if not ok:
            return Response({'erreur': True, 'message': message},
                            status=status.HTTP_400_BAD_REQUEST)

        detail = CommandeAdminDetailView()
        detail.request = request
        commande = detail.get_queryset().get(pk=commande.pk)
        return Response(CommandeAdminDetailSerializer(commande, context={'request': request}).data)


class DemanderLivreurAdminView(APIView):
    """POST /orders/admin/commandes/<id>/demander-livreur/ {"commentaire"?}
    — l'admin déclenche une demande de livraison via la couche service
    TeneLivr existante (services.demander_livreur), comme le ferait un
    partenaire. Le commentaire (si fourni) est historisé, sans changer le
    statut au-delà de ce que demander_livreur applique déjà."""
    permission_classes = _PERMISSION

    def post(self, request, pk=None):
        commande = Commande.objects.filter(pk=pk).select_related('partenaire').first()
        if commande is None:
            return Response({'erreur': True, 'message': 'Commande introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            course, resultat = demander_livreur(commande, request.user, type_demandeur='admin')
        except LivraisonEnCoursError as exc:
            return Response(
                {'erreur': True, 'message': str(exc), 'course_numero': exc.numero_course},
                status=status.HTTP_409_CONFLICT)
        except DemandeLivreurInvalide as exc:
            return Response({'erreur': True, 'message': str(exc)},
                            status=status.HTTP_400_BAD_REQUEST)

        commentaire = (request.data.get('commentaire') or '').strip()
        HistoriqueCommande.objects.create(
            commande=commande, statut=commande.statut, acteur=request.user,
            acteur_role=HistoriqueCommande.ActeurRole.ADMIN,
            commentaire=commentaire or f'Livreur demandé (course {course.numero}).',
        )
        return Response({'livraison': {
            'id': str(course.id), 'statut': course.statut,
            'statut_libelle': course.get_statut_display(),
            'livreur_nom': (course.livreur.user.get_full_name() or course.livreur.user.telephone)
                          if course.livreur_id else None,
            'livreur_telephone': course.livreur.user.telephone if course.livreur_id else None,
        }}, status=status.HTTP_201_CREATED)


class NotesAdminCommandeView(APIView):
    """POST /orders/admin/commandes/<id>/notes/ {"texte"} — note interne,
    invisible du client et du partenaire (aucun des deux serializers/vues
    existants n'expose NoteAdminCommande)."""
    permission_classes = _PERMISSION

    def post(self, request, pk=None):
        commande = Commande.objects.filter(pk=pk).first()
        if commande is None:
            return Response({'erreur': True, 'message': 'Commande introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)
        texte = (request.data.get('texte') or '').strip()
        if not texte:
            return Response({'erreur': True, 'message': 'Le texte de la note est requis.'},
                            status=status.HTTP_400_BAD_REQUEST)
        note = NoteAdminCommande.objects.create(
            commande=commande, auteur=request.user, texte=texte)
        return Response(NoteAdminCommandeSerializer(note).data, status=status.HTTP_201_CREATED)


class StatsAdminCommandesView(APIView):
    """GET /orders/admin/stats/?du=&au=&partenaire=&departement=
    (défaut : 30 derniers jours). Agrégations en base, sans N+1."""
    permission_classes = _PERMISSION

    def get(self, request):
        p = request.query_params
        au = _parser_date(p.get('au')) or timezone.localdate()
        du = _parser_date(p.get('du')) or (au - timezone.timedelta(days=30))

        qs = Commande.objects.filter(created_at__date__gte=du, created_at__date__lte=au)
        partenaire = p.get('partenaire')
        if partenaire:
            try:
                qs = qs.filter(partenaire_id=int(partenaire))
            except (ValueError, TypeError):
                return Response({'erreur': True, 'message': 'Partenaire invalide.'}, status=400)
        departement = p.get('departement')
        if departement:
            try:
                qs = qs.filter(partenaire__departement_id=int(departement))
            except (ValueError, TypeError):
                return Response({'erreur': True, 'message': 'Département invalide.'}, status=400)

        total = qs.count()
        par_statut_brut = dict(qs.order_by().values_list('statut').annotate(n=Count('id')))
        compteurs = {g: 0 for g in LIBELLES_GROUPE}
        for statut, n in par_statut_brut.items():
            groupe = GROUPE_PAR_STATUT.get(statut)
            if groupe:
                compteurs[groupe] += n

        montants = qs.aggregate(montant_total=Coalesce(Sum('total'), Value(0, output_field=DecimalField())))
        montant_total = montants['montant_total']
        panier_moyen = (montant_total / total) if total else None

        # Délai de traitement : création -> 1re sortie du groupe a_traiter
        # (1re ligne d'historique de la commande, toutes confondues, puisque
        # 'nouvelle' est le seul statut du groupe a_traiter). Nul pour les
        # commandes sans historique (jamais transitionnées via le point
        # central appliquer_transition_commande — voir rapport).
        delai_traitement = (
            qs.filter(historique__isnull=False)
            .annotate(premiere=F('historique__cree_le'))
            .order_by('id', 'premiere').distinct('id')
            .annotate(delai=ExpressionWrapper(
                F('premiere') - F('created_at'), output_field=DurationField()))
        )
        delai_traitement_min = None
        if delai_traitement.exists():
            secondes = sum(
                d.total_seconds() for d in delai_traitement.values_list('delai', flat=True))
            delai_traitement_min = round(secondes / delai_traitement.count() / 60, 1)

        delai_livraison_qs = qs.filter(
            statut=Commande.Statut.LIVREE, livree_le__isnull=False,
        ).annotate(delai=ExpressionWrapper(
            F('livree_le') - F('created_at'), output_field=DurationField()))
        delai_livraison_min = None
        if delai_livraison_qs.exists():
            secondes = sum(
                d.total_seconds() for d in delai_livraison_qs.values_list('delai', flat=True))
            delai_livraison_min = round(secondes / delai_livraison_qs.count() / 60, 1)

        nb_annulees = compteurs['annulees']
        taux_annulation = round(nb_annulees / total * 100, 1) if total else None

        kpis = {
            'total': total,
            'a_traiter': compteurs['a_traiter'],
            'en_cours': compteurs['en_cours'],
            'terminees': compteurs['terminees'],
            'annulees': compteurs['annulees'],
            'montant_total': montant_total,
            'panier_moyen': round(panier_moyen) if panier_moyen is not None else None,
            'delai_moyen_traitement_min': delai_traitement_min,
            'delai_moyen_livraison_min': delai_livraison_min,
            'taux_annulation': taux_annulation,
        }

        par_jour = [{
            'date': str(r['jour']), 'nb': r['nb'], 'montant': r['montant'] or 0,
        } for r in qs.annotate(jour=TruncDate('created_at'))
                     .values('jour').annotate(nb=Count('id'), montant=Sum('total'))
                     .order_by('jour')]

        libelles_statut = dict(Commande.Statut.choices)
        par_statut = [{
            'statut': v, 'libelle': libelles_statut.get(v, v), 'nb': n,
        } for v, n in par_statut_brut.items()]

        par_groupe = [{
            'groupe': g, 'libelle': LIBELLES_GROUPE[g], 'nb': compteurs[g],
        } for g in LIBELLES_GROUPE]

        par_partenaire = [{
            'id': r['partenaire_id'], 'nom': r['partenaire__nom_commerce'],
            'nb': r['nb'], 'montant': r['montant'] or 0,
        } for r in qs.values('partenaire_id', 'partenaire__nom_commerce')
                        .annotate(nb=Count('id'), montant=Sum('total'))
                        .order_by('-montant')[:10]]

        # Détail par partenaire (TOUS ceux ayant au moins une commande sur la
        # période, mêmes filtres) : une seule requête agrégée, un Count avec
        # filter par groupe. Noms nb_* : `total` est un champ de Commande.
        def _nb_groupe(groupe):
            return Count('id', filter=Q(statut__in=STATUTS_PAR_GROUPE[groupe]))
        par_partenaire_detail = [{
            'id': r['partenaire_id'], 'nom': r['partenaire__nom_commerce'],
            'total': r['nb_total'], 'a_traiter': r['nb_a_traiter'],
            'en_cours': r['nb_en_cours'], 'terminees': r['nb_terminees'],
            'annulees': r['nb_annulees'], 'montant': r['montant'] or 0,
        } for r in qs.values('partenaire_id', 'partenaire__nom_commerce').annotate(
            nb_total=Count('id'),
            nb_a_traiter=_nb_groupe('a_traiter'), nb_en_cours=_nb_groupe('en_cours'),
            nb_terminees=_nb_groupe('terminees'), nb_annulees=_nb_groupe('annulees'),
            montant=Sum('total'),
        ).order_by('-nb_total', 'partenaire__nom_commerce')]

        libelles_type = dict(ProfilPartenaire.TypePartenaire.choices)
        par_type_partenaire = [{
            'type': r['partenaire__type_partenaire'],
            'libelle': libelles_type.get(r['partenaire__type_partenaire'], r['partenaire__type_partenaire']),
            'nb': r['nb'], 'montant': r['montant'] or 0,
        } for r in qs.values('partenaire__type_partenaire')
                     .annotate(nb=Count('id'), montant=Sum('total'))
                     .order_by('-nb')]

        par_client = []
        for r in (qs.values('user_id', 'user__first_name', 'user__last_name',
                            'user__username', 'user__telephone')
                  .annotate(nb=Count('id'), montant=Sum('total'))
                  .order_by('-montant')[:10]):
            nom = (f"{r['user__first_name']} {r['user__last_name']}".strip()
                  or r['user__username'] or r['user__telephone'])
            par_client.append({'id': r['user_id'], 'nom': nom, 'nb': r['nb'],
                               'montant': r['montant'] or 0})

        libelles_mode = dict(Commande.ModeLivraison.choices)
        par_mode_livraison = [{
            'mode': r['mode_livraison'],
            'libelle': libelles_mode.get(r['mode_livraison'], r['mode_livraison']),
            'nb': r['nb'],
        } for r in qs.values('mode_livraison').annotate(nb=Count('id'))]

        par_heure_brut = dict(qs.annotate(h=ExtractHour('created_at'))
                              .order_by().values_list('h').annotate(n=Count('id')))
        par_heure = [{'heure': h, 'nb': par_heure_brut.get(h, 0)} for h in range(24)]

        libelles_jour = {1: 'Lundi', 2: 'Mardi', 3: 'Mercredi', 4: 'Jeudi',
                         5: 'Vendredi', 6: 'Samedi', 7: 'Dimanche'}
        par_jsem_brut = dict(qs.annotate(j=ExtractIsoWeekDay('created_at'))
                             .order_by().values_list('j').annotate(n=Count('id')))
        par_jour_semaine = [{
            'jour': j, 'libelle': libelles_jour[j], 'nb': par_jsem_brut.get(j, 0),
        } for j in range(1, 8)]

        par_departement = [{
            'id': r['partenaire__departement_id'], 'nom': r['partenaire__departement__nom'],
            'nb': r['nb'],
        } for r in qs.filter(partenaire__departement__isnull=False)
                     .values('partenaire__departement_id', 'partenaire__departement__nom')
                     .annotate(nb=Count('id')).order_by('-nb')]

        return Response({
            'kpis': kpis, 'par_jour': par_jour, 'par_statut': par_statut,
            'par_groupe': par_groupe, 'par_partenaire': par_partenaire,
            'par_partenaire_detail': par_partenaire_detail,
            'par_type_partenaire': par_type_partenaire, 'par_client': par_client,
            'par_mode_livraison': par_mode_livraison, 'par_heure': par_heure,
            'par_jour_semaine': par_jour_semaine, 'par_departement': par_departement,
        })


class ExportAdminCommandesView(APIView):
    """GET /orders/admin/commandes/export/ — CSV, mêmes filtres que la liste."""
    permission_classes = _PERMISSION

    def get(self, request):
        qs, erreur = _commandes_admin_qs(request)
        if erreur:
            return Response({'erreur': True, 'message': erreur}, status=400)
        entetes = ['id', 'reference', 'cree_le', 'statut', 'groupe',
                  'montant_total', 'nb_articles', 'mode_livraison',
                  'client_nom', 'client_telephone', 'partenaire_nom',
                  'partenaire_telephone', 'departement']
        lignes = []
        for c in qs.order_by('-created_at'):
            lignes.append([
                c.id, c.numero, c.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                c.statut, GROUPE_PAR_STATUT.get(c.statut, ''), c.total,
                c.nb_articles, c.mode_livraison,
                c.user.get_full_name() or c.user.username or c.user.telephone,
                c.user.telephone, c.partenaire.nom_commerce,
                c.partenaire.telephone_pro or getattr(c.partenaire.user, 'telephone', ''),
                getattr(c.partenaire.departement, 'nom', ''),
            ])
        return reponse_csv('commandes_admin', entetes, lignes)
