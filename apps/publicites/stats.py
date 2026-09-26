import csv

from django.core.exceptions import ValidationError as DjangoValidationError
from datetime import datetime, timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import ExtractHour, TruncDate
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import ADroitDe

from apps.users.models import Portee

from .models import (FormulePublicite, ImpressionPublicite, Publicite,
                     TypeAffichage, nb_clients_actifs)


def _stats_pub(pub, nb_actifs=None):
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
        'cible_atteinte': pub.cible_atteinte_pour(nb_actifs),
        'debut_diffusion': pub.debut_diffusion,
        'fin_diffusion': pub.fin_diffusion,
        'partenaire_id': pub.partenaire_id,
        'nom_partenaire': pub.partenaire.nom_commerce,
        'partenaire_telephone': pub.partenaire.user.telephone,
        'formule_id': pub.formule_id,
        'prix_formule': pub.formule.prix,
    }


STATUTS_AVEC_STATS = (Publicite.Statut.ACTIVE, Publicite.Statut.TERMINEE)


def stats_visibles_effectif(pub):
    """Vrai si le partenaire voit les stats de cette pub : campagne active
    ou terminée ET visibilité non masquée par l'admin. Brouillon, en
    attente et rejetée : jamais de stats (rien n'a été diffusé)."""
    return pub.statut in STATUTS_AVEC_STATS and pub.stats_visibles_partenaire


class StatsPartenaireView(APIView):
    """Stats des pubs du partenaire connecte (GET /publicites/mes-stats/).

    Stats detaillees (impressions, personnes touchees, clics, taux de clic...)
    quand stats_visibles est vrai : statut active/terminee ET
    stats_visibles_partenaire=True (par defaut ; l'admin peut masquer
    campagne par campagne). Sinon : reponse allegee avec stats_disponibles
    False. Dans les deux cas : stats_visibles (bool effectif) et
    statut_libelle. Il n'existe pas de serie d'evolution dans les donnees
    actuelles (compteurs cumules seulement) : rien n'est invente ici.
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
            visible = stats_visibles_effectif(pub)
            if visible:
                d = _stats_pub(pub)
            else:
                d = {
                    'id': str(pub.id), 'titre': pub.titre,
                    'formule': pub.formule.nom, 'statut': pub.statut,
                    'stats_disponibles': False,
                    'message': 'Statistiques bientot disponibles.',
                }
            d['stats_visibles'] = visible
            d['statut_libelle'] = pub.get_statut_display()
            donnees.append(d)
        return Response({'publicites': donnees})


class StatsVisiblesAdminView(APIView):
    """POST /publicites/admin/<uuid>/stats-visibles/ {"visible": bool} —
    l'admin masque ou rend visibles les stats d'une campagne au partenaire.
    Permission de validation des pubs (valider_publicite). Journalise
    (pub_stats_visibles). Les brouillons ne sont pas visibles de l'admin (404)."""
    permission_classes = [permissions.IsAuthenticated, ADroitDe('valider_publicite')]

    def post(self, request, pk=None):
        visible = request.data.get('visible')
        if not isinstance(visible, bool):
            return Response(
                {'erreur': True, 'message': 'Le champ "visible" doit être true ou false.'},
                status=status.HTTP_400_BAD_REQUEST)
        pub = (Publicite.objects.exclude(statut=Publicite.Statut.BROUILLON)
               .select_related('partenaire__user').filter(pk=pk).first())
        if pub is None:
            return Response({'erreur': True, 'message': 'Publicité introuvable.'},
                            status=status.HTTP_404_NOT_FOUND)
        if pub.stats_visibles_partenaire != visible:
            pub.stats_visibles_partenaire = visible
            pub.save(update_fields=['stats_visibles_partenaire', 'modifie_le'])
            try:
                from apps.administration.moderation import _journaliser
                _journaliser(
                    request.user, pub.partenaire.user, 'pub_stats_visibles',
                    f'Stats de la pub « {pub.titre} » (id {pub.pk}) '
                    f'{"rendues visibles" if visible else "masquées"} '
                    f'pour le partenaire.')
            except Exception:
                pass
        return Response({'id': str(pub.id),
                         'stats_visibles_partenaire': pub.stats_visibles_partenaire,
                         'stats_visibles': stats_visibles_effectif(pub)})


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
        # Nombre de clients actifs calculé UNE fois (évite un parcours des
        # profils par campagne) et seulement si une formule a une cible.
        nb_actifs = (nb_clients_actifs()
                     if any(p.formule.cible_pourcentage_actifs for p in pubs) else None)
        for p in pubs:
            # Mêmes champs et mêmes noms que StatsPartenaireView (stats
            # détaillées) : impressions, personnes touchées, clics, taux de
            # clic, impressions_par_type, cible_atteinte…
            d = _stats_pub(p, nb_actifs)
            d['statut_libelle'] = p.get_statut_display()
            d['stats_visibles'] = stats_visibles_effectif(p)
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
            d['stats_visibles_partenaire'] = p.stats_visibles_partenaire
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


