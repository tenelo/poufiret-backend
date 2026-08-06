"""Endpoints du bloc administration (G5), réservés au super-admin.

- Tableau de bord (réexpose les stats de connexion) + répartition appareils.
- Exports CSV (sessions, appareils).
- Actions de modération : suspendre / réactiver / bannir / supprimer.
Protégé par la grille de permissions granulaire (ADroitDe), sauf la
modération de comptes qui reste réservée au super-admin (EstSuperAdmin).
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from django.contrib.auth import get_user_model

from apps.core.permissions import EstAdmin, EstSuperAdmin, ADroitDe
from apps.core.exports import reponse_csv
from . import services, moderation, faveurs, partenaires
from apps.users.models import ProfilPartenaire, PlanAbonnement
from apps.users.serializers import MonProfilPartenaireSerializer
from apps.publicites.models import Publicite
from .models import JournalModeration

User = get_user_model()


class DashboardG5View(APIView):
    """Vue d'ensemble G5 : stats de connexion + répartition appareils."""
    permission_classes = [IsAuthenticated, ADroitDe('voir_stats')]

    def get(self, request):
        from apps.analytics.stats_connexion import tableau_de_bord
        data = tableau_de_bord()
        data['appareils'] = services.repartition_appareils()
        data['comptes_par_statut'] = services.comptes_par_statut()
        return Response(data)


class AppareilsExportView(APIView):
    """Export CSV détaillé des appareils."""
    permission_classes = [IsAuthenticated, ADroitDe('exporter_csv')]

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
    """Consultation du journal d'audit de modération (capacité lire_journal)."""
    permission_classes = [IsAuthenticated, ADroitDe('lire_journal')]

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
    permission_classes = [IsAuthenticated, ADroitDe('lire_journal', 'exporter_csv')]

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


class IndicateursPartenairesView(APIView):
    """Tableau de bord des indicateurs partenaires (capacité voir_indicateurs).

    Répartition par plan/type/département/statut, certifiés, faveurs,
    et abonnements expirant bientôt (tranches exclusives).
    """
    permission_classes = [IsAuthenticated, ADroitDe('voir_indicateurs')]

    def get(self, request):
        from . import indicateurs_partenaires as ip
        return Response(ip.tableau_de_bord())


class PartenairesExportView(APIView):
    """Export CSV détaillé des partenaires (super-admin)."""
    permission_classes = [IsAuthenticated, ADroitDe('exporter_csv')]

    def get(self, request):
        from . import indicateurs_partenaires as ip
        entetes, lignes = ip.export_partenaires_lignes()
        return reponse_csv('partenaires', entetes, lignes)


