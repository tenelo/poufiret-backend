import csv

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import ADroitDe

from .models import FormulePublicite, ImpressionPublicite, Publicite


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


def _publicites_admin_qs(request, avec_statut=True):
    """Publicites vues par l'admin : JAMAIS les brouillons (le partenaire
    seul voit les siens). Filtres optionnels : ?formule=<uuid>,
    ?partenaire=<id>, ?search= (titre / nom du partenaire), ?portee=
    (portee EFFECTIVE = MAX(forfait, achetee)) et, si avec_statut, ?statut=
    (un ou plusieurs, repete ou separe par des virgules).

    Retourne (queryset, erreur) ; erreur est un message francais (400) ou None.
    """
    qs = (Publicite.objects.exclude(statut=Publicite.Statut.BROUILLON)
          .select_related('formule', 'partenaire__user', 'partenaire__plan'))
    p = request.query_params

    formule = p.get('formule')
    if formule:
        try:
            qs = qs.filter(formule_id=formule)
        except (ValueError, DjangoValidationError):
            return qs.none(), 'Formule invalide.'
    partenaire = p.get('partenaire')
    if partenaire:
        try:
            qs = qs.filter(partenaire_id=int(partenaire))
        except (ValueError, TypeError):
            return qs.none(), 'Partenaire invalide.'
    search = (p.get('search') or '').strip()
    if search:
        qs = qs.filter(Q(titre__icontains=search)
                       | Q(partenaire__nom_commerce__icontains=search))
    portee = p.get('portee')
    if portee:
        if portee not in ('departement', 'region', 'district'):
            return qs.none(), 'Portée invalide (departement, region ou district).'
        district = Q(portee='district') | Q(partenaire__plan__portee='district')
        if portee == 'district':
            qs = qs.filter(district)
        elif portee == 'region':
            qs = qs.filter(Q(portee='region') | Q(partenaire__plan__portee='region')
                           ).exclude(district)
        else:
            qs = qs.exclude(Q(portee__in=['region', 'district'])
                            | Q(partenaire__plan__portee__in=['region', 'district']))
    if avec_statut:
        valeurs = []
        for brut in p.getlist('statut'):
            valeurs += [v.strip() for v in brut.split(',') if v.strip()]
        if valeurs:
            connus = {v for v, _ in Publicite.Statut.choices}
            inconnus = [v for v in valeurs if v not in connus]
            if inconnus:
                return qs.none(), f'Statut inconnu : {", ".join(inconnus)}.'
            qs = qs.filter(statut__in=valeurs)
    return qs, None


def _compteurs_statut(request):
    """Nombre de pubs par statut (hors brouillon), pour les onglets.

    Respecte les filtres formule/partenaire/search/portee mais PAS le filtre
    statut, afin que chaque onglet affiche son propre total. 1 requete.
    """
    qs, _ = _publicites_admin_qs(request, avec_statut=False)
    compteurs = {v: 0 for v, _ in Publicite.Statut.choices
                 if v != Publicite.Statut.BROUILLON}
    for statut, n in qs.order_by().values_list('statut').annotate(n=Count('id')):
        compteurs[statut] = n
    compteurs['total'] = sum(compteurs.values())
    return compteurs


class StatsAdminView(APIView):
    """Vue d'ensemble des publicites (admin / Angular). Brouillons exclus.

    GET ?statut=active,terminee (ou repete) &formule=<uuid> &partenaire=<id>
        &search=<titre|partenaire> &portee=departement|region|district
    Reponse : {totaux, compteurs_statut, publicites}. `compteurs_statut`
    ignore le filtre statut (onglets).
    """
    permission_classes = [permissions.IsAuthenticated, ADroitDe('voir_stats')]

    def get(self, request):
        pubs, erreur = _publicites_admin_qs(request)
        if erreur:
            return Response({'erreur': True, 'message': erreur},
                            status=status.HTTP_400_BAD_REQUEST)
        donnees = []
        for p in pubs:
            d = _stats_pub(p)
            # Média (lecture seule, URL absolue) : _stats_pub reste inchangée
            # (partagée avec StatsPartenaireView) — ajout scopé à cette seule
            # vue admin, même logique de construction d'URL que les
            # ImageField/FileField sérialisés avec context={'request': ...}
            # côté partenaire (request.build_absolute_uri).
            d['image_couverture'] = (
                request.build_absolute_uri(p.image_couverture.url)
                if p.image_couverture else None
            )
            d['video'] = (
                request.build_absolute_uri(p.video.url) if p.video else None
            )
            d['portee'] = p.portee
            d['portee_effective'] = p.portee_effective
            donnees.append(d)
        totaux = {
            'nb_publicites': len(donnees),
            'nb_actives': sum(1 for p in pubs if p.statut == Publicite.Statut.ACTIVE),
            'total_impressions': sum(d['nb_impressions'] for d in donnees),
            'total_personnes_touchees': sum(d['nb_personnes_touchees'] for d in donnees),
            'total_clics': sum(d['nb_clics'] for d in donnees),
        }
        return Response({'totaux': totaux,
                         'compteurs_statut': _compteurs_statut(request),
                         'publicites': donnees})


class FormulesQuotasAdminView(APIView):
    """Suivi admin des quotas par formule (toutes les formules, actives ou non).

    quota_partenaires = nombre maximal de pubs au statut active EN MEME TEMPS
    sur la formule. Une seule requete agregee (annotate), sans N+1.
    nb_en_attente = soumises pas encore activees (en attente de paiement +
    en attente de validation) ; brouillons jamais comptes.
    """
    permission_classes = [permissions.IsAuthenticated, ADroitDe('voir_stats')]

    def get(self, request):
        Statut = Publicite.Statut
        formules = FormulePublicite.objects.annotate(
            nb_actives=Count('publicites', filter=Q(publicites__statut=Statut.ACTIVE)),
            nb_attente_paiement=Count(
                'publicites', filter=Q(publicites__statut=Statut.EN_ATTENTE_PAIEMENT)),
            nb_attente_validation=Count(
                'publicites', filter=Q(publicites__statut=Statut.EN_ATTENTE_VALIDATION)),
        ).order_by('prix')
        return Response({'formules': [{
            'id': str(f.id),
            'nom': f.nom,
            'prix': f.prix,
            'est_active': f.est_active,
            'quota_partenaires': f.quota_partenaires,
            'nb_actives': f.nb_actives,
            'places_restantes': max(0, f.quota_partenaires - f.nb_actives),
            'nb_en_attente': f.nb_attente_paiement + f.nb_attente_validation,
            'nb_en_attente_paiement': f.nb_attente_paiement,
            'nb_en_attente_validation': f.nb_attente_validation,
        } for f in formules]})


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
            for p in (Publicite.objects.exclude(statut=Publicite.Statut.BROUILLON)
                      .select_related('formule', 'partenaire')):
                writer.writerow([p.id, p.titre, p.partenaire.nom_commerce, p.formule.nom,
                                 p.formule.prix, p.statut, p.nb_personnes_touchees,
                                 p.nb_impressions, p.nb_clics,
                                 p.debut_diffusion or '', p.fin_diffusion or ''])

        elif type_export == 'impressions':
            writer.writerow(['id', 'publicite', 'utilisateur', 'type_affichage',
                             'minute_session', 'cliquee', 'date'])
            qs = (ImpressionPublicite.objects
                  .exclude(publicite__statut=Publicite.Statut.BROUILLON)
                  .select_related('publicite', 'utilisateur'))
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