def _parser_date(valeur):
    if not valeur:
        return None
    try:
        return datetime.strptime(valeur[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _taux(clics, impressions):
    return round(clics / impressions * 100, 1) if impressions else 0.0


class StatistiquesGlobalesAdminView(APIView):
    """GET /publicites/admin/statistiques/?du=&au=&formule=&partenaire=&portee=
    — statistiques globales des campagnes (défaut : 30 derniers jours).

    Définitions (cohérentes avec les compteurs par campagne) : une
    *impression* = une ligne ImpressionPublicite (les clics en sont aussi,
    comme pour Publicite.nb_impressions) ; un *clic* = ligne cliquee=True ;
    *personnes touchées* = utilisateurs connectés distincts sur la période.
    Brouillons toujours exclus ; ?portee= = portée EFFECTIVE (filtres
    partagés avec la liste admin, _publicites_admin_qs).
    Agrégé en base : 1 requête par dimension (jour, type, heure, campagne)
    et roll-up par campagne (bornée par le nombre de campagnes, pas
    d'impressions) pour formule/partenaire/portée. Sans N+1.
    """
    permission_classes = [permissions.IsAuthenticated, ADroitDe('voir_stats')]

    def get(self, request):
        p = request.query_params
        au = _parser_date(p.get('au')) or timezone.localdate()
        du = _parser_date(p.get('du')) or (au - timedelta(days=30))
        if du > au:
            return Response({'erreur': True, 'message': 'La date de début est postérieure à la date de fin.'},
                            status=status.HTTP_400_BAD_REQUEST)

        pubs, erreur = _publicites_admin_qs(request, avec_statut=False)
        if erreur:
            return Response({'erreur': True, 'message': erreur},
                            status=status.HTTP_400_BAD_REQUEST)
        pubs = pubs.order_by()
        imps = ImpressionPublicite.objects.filter(
            publicite__in=pubs.values('pk'),
            cree_le__date__gte=du, cree_le__date__lte=au).order_by()
        clic = Q(cliquee=True)

        # ── Global + par campagne (2 requêtes) ──
        globaux = imps.aggregate(
            impressions=Count('id'), clics=Count('id', filter=clic),
            personnes=Count('utilisateur', distinct=True))
        par_campagne = {r['publicite_id']: r for r in imps.values('publicite_id').annotate(
            impressions=Count('id'), clics=Count('id', filter=clic),
            personnes=Count('utilisateur', distinct=True))}
        infos = {pub.pk: pub for pub in Publicite.objects.filter(
            pk__in=par_campagne).select_related('formule', 'partenaire__plan')}

        # ── Revenus estimés : campagnes ACTIVÉES sur la période, hors faveurs ──
        activees = pubs.filter(debut_diffusion__date__gte=du, debut_diffusion__date__lte=au,
                               est_faveur=False)
        revenus_par_formule = {str(r['formule_id']): r['revenus'] or 0 for r in activees.order_by().values(
            'formule_id').annotate(revenus=Sum('formule__prix'))}
        revenus_total = sum(revenus_par_formule.values())

        # ── Cible atteinte : campagnes diffusées AYANT une cible ──
        nb_actifs = None
        nb_cible_atteinte = 0
        avec_cible = [pub for pub in infos.values() if pub.formule.cible_pourcentage_actifs]
        if avec_cible:
            nb_actifs = nb_clients_actifs()
            nb_cible_atteinte = sum(1 for pub in avec_cible if pub.cible_atteinte_pour(nb_actifs))

        # ── Roll-up par formule / partenaire / portée (à partir des campagnes) ──
        par_formule, par_partenaire, par_portee = {}, {}, {}
        for pk, r in par_campagne.items():
            pub = infos[pk]
            f = par_formule.setdefault(str(pub.formule_id), {
                'id': str(pub.formule_id), 'nom': pub.formule.nom,
                'nb_campagnes': 0, 'impressions': 0, 'clics': 0})
            f['nb_campagnes'] += 1; f['impressions'] += r['impressions']; f['clics'] += r['clics']
            pt = par_partenaire.setdefault(pub.partenaire_id, {
                'id': pub.partenaire_id, 'nom': pub.partenaire.nom_commerce,
                'nb_campagnes': 0, 'impressions': 0, 'clics': 0})
            pt['nb_campagnes'] += 1; pt['impressions'] += r['impressions']; pt['clics'] += r['clics']
            po = par_portee.setdefault(pub.portee_effective, {'nb_campagnes': 0, 'impressions': 0})
            po['nb_campagnes'] += 1; po['impressions'] += r['impressions']

        # formules avec revenus mais sans impression sur la période : incluses
        noms = {str(f.pk): f.nom for f in FormulePublicite.objects.filter(
            pk__in=[fid for fid in revenus_par_formule if fid not in par_formule])}
        for fid in revenus_par_formule:
            par_formule.setdefault(fid, {'id': fid, 'nom': noms.get(fid, ''),
                                         'nb_campagnes': 0, 'impressions': 0, 'clics': 0})
        for f in par_formule.values():
            f['taux_clic'] = _taux(f['clics'], f['impressions'])
            f['revenus'] = revenus_par_formule.get(f['id'], 0)

        # ── Séries (jour, type, heure) ──
        jours = {r['j']: r for r in imps.annotate(j=TruncDate('cree_le')).values('j').annotate(
            impressions=Count('id'), clics=Count('id', filter=clic))}
        par_jour, jour = [], du
        if (au - du).days <= 366:
            while jour <= au:
                r = jours.get(jour)
                par_jour.append({'date': str(jour), 'impressions': r['impressions'] if r else 0,
                                 'clics': r['clics'] if r else 0})
                jour += timedelta(days=1)
        else:  # période très longue : uniquement les jours avec activité
            par_jour = [{'date': str(j), 'impressions': r['impressions'], 'clics': r['clics']}
                        for j, r in sorted(jours.items())]

        types = {r['type_affichage']: r for r in imps.values('type_affichage').annotate(
            impressions=Count('id'), clics=Count('id', filter=clic))}
        par_type_affichage = [{
            'type': v, 'libelle': l,
            'impressions': types.get(v, {}).get('impressions', 0),
            'clics': types.get(v, {}).get('clics', 0),
        } for v, l in TypeAffichage.choices]

        heures = {r['h']: r['impressions'] for r in imps.annotate(h=ExtractHour('cree_le')).values(
            'h').annotate(impressions=Count('id'))}
        par_heure = [{'heure': h, 'impressions': heures.get(h, 0)} for h in range(24)]

        portees = [{'portee': v, 'libelle': l,
                    'nb_campagnes': par_portee.get(v, {}).get('nb_campagnes', 0),
                    'impressions': par_portee.get(v, {}).get('impressions', 0)}
                   for v, l in Portee.choices]

        # ── Top 10 campagnes par impressions ──
        top = sorted(par_campagne.items(), key=lambda kv: -kv[1]['impressions'])[:10]
        top_campagnes = [{
            'id': str(pk), 'titre': infos[pk].titre,
            'partenaire_nom': infos[pk].partenaire.nom_commerce,
            'formule_nom': infos[pk].formule.nom, 'statut': infos[pk].statut,
            'statut_libelle': infos[pk].get_statut_display(),
            'impressions': r['impressions'], 'personnes_touchees': r['personnes'],
            'clics': r['clics'], 'taux_clic': _taux(r['clics'], r['impressions']),
            'cible_pourcentage': infos[pk].formule.cible_pourcentage_actifs,
            'cible_atteinte': infos[pk].cible_atteinte_pour(nb_actifs),
        } for pk, r in top]

        return Response({
            'kpis': {
                'campagnes_actives': pubs.filter(statut=Publicite.Statut.ACTIVE).count(),
                'campagnes_diffusees': len(par_campagne),
                'annonceurs': len({infos[pk].partenaire_id for pk in par_campagne}),
                'impressions': globaux['impressions'],
                'personnes_touchees': globaux['personnes'],
                'clics': globaux['clics'],
                'taux_clic': _taux(globaux['clics'], globaux['impressions']),
                'revenus_estimes': revenus_total,
                'campagnes_cible_atteinte': nb_cible_atteinte,
            },
            'par_jour': par_jour,
            'par_type_affichage': par_type_affichage,
            'par_formule': sorted(par_formule.values(), key=lambda f: -f['impressions']),
            'par_partenaire': sorted(par_partenaire.values(), key=lambda x: -x['impressions'])[:10],
            'par_portee': portees,
            'par_heure': par_heure,
            'top_campagnes': top_campagnes,
        })


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