class FaveurView(APIView):
    """Accorde (POST) ou retire (DELETE) une faveur a un partenaire.

    Geste commercial : accessible a EstAdmin (donc admin ET super-admin).
    POST   body: {"plan_code": "premium", "motif": "Partenariat"}
    DELETE body: {"motif": "Fin de partenariat"} (optionnel)
    """
    permission_classes = [IsAuthenticated, ADroitDe('accorder_faveur')]

    def _profil(self, pk):
        return ProfilPartenaire.objects.select_related(
            'user', 'plan').filter(pk=pk).first()

    def post(self, request, pk):
        profil = self._profil(pk)
        if profil is None:
            return Response({'detail': 'Partenaire introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)
        code = request.data.get('plan_code')
        plan = PlanAbonnement.objects.filter(code=code, est_actif=True).first()
        if plan is None:
            return Response(
                {'detail': "plan_code manquant ou plan inactif/inexistant."},
                status=status.HTTP_400_BAD_REQUEST)
        motif = request.data.get('motif', '')
        profil = faveurs.accorder_faveur(request.user, profil, plan, motif)
        return Response(MonProfilPartenaireSerializer(profil).data,
                        status=status.HTTP_200_OK)

    def delete(self, request, pk):
        profil = self._profil(pk)
        if profil is None:
            return Response({'detail': 'Partenaire introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)
        motif = request.data.get('motif', '')
        profil = faveurs.retirer_faveur(request.user, profil, motif)
        return Response(MonProfilPartenaireSerializer(profil).data,
                        status=status.HTTP_200_OK)


def _faveur_pub_reponse(pub):
    """Petite reponse dediee (le serializer public n'expose pas statut/faveur)."""
    return {
        'id': str(pub.id),
        'titre': pub.titre,
        'statut': pub.statut,
        'est_faveur': pub.est_faveur,
        'debut_diffusion': pub.debut_diffusion,
        'fin_diffusion': pub.fin_diffusion,
        'faveur_motif': pub.faveur_motif,
    }


class FaveurPubliciteView(APIView):
    """Offre (POST) ou retire (DELETE) une campagne publicitaire gratuite.

    Geste commercial : EstAdmin (admin ET super-admin).
    POST   body: {"motif": "Lancement"}  -> active la pub sans paiement
    DELETE body: {"motif": "..."}         -> termine la pub offerte
    """
    permission_classes = [IsAuthenticated, ADroitDe('offrir_campagne')]

    def _pub(self, pk):
        return Publicite.objects.select_related(
            'partenaire__user', 'formule').filter(pk=pk).first()

    def post(self, request, pk):
        pub = self._pub(pk)
        if pub is None:
            return Response({'detail': 'Publicité introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)
        motif = request.data.get('motif', '')
        pub = faveurs.offrir_campagne(request.user, pub, motif)
        return Response(_faveur_pub_reponse(pub), status=status.HTTP_200_OK)

    def delete(self, request, pk):
        pub = self._pub(pk)
        if pub is None:
            return Response({'detail': 'Publicité introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)
        motif = request.data.get('motif', '')
        pub = faveurs.retirer_campagne_offerte(request.user, pub, motif)
        return Response(_faveur_pub_reponse(pub), status=status.HTTP_200_OK)


class DemandesPartenariatView(APIView):
    """Demandes de partenariat en attente (liste + nombre) et décision.

    GET  -> {"total": N, "demandes": [...]}
    POST -> {"partenaire_id": <pk>, "decision": "accepter"|"rejeter",
             "motif": "..."}
    """
    permission_classes = [IsAuthenticated, ADroitDe('valider_devenir_partenaire')]

    def get(self, request):
        qs = ProfilPartenaire.objects.select_related(
            'user', 'departement', 'plan').filter(
            statut=ProfilPartenaire.Statut.EN_ATTENTE).order_by('cree_le')
        demandes = [{
            'id': p.id,
            'nom_commerce': p.nom_commerce,
            'telephone': p.user.telephone,
            'nom_complet': p.user.get_full_name(),
            'departement': getattr(p.departement, 'nom', None),
            'type_partenaire': p.type_partenaire,
            'cree_le': p.cree_le,
        } for p in qs]
        return Response({'total': len(demandes), 'demandes': demandes})

    def post(self, request):
        pk = request.data.get('partenaire_id')
        decision = request.data.get('decision')
        motif = request.data.get('motif', '')
        profil = ProfilPartenaire.objects.select_related('user').filter(
            pk=pk, statut=ProfilPartenaire.Statut.EN_ATTENTE).first()
        if profil is None:
            return Response(
                {'detail': 'Demande introuvable ou déjà traitée.'},
                status=status.HTTP_404_NOT_FOUND)
        if decision == 'accepter':
            partenaires.accepter_partenaire(request.user, profil, motif)
        elif decision == 'rejeter':
            partenaires.rejeter_partenaire(request.user, profil, motif)
        else:
            return Response(
                {'detail': "decision doit valoir 'accepter' ou 'rejeter'."},
                status=status.HTTP_400_BAD_REQUEST)
        return Response({'statut': profil.statut, 'id': profil.id},
                        status=status.HTTP_200_OK)
