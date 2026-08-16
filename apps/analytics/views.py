from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from waffle import flag_is_active

from .models import ProfilNavigation, TempsSessionUtilisateur


def _profil(utilisateur):
    aujourdhui = timezone.localdate()
    mois = aujourdhui.replace(day=1)
    profil, _ = ProfilNavigation.objects.get_or_create(
        utilisateur=utilisateur, defaults={'mois_reference': mois},
    )
    if profil.mois_reference != mois:
        # Nouveau mois : remise à zéro des compteurs mensuels
        profil.mois_reference = mois
        profil.nb_articles_vus_mois = 0
        profil.nb_vues_catalogue_mois = 0
        profil.temps_cumule_secondes_mois = 0
    return profil


class DemarrerSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not flag_is_active(request._request, 'analytics_actif'):
            return Response({'detail': 'Analytics désactivé.'}, status=status.HTTP_403_FORBIDDEN)
        # Clôturer les sessions restées actives (app tuée sans fin propre)
        TempsSessionUtilisateur.objects.filter(
            utilisateur=request.user, est_active=True,
        ).update(est_active=False)
        session = TempsSessionUtilisateur.objects.create(
            utilisateur=request.user,
            source=request.data.get('source', TempsSessionUtilisateur.Source.MOBILE),
        )
        return Response({'session_id': str(session.id)}, status=status.HTTP_201_CREATED)


class PingSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not flag_is_active(request._request, 'analytics_actif'):
            return Response({'detail': 'Analytics désactivé.'}, status=status.HTTP_403_FORBIDDEN)
        session_id = request.data.get('session_id')
        try:
            session = TempsSessionUtilisateur.objects.get(
                id=session_id, utilisateur=request.user, est_active=True,
            )
        except (TempsSessionUtilisateur.DoesNotExist, ValueError, TypeError):
            return Response({'detail': 'Session introuvable.'}, status=status.HTTP_404_NOT_FOUND)

        maintenant = timezone.now()
        delta = int((maintenant - session.dernier_ping).total_seconds())
        # Ignorer les deltas aberrants (> 5 min = app revenue après longue pause)
        delta = min(max(delta, 0), 300)
        session.dernier_ping = maintenant
        session.save(update_fields=['dernier_ping', 'modifie_le'])

        profil = _profil(request.user)
        profil.temps_cumule_secondes_mois += delta
        profil.derniere_activite = maintenant
        profil.save()

        return Response({
            'duree_secondes': session.duree_secondes,
            'minute_session': session.minute_session,
        })


class EngagementAdminView(APIView):
    """Liste des profils de navigation + statut client actif (admin/Angular)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.is_staff:
            return Response({'detail': 'Réservé aux administrateurs.'},
                            status=status.HTTP_403_FORBIDDEN)
        profils = ProfilNavigation.objects.select_related('utilisateur').order_by('-derniere_activite')
        donnees = [{
            'utilisateur_id': p.utilisateur_id,
            'telephone': p.utilisateur.telephone,
            'username': p.utilisateur.username,
            'nb_articles_vus_mois': p.nb_articles_vus_mois,
            'nb_vues_catalogue_mois': p.nb_vues_catalogue_mois,
            'temps_cumule_secondes_mois': p.temps_cumule_secondes_mois,
            'derniere_activite': p.derniere_activite,
            'est_client_actif': p.est_client_actif,
            'categories_consultees': p.categories_consultees,
        } for p in profils]
        nb_actifs = sum(1 for d in donnees if d['est_client_actif'])
        return Response({'nb_profils': len(donnees), 'nb_clients_actifs': nb_actifs, 'profils': donnees})


class VisiteCategorieView(APIView):
    """POST categorie/visite/ — l'utilisateur entre dans un catalogue."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not flag_is_active(request._request, 'analytics_actif'):
            return Response({'detail': 'Analytics désactivé.'},
                            status=status.HTTP_403_FORBIDDEN)
        slug = request.data.get('categorie')
        if not slug:
            # Le client peut envoyer l'id numerique plutot que le slug.
            categorie_id = request.data.get('categorie_id')
            if categorie_id:
                from apps.catalog.models import Categorie
                cat = Categorie.objects.filter(pk=categorie_id).only('slug').first()
                slug = cat.slug if cat else None
        if not slug:
            return Response({'erreur': True, 'message': 'Catégorie manquante.'},
                            status=status.HTTP_400_BAD_REQUEST)
        from .services import enregistrer_visite_categorie
        enregistrer_visite_categorie(request.user, slug)
        return Response({'message': 'Visite enregistrée.'},
                        status=status.HTTP_201_CREATED)


