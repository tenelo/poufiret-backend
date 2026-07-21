from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
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
