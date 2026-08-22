import csv

from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import ADroitDe

from .models import ImpressionPublicite, Publicite


def _stats_pub(pub):
    impressions = ImpressionPublicite.objects.filter(publicite=pub)
    par_type = dict(
        impressions.values_list('type_affichage')
        .annotate(n=Count('id'))
    )
    return {
        'id': str(pub.id),
        'titre': pub.titre,
        'formule': pub.formule.nom,
        'statut': pub.statut,
        'nb_personnes_touchees': pub.nb_personnes_touchees,
        'nb_impressions': pub.nb_impressions,
        'nb_clics': pub.nb_clics,
        'taux_clic': round(pub.nb_clics / pub.nb_impressions * 100, 2) if pub.nb_impressions else 0,
        'impressions_par_type': par_type,
        'cible_pourcentage': pub.formule.cible_pourcentage_actifs,
        'cible_atteinte': pub.cible_atteinte,
        'debut_diffusion': pub.debut_diffusion,
        'fin_diffusion': pub.fin_diffusion,
        'partenaire_id': pub.partenaire_id,
        'nom_partenaire': pub.partenaire.nom_commerce,
        'partenaire_telephone': pub.partenaire.user.telephone,
        'formule_id': pub.formule_id,
        'prix_formule': pub.formule.prix,
    }


class StatsPartenaireView(APIView):
    """Stats des pubs du partenaire connecte.

    Chaque pub n'est detaillee que si stats_visibles_partenaire est True.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        profil = getattr(request.user, 'profil_partenaire', None)
        if profil is None:
            return Response({'erreur': True, 'message': 'Reserve aux partenaires.'},
                            status=status.HTTP_403_FORBIDDEN)
        pubs = Publicite.objects.filter(partenaire=profil).exclude(
            masquee_par_partenaire=True).select_related('formule', 'partenaire__user')
        donnees = []
        for pub in pubs:
            if pub.stats_visibles_partenaire:
                donnees.append(_stats_pub(pub))
            else:
                donnees.append({
                    'id': str(pub.id), 'titre': pub.titre,
                    'formule': pub.formule.nom, 'statut': pub.statut,
                    'stats_disponibles': False,
                    'message': 'Statistiques bientot disponibles.',
                })
        return Response({'publicites': donnees})


class StatsAdminView(APIView):
    """Vue d'ensemble des publicites (admin / Angular)."""
    permission_classes = [permissions.IsAuthenticated, ADroitDe('voir_stats')]

    def get(self, request):
        pubs = Publicite.objects.select_related('formule', 'partenaire', 'partenaire__user')
        donnees = [_stats_pub(p) for p in pubs]
        totaux = {
            'nb_publicites': len(donnees),
            'nb_actives': sum(1 for p in pubs if p.statut == Publicite.Statut.ACTIVE),
            'total_impressions': sum(d['nb_impressions'] for d in donnees),
            'total_personnes_touchees': sum(d['nb_personnes_touchees'] for d in donnees),
            'total_clics': sum(d['nb_clics'] for d in donnees),
        }
        return Response({'totaux': totaux, 'publicites': donnees})


class ExportCSVView(APIView):
    """Exports CSV pour analyse (staff uniquement).

    GET /export/?type=publicites|impressions|profils|sessions
    """
    permission_classes = [permissions.IsAuthenticated, ADroitDe('voir_stats', 'exporter_csv')]

    def get(self, request):
        type_export = request.query_params.get('type', 'publicites')
        horodatage = timezone.localtime().strftime('%Y%m%d_%H%M')
        reponse = HttpResponse(content_type='text/csv; charset=utf-8')
        reponse['Content-Disposition'] = (
            f'attachment; filename="poufiret_{type_export}_{horodatage}.csv"'
        )
        reponse.write('\ufeff')  # BOM pour Excel
        writer = csv.writer(reponse, delimiter=';')

        if type_export == 'publicites':
            writer.writerow(['id', 'titre', 'partenaire', 'formule', 'prix', 'statut',
                             'personnes_touchees', 'impressions', 'clics',
                             'debut_diffusion', 'fin_diffusion'])
            for p in Publicite.objects.select_related('formule', 'partenaire'):
                writer.writerow([p.id, p.titre, p.partenaire.nom_commerce, p.formule.nom,
                                 p.formule.prix, p.statut, p.nb_personnes_touchees,
                                 p.nb_impressions, p.nb_clics,
                                 p.debut_diffusion or '', p.fin_diffusion or ''])

        elif type_export == 'impressions':
            writer.writerow(['id', 'publicite', 'utilisateur', 'type_affichage',
                             'minute_session', 'cliquee', 'date'])
            qs = ImpressionPublicite.objects.select_related('publicite', 'utilisateur')
            for i in qs.iterator():
                writer.writerow([i.id, i.publicite.titre,
                                 i.utilisateur.telephone if i.utilisateur else 'anonyme',
                                 i.type_affichage, i.minute_session or '',
                                 'oui' if i.cliquee else 'non', i.cree_le])

        elif type_export == 'profils':
            from apps.analytics.models import ProfilNavigation
            writer.writerow(['utilisateur', 'mois', 'articles_vus', 'temps_cumule_s',
                             'client_actif', 'derniere_activite', 'categories'])
            for p in ProfilNavigation.objects.select_related('utilisateur'):
                writer.writerow([p.utilisateur.telephone, p.mois_reference,
                                 p.nb_articles_vus_mois, p.temps_cumule_secondes_mois,
                                 'oui' if p.est_client_actif else 'non',
                                 p.derniere_activite or '', p.categories_consultees])

        elif type_export == 'sessions':
            from apps.analytics.models import TempsSessionUtilisateur
            writer.writerow(['id', 'utilisateur', 'debut', 'dernier_ping',
                             'duree_secondes', 'source'])
            qs = TempsSessionUtilisateur.objects.select_related('utilisateur')
            for s in qs.iterator():
                writer.writerow([s.id, s.utilisateur.telephone, s.debut,
                                 s.dernier_ping, s.duree_secondes, s.source])
        else:
            return Response({'erreur': True, 'message': 'Type d\'export inconnu.'},
                            status=status.HTTP_400_BAD_REQUEST)

        return reponse