class VueVitrineView(APIView):
    """POST vitrine/vue/ — consultation de la vitrine d'un partenaire.

    Accessible sans authentification : un visiteur anonyme incremente le
    compteur public, sans alimenter de profil de navigation.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        if not flag_is_active(request._request, 'analytics_actif'):
            return Response({'detail': 'Analytics désactivé.'},
                            status=status.HTTP_403_FORBIDDEN)
        partenaire_id = request.data.get('partenaire')
        if not partenaire_id:
            return Response({'erreur': True, 'message': 'Partenaire manquant.'},
                            status=status.HTTP_400_BAD_REQUEST)
        from apps.users.models import ProfilPartenaire
        partenaire = ProfilPartenaire.objects.filter(pk=partenaire_id).first()
        if partenaire is None:
            return Response({'erreur': True, 'message': 'Partenaire introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)
        from .services import enregistrer_vue_vitrine
        enregistrer_vue_vitrine(
            request.user, partenaire,
            source=request.data.get('source', 'autre'),
            avec_catalogue=bool(request.data.get('avec_catalogue', True)),
        )
        return Response({'message': 'Vue enregistrée.'},
                        status=status.HTTP_201_CREATED)


class VueServiceLivraisonView(APIView):
    """POST livraison/vue/ — ouverture de l'ecran/service livraison.

    Accessible sans authentification : un visiteur anonyme peut aussi
    ouvrir l'onglet, sans alimenter de profil de navigation.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        if not flag_is_active(request._request, 'analytics_actif'):
            return Response({'detail': 'Analytics desactive.'},
                            status=status.HTTP_403_FORBIDDEN)
        from .services import enregistrer_vue_service_livraison
        enregistrer_vue_service_livraison(
            request.user, source=request.data.get('source', 'onglet'),
        )
        return Response({'message': 'Vue enregistree.'},
                        status=status.HTTP_201_CREATED)


class OuvertureDemandeInterventionView(APIView):
    """POST intervention/ouverture/ — l'utilisateur ouvre l'ecran de demande.

    Signal d'intention forte, compte comme une interaction meme sans envoi.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not flag_is_active(request._request, 'analytics_actif'):
            return Response({'detail': 'Analytics désactivé.'},
                            status=status.HTTP_403_FORBIDDEN)
        from .services import enregistrer_demande_intervention
        enregistrer_demande_intervention(request.user)
        return Response({'message': 'Ouverture enregistrée.'},
                        status=status.HTTP_201_CREATED)


class StatsConnexionAdminView(APIView):
    """Tableau de bord des stats de connexion (admin/Angular G5).

    En ligne à l'instant t (ventilé par rôle), comptes créés, connexions
    distinctes et nombre d'ouvertures sur aujourd'hui / 7 jours / 30 jours.
    Lecture seule, dérivée de TempsSessionUtilisateur et User.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.is_staff:
            return Response({'detail': 'Réservé aux administrateurs.'},
                            status=status.HTTP_403_FORBIDDEN)
        from .stats_connexion import tableau_de_bord
        return Response(tableau_de_bord())


