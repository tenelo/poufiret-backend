"""Endpoints du bloc administration (G5), réservés au super-admin.

- Tableau de bord (réexpose les stats de connexion) + répartition appareils.
- Exports CSV (sessions, appareils).
- Actions de modération : suspendre / réactiver / bannir / supprimer.
Tout est protégé par EstSuperAdmin (is_superuser).
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from django.contrib.auth import get_user_model

from apps.core.permissions import EstSuperAdmin
from apps.core.exports import reponse_csv
from . import services, moderation
from .models import JournalModeration

User = get_user_model()


class DashboardG5View(APIView):
    """Vue d'ensemble G5 : stats de connexion + répartition appareils."""
    permission_classes = [IsAuthenticated, EstSuperAdmin]

    def get(self, request):
        from apps.analytics.stats_connexion import tableau_de_bord
        data = tableau_de_bord()
        data['appareils'] = services.repartition_appareils()
        data['comptes_par_statut'] = services.comptes_par_statut()
        return Response(data)


class AppareilsExportView(APIView):
    """Export CSV détaillé des appareils."""
    permission_classes = [IsAuthenticated, EstSuperAdmin]

    def get(self, request):
        actives = request.query_params.get('actives', '1') != '0'
        entetes, lignes = services.export_appareils_lignes(actives)
        return reponse_csv('appareils', entetes, lignes)


class ModerationView(APIView):
    """Action de modération sur un compte cible (super-admin only).

    POST body : { "cible_id": "...", "action": "suspendre|reactiver|bannir|
                  supprimer_soft|supprimer_hard", "motif": "..." }
    """
    permission_classes = [IsAuthenticated, EstSuperAdmin]

    ACTIONS = {
        'suspendre': moderation.suspendre,
        'reactiver': moderation.reactiver,
        'bannir': moderation.bannir,
        'supprimer_soft': moderation.supprimer_soft,
        'supprimer_hard': moderation.supprimer_hard,
        'restaurer': moderation.restaurer,
    }

    def post(self, request):
        cible_id = request.data.get('cible_id')
        action = request.data.get('action')
        motif = request.data.get('motif', '')

        fn = self.ACTIONS.get(action)
        if fn is None:
            return Response(
                {'detail': f'Action inconnue. Choix : {list(self.ACTIONS)}.'},
                status=status.HTTP_400_BAD_REQUEST)

        try:
            cible = User.objects.get(id=cible_id)
        except (User.DoesNotExist, ValueError, TypeError):
            return Response({'detail': 'Compte cible introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)

        # Garde-fou : le super-admin ne peut pas se modérer lui-même.
        if cible.id == request.user.id:
            return Response(
                {'detail': 'Vous ne pouvez pas vous modérer vous-même.'},
                status=status.HTTP_400_BAD_REQUEST)

        fn(request.user, cible, motif=motif)
        return Response({'detail': 'Action effectuée.', 'action': action})


class JournalModerationView(APIView):
    """Consultation du journal d'audit de modération (super-admin)."""
    permission_classes = [IsAuthenticated, EstSuperAdmin]

    def get(self, request):
        entrees = JournalModeration.objects.select_related(
            'acteur', 'cible')[:200]
        data = [{
            'date': j.cree_le.isoformat(),
            'action': j.action,
            'action_libelle': j.get_action_display(),
            'acteur': getattr(j.acteur, 'telephone', None),
            'cible': j.cible_identifiant,
            'cible_role': j.cible_role,
            'motif': j.motif,
        } for j in entrees]
        return Response({'total': JournalModeration.objects.count(),
                         'entrees': data})


class JournalExportView(APIView):
    """Export CSV du journal de modération."""
    permission_classes = [IsAuthenticated, EstSuperAdmin]

    def get(self, request):
        from django.utils import timezone
        entetes = ['date', 'action', 'acteur', 'cible', 'cible_role', 'motif']
        lignes = []
        for j in JournalModeration.objects.select_related('acteur').iterator():
            lignes.append([
                timezone.localtime(j.cree_le).strftime('%Y-%m-%d %H:%M:%S'),
                j.get_action_display(),
                getattr(j.acteur, 'telephone', ''),
                j.cible_identifiant,
                j.cible_role,
                j.motif,
            ])
        return reponse_csv('journal_moderation', entetes, lignes)
