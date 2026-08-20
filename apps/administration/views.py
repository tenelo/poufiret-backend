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
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.permissions import EstAdmin, EstSuperAdmin, ADroitDe
from apps.core.exports import reponse_csv
from . import services, moderation, faveurs, partenaires
from apps.users.models import ProfilPartenaire, PlanAbonnement
from apps.users.serializers import MonProfilPartenaireSerializer
from apps.publicites.models import CreditFormulePub, FormulePublicite, Publicite
from apps.publicites import credits as credits_pub
from .models import JournalModeration, PermissionsAdmin

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
            statut=ProfilPartenaire.Statut.EN_ATTENTE).order_by('created_at')
        demandes = [{
            'id': p.id,
            'nom_commerce': p.nom_commerce,
            'telephone': p.user.telephone,
            'nom_complet': p.user.get_full_name(),
            'departement': getattr(p.departement, 'nom', None),
            'type_partenaire': p.type_partenaire,
            'cree_le': p.created_at,
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


class MesPermissionsView(APIView):
    """Rôle + capacités admin de l'utilisateur connecté.

    Sert de source de vérité au front Angular pour construire dynamiquement
    le menu et les gardes de routes, sans dupliquer la liste des capacités
    côté client. La liste des capacités est introspectée depuis les
    BooleanField de PermissionsAdmin pour ne jamais se désynchroniser du
    modèle réel.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        noms_capacites = [
            champ.name for champ in PermissionsAdmin._meta.get_fields()
            if isinstance(champ, models.BooleanField)
        ]

        if user.is_superuser:
            capacites = {nom: True for nom in noms_capacites}
        else:
            perms = getattr(user, 'permissions_admin', None)
            if user.is_staff and perms is not None:
                capacites = {nom: getattr(perms, nom) for nom in noms_capacites}
            else:
                capacites = {nom: False for nom in noms_capacites}

        return Response({
            'role': user.role,
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
            'capacites': capacites,
        })


class ChangerFormulePubliciteView(APIView):
    """Réassigne la formule d'une publicité (avant de l'offrir en faveur).

    Même capacité que la faveur pub (offrir_campagne) : sert typiquement à
    ramener une pub soumise avec une formule chère au forfait effectivement
    offert, avant d'appeler FaveurPubliciteView.
    """
    permission_classes = [IsAuthenticated, ADroitDe('offrir_campagne')]

    STATUTS_INTERDITS = {Publicite.Statut.ACTIVE, Publicite.Statut.TERMINEE}

    def patch(self, request, pk):
        pub = Publicite.objects.select_related('formule', 'partenaire__user').filter(pk=pk).first()
        if pub is None:
            return Response({'detail': 'Publicité introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)

        formule_id = request.data.get('formule_id')
        if not formule_id:
            return Response({'detail': 'formule_id requis.'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            nouvelle_formule = FormulePublicite.objects.filter(
                pk=formule_id, est_active=True).first()
        except (ValueError, TypeError, ValidationError):
            nouvelle_formule = None
        if nouvelle_formule is None:
            return Response(
                {'detail': 'Formule introuvable ou inactive.'},
                status=status.HTTP_400_BAD_REQUEST)

        if pub.statut in self.STATUTS_INTERDITS:
            return Response(
                {'detail': f"Impossible de changer la formule d'une publicité "
                           f"au statut « {pub.get_statut_display()} »."},
                status=status.HTTP_400_BAD_REQUEST)

        ancienne_formule = pub.formule
        pub.formule = nouvelle_formule
        pub.save(update_fields=['formule'])

        try:
            moderation._journaliser(
                request.user, pub.partenaire.user, 'changer_formule',
                f"Pub « {pub.titre} » : formule {ancienne_formule.nom} "
                f"→ {nouvelle_formule.nom}",
            )
        except Exception:
            pass

        return Response({
            'id': str(pub.id),
            'titre': pub.titre,
            'statut': pub.statut,
            'formule': nouvelle_formule.nom,
            'formule_id': nouvelle_formule.id,
            'prix_formule': nouvelle_formule.prix,
        }, status=status.HTTP_200_OK)


class RecherchePartenairesView(APIView):
    """Recherche un partenaire par nom d'enseigne ou téléphone.

    Sert de premier pas au parcours « accorder un crédit de formule pub » :
    l'admin cherche le partenaire avant de lui offrir un crédit.
    GET ?q=<texte> — moins de 2 caractères => liste vide (pas d'erreur).
    """
    permission_classes = [IsAuthenticated, ADroitDe('offrir_campagne')]

    def get(self, request):
        q = request.query_params.get('q', '').strip()
        if len(q) < 2:
            return Response({'resultats': []})

        qs = ProfilPartenaire.objects.select_related(
            'user', 'departement', 'plan').filter(
            Q(nom_commerce__icontains=q) | Q(user__telephone__icontains=q)
        ).order_by('nom_commerce')[:20]

        resultats = [{
            'id': p.id,
            'nom_commerce': p.nom_commerce,
            'telephone': p.user.telephone,
            'type_partenaire': p.type_partenaire,
            'type_partenaire_libelle': p.get_type_partenaire_display(),
            'departement': getattr(p.departement, 'nom', None),
            'statut': p.statut,
            'statut_libelle': p.get_statut_display(),
        } for p in qs]
        return Response({'resultats': resultats})


def _credit_dict(credit):
    accorde_par = None
    if credit.accorde_par_id:
        accorde_par = (getattr(credit.accorde_par, 'telephone', '')
                       or getattr(credit.accorde_par, 'username', '')) or None
    return {
        'id': str(credit.id),
        'formule_id': credit.formule_id,
        'formule_nom': credit.formule.nom,
        'formule_prix': credit.formule.prix,
        'statut': credit.statut,
        'motif': credit.motif,
        'accorde_par': accorde_par,
        'cree_le': credit.cree_le,
        'consomme_le': credit.consomme_le,
        'publicite_consommatrice_id': (
            str(credit.publicite_consommatrice_id)
            if credit.publicite_consommatrice_id else None
        ),
    }


class CreditsPartenaireView(APIView):
    """Crédits de formule pub d'un partenaire : liste (GET) et octroi (POST).

    pk = id du ProfilPartenaire (pas du User).
    """
    permission_classes = [IsAuthenticated, ADroitDe('offrir_campagne')]

    def _partenaire(self, pk):
        return ProfilPartenaire.objects.select_related('user').filter(pk=pk).first()

    def get(self, request, pk):
        partenaire = self._partenaire(pk)
        if partenaire is None:
            return Response({'detail': 'Partenaire introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)

        qs = CreditFormulePub.objects.filter(partenaire=partenaire).select_related(
            'formule', 'accorde_par').order_by('-cree_le')

        return Response({
            'partenaire': {
                'id': partenaire.id,
                'nom_commerce': partenaire.nom_commerce,
                'telephone': partenaire.user.telephone,
            },
            'credits': [_credit_dict(c) for c in qs],
        })

    def post(self, request, pk):
        partenaire = self._partenaire(pk)
        if partenaire is None:
            return Response({'detail': 'Partenaire introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)

        formule_id = request.data.get('formule_id')
        if not formule_id:
            return Response({'detail': 'formule_id requis.'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            formule = FormulePublicite.objects.filter(
                pk=formule_id, est_active=True).first()
        except (ValueError, TypeError, ValidationError):
            formule = None
        if formule is None:
            return Response({'detail': 'Formule introuvable ou inactive.'},
                            status=status.HTTP_400_BAD_REQUEST)

        motif = request.data.get('motif', '')
        try:
            credit = credits_pub.accorder_credit(
                request.user, partenaire, formule, motif)
        except ValueError as exc:
            return Response({'detail': str(exc)},
                            status=status.HTTP_400_BAD_REQUEST)

        return Response(_credit_dict(credit), status=status.HTTP_201_CREATED)


class CreditDetailView(APIView):
    """DELETE : retire un crédit de formule pub encore disponible."""
    permission_classes = [IsAuthenticated, ADroitDe('offrir_campagne')]

    def delete(self, request, pk):
        credit = CreditFormulePub.objects.select_related(
            'partenaire__user', 'formule').filter(pk=pk).first()
        if credit is None:
            return Response({'detail': 'Crédit introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)

        motif = request.data.get('motif', '')
        try:
            credits_pub.retirer_credit(request.user, credit, motif)
        except ValueError as exc:
            return Response({'detail': str(exc)},
                            status=status.HTTP_400_BAD_REQUEST)

        return Response({'detail': 'Crédit retiré.'}, status=status.HTTP_200_OK)