class StatsConnexionExportView(APIView):
    """Export CSV détaillé des sessions (admin). Une ligne par ouverture.

    Paramètre optionnel ?jours=N pour borner la période (ex. ?jours=30).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.is_staff:
            return Response({'detail': 'Réservé aux administrateurs.'},
                            status=status.HTTP_403_FORBIDDEN)
        from datetime import timedelta
        from apps.core.exports import reponse_csv
        from .stats_connexion import export_sessions_lignes
        depuis = None
        jours = request.query_params.get('jours')
        if jours:
            try:
                depuis = timezone.now() - timedelta(days=int(jours))
            except (ValueError, TypeError):
                depuis = None
        entetes, lignes = export_sessions_lignes(depuis)
        return reponse_csv('stats_connexion_sessions', entetes, lignes)


def _bornes_periode(request):
    """Lit ?debut=YYYY-MM-DD&fin=YYYY-MM-DD. Retourne (debut, fin, erreur)."""
    from datetime import datetime
    debut = fin = None
    try:
        if request.query_params.get('debut'):
            debut = datetime.strptime(request.query_params['debut'], '%Y-%m-%d').date()
        if request.query_params.get('fin'):
            fin = datetime.strptime(request.query_params['fin'], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None, None, True
    return debut, fin, False


class LivraisonStatsClientView(APIView):
    """GET livraison/client/<user_id>/ — stats livraison d'un client (admin).

    Consultations de l'onglet livraison + usages réels (demandeur/destinataire).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id=None):
        if not request.user.is_staff:
            return Response({'detail': 'Réservé aux administrateurs.'},
                            status=status.HTTP_403_FORBIDDEN)
        from .stats_livraison import stats_client
        return Response(stats_client(user_id))


class LivraisonStatsPartenaireView(APIView):
    """GET livraison/partenaire/<partenaire_id>/ — stats livraison d'un partenaire (admin).

    Nombre de courses issues d'une commande de ce partenaire.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, partenaire_id=None):
        if not request.user.is_staff:
            return Response({'detail': 'Réservé aux administrateurs.'},
                            status=status.HTTP_403_FORBIDDEN)
        from .stats_livraison import stats_partenaire
        return Response(stats_partenaire(partenaire_id))


class LivraisonTableauDeBordView(APIView):
    """GET livraison/tableau-de-bord/ — tableau de bord livraison (admin/Angular).

    Agrège TOUTES les courses : taux de conversion, CA (courses livrées),
    CA par jour/mois/heure, répartition par type de demandeur, top villes,
    top quartiers de départ, top catégories de partenaire.
    Filtre de période optionnel : ?debut=YYYY-MM-DD&fin=YYYY-MM-DD.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.is_staff:
            return Response({'detail': 'Réservé aux administrateurs.'},
                            status=status.HTTP_403_FORBIDDEN)
        debut, fin, erreur = _bornes_periode(request)
        if erreur:
            return Response({'detail': 'Format de date invalide (attendu YYYY-MM-DD).'},
                            status=status.HTTP_400_BAD_REQUEST)
        from .stats_livraison import tableau_de_bord
        return Response(tableau_de_bord(debut, fin))


class LivraisonTableauDeBordExportView(APIView):
    """Export CSV du tableau de bord livraison (admin).

    Mêmes données que LivraisonTableauDeBordView, à plat (section ; clé ; valeur).
    Filtre de période optionnel : ?debut=YYYY-MM-DD&fin=YYYY-MM-DD.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.is_staff:
            return Response({'detail': 'Réservé aux administrateurs.'},
                            status=status.HTTP_403_FORBIDDEN)
        debut, fin, erreur = _bornes_periode(request)
        if erreur:
            return Response({'detail': 'Format de date invalide (attendu YYYY-MM-DD).'},
                            status=status.HTTP_400_BAD_REQUEST)
        from apps.core.exports import reponse_csv
        from .stats_livraison import export_tableau_de_bord_lignes
        entetes, lignes = export_tableau_de_bord_lignes(debut, fin)
        return reponse_csv('livraison_tableau_de_bord', entetes, lignes)
