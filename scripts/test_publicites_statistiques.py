"""Tests : statistiques globales des pubs (admin) + parite des stats par
campagne entre liste admin et endpoint partenaire.

Execution (tout est annule a la fin) :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_publicites_statistiques.py
"""
import json
from datetime import datetime, timedelta, timezone as dt_tz
from unittest.mock import patch

from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import PermissionsAdmin
from apps.publicites.models import FormulePublicite, ImpressionPublicite, Publicite
from apps.users.models import ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
NB = 0


class Rollback(Exception):
    pass


def ok(libelle, cond, detail=''):
    global NB
    print(('OK   ' if cond else 'FAIL '), libelle, '' if cond else detail)
    assert cond, f'{libelle} {detail}'
    NB += 1


def h(user):
    return {'HTTP_AUTHORIZATION': f'Bearer {AccessToken.for_user(user)}', 'HTTP_HOST': HOST}


def get(url, user):
    return Client().get(url, secure=True, **h(user))


URL = '/api/v1/publicites/admin/statistiques/'
avant = Publicite.objects.count()
avant_i = ImpressionPublicite.objects.count()
try:
    with transaction.atomic():
        superadmin = User.objects.filter(is_superuser=True).first()
        admin_stats = User.objects.create(
            telephone='+22506000001', username='t_glob_ok', role=User.Role.ADMIN,
            is_staff=True, is_superuser=False, est_verifie=True)
        admin_stats.set_password('0000'); admin_stats.save()
        PermissionsAdmin.objects.create(admin=admin_stats, voir_stats=True)
        admin_sans = User.objects.create(
            telephone='+22506000002', username='t_glob_sans', role=User.Role.ADMIN,
            is_staff=True, is_superuser=False, est_verifie=True)
        admin_sans.set_password('0000'); admin_sans.save()
        PermissionsAdmin.objects.create(admin=admin_sans)

        pa = ProfilPartenaire.objects.get(id=2)     # forfait departement
        pb = ProfilPartenaire.objects.get(id=1)
        decouverte = FormulePublicite.objects.get(nom='Découverte')
        eclair = FormulePublicite.objects.get(nom='Éclair')
        u1 = User.objects.filter(role='client').order_by('id')[0]
        u2 = User.objects.filter(role='client').order_by('id')[1]

        def t(jour, heure, minute=0):   # datetime aware (UTC) a heure locale ~ midi : evite les effets de fuseau
            return datetime(2025, 3, jour, heure, minute, tzinfo=dt_tz.utc)

        def pub(formule, statut, partenaire=pa, debut=None, faveur=False, titre='G'):
            return Publicite.objects.create(
                partenaire=partenaire, formule=formule, titre=titre, portee='departement',
                image_couverture='x.jpg', statut=statut, debut_diffusion=debut, est_faveur=faveur)

        def imp(p, quand, type_affichage='carrousel', user=None, clic=False):
            i = ImpressionPublicite.objects.create(
                publicite=p, utilisateur=user, type_affichage=type_affichage, cliquee=clic)
            ImpressionPublicite.objects.filter(pk=i.pk).update(cree_le=quand)   # auto_now_add

        A = pub(decouverte, 'active', debut=t(3, 10), titre='GA')
        B = pub(eclair, 'terminee', debut=t(4, 9), faveur=True, titre='GB')
        C = pub(decouverte, 'brouillon', titre='GC-brouillon')
        D_hors = pub(decouverte, 'active', debut=t(3, 10), titre='GD')
        E_autre = pub(decouverte, 'active', partenaire=pb, debut=t(4, 11), titre='GE-autre-partenaire')
        imp(A, t(3, 10, 15), 'carrousel', u1)
        imp(A, t(3, 10, 20), 'bandeau_bas', u1, clic=True)
        imp(A, t(4, 14, 0), 'carrousel', u2)
        imp(A, t(5, 12, 0), 'page_publicites', None)
        imp(B, t(4, 9, 0), 'interstitiel', u1)
        imp(B, t(4, 9, 5), 'carrousel', u2, clic=True)
        imp(C, t(3, 11, 0), 'carrousel', u1)              # brouillon : exclu
        imp(D_hors, t(10, 12, 0), 'carrousel', u1)        # hors fenetre
        imp(E_autre, t(4, 15, 0), 'carrousel', u1)        # autre partenaire
        Q = f'?du=2025-03-03&au=2025-03-05&partenaire={pa.id}'

        print('\n=== 1. ACCES ===')
        ok('sans voir_stats -> 403', get(URL + Q, admin_sans).status_code == 403)
        ok('partenaire -> 403', get(URL + Q, pa.user).status_code == 403)
        ok('admin voir_stats -> 200', get(URL + Q, admin_stats).status_code == 200)
        ok('super-admin -> 200', get(URL + Q, superadmin).status_code == 200)
        ok('du > au -> 400', get(URL + '?du=2025-03-09&au=2025-03-01', superadmin).status_code == 400)
        ok('portee invalide -> 400', get(URL + '?portee=monde', superadmin).status_code == 400)
        ok('formule invalide -> 400', get(URL + '?formule=abc', superadmin).status_code == 400)

        print('\n=== 2. COHERENCE kpis / agregats (jeu de donnees controle) ===')
        c = Client()
        get(URL + Q, superadmin)
        with CaptureQueriesContext(connection) as ctx:
            r = get(URL + Q, superadmin)
        d = r.json()
        k = d['kpis']
        ok(f'requetes SQL bornees ({len(ctx)}) : quelques requetes, sans N+1', len(ctx) <= 16, len(ctx))
        ok('impressions = 6 (brouillon, hors fenetre et autre partenaire exclus)', k['impressions'] == 6, k)
        ok('clics = 2', k['clics'] == 2, k)
        ok('taux_clic = 33.3 (1 decimale)', k['taux_clic'] == 33.3, k['taux_clic'])
        ok('personnes_touchees = 2 (utilisateurs connectes distincts, anonyme exclu)', k['personnes_touchees'] == 2, k)
        ok('campagnes_diffusees = 2 et annonceurs = 1', (k['campagnes_diffusees'], k['annonceurs']) == (2, 1), k)
        ok('campagnes_actives = campagnes au statut active dans les filtres (A et D, pas C brouillon)',
           k['campagnes_actives'] == 2, k)
        ok('revenus_estimes = prix Decouverte de A et D (activees dans la periode, base sur la date '
           'd\'activation et non sur les impressions) ; B faveur et C brouillon exclues',
           k['revenus_estimes'] == decouverte.prix * 2, (k['revenus_estimes'], decouverte.prix))
        ok('somme par_jour.impressions = kpis.impressions',
           sum(x['impressions'] for x in d['par_jour']) == k['impressions'])
        ok('somme par_jour.clics = kpis.clics', sum(x['clics'] for x in d['par_jour']) == k['clics'])
        ok('par_jour : 3 jours consecutifs, jours sans activite a 0',
           [x['date'] for x in d['par_jour']] == ['2025-03-03', '2025-03-04', '2025-03-05'], d['par_jour'])
        ok('par_jour : 2 / 3 / 1 impressions', [x['impressions'] for x in d['par_jour']] == [2, 3, 1], d['par_jour'])
        ok('somme par_type_affichage = kpis.impressions et 4 types presents',
           sum(x['impressions'] for x in d['par_type_affichage']) == 6 and len(d['par_type_affichage']) == 4)
        types = {x['type']: x for x in d['par_type_affichage']}
        ok('par_type : carrousel 3 imp/1 clic, bandeau 1/1, interstitiel 1/0, page 1/0',
           (types['carrousel']['impressions'], types['carrousel']['clics'], types['bandeau_bas']['clics'],
            types['interstitiel']['impressions'], types['page_publicites']['impressions']) == (3, 1, 1, 1, 1), types)
        ok('par_heure : 24 entrees, somme = impressions',
           len(d['par_heure']) == 24 and sum(x['impressions'] for x in d['par_heure']) == 6)
        h_attendues = {}
        for q in (t(3, 10, 15), t(3, 10, 20), t(4, 14), t(5, 12), t(4, 9), t(4, 9, 5)):
            hl = timezone.localtime(q).hour
            h_attendues[hl] = h_attendues.get(hl, 0) + 1
        ok('par_heure : repartition conforme (heure locale)',
           {x['heure']: x['impressions'] for x in d['par_heure'] if x['impressions']} == h_attendues, d['par_heure'])
        pf = {x['nom']: x for x in d['par_formule']}
        ok('par_formule : Decouverte 1 campagne diffusee/4 imp/1 clic/revenus=2 activations ; Eclair 1/2/1/0',
           (pf['Découverte']['nb_campagnes'], pf['Découverte']['impressions'], pf['Découverte']['clics'],
            pf['Découverte']['revenus'], pf['Éclair']['impressions'], pf['Éclair']['revenus'])
           == (1, 4, 1, decouverte.prix * 2, 2, 0), pf)
        ok('par_formule : taux_clic present et somme impressions = total',
           all('taux_clic' in x for x in d['par_formule']) and sum(x['impressions'] for x in d['par_formule']) == 6)
        ok('par_partenaire : 1 ligne (le partenaire filtre), 2 campagnes, 6 imp, 2 clics',
           len(d['par_partenaire']) == 1 and (d['par_partenaire'][0]['id'], d['par_partenaire'][0]['nb_campagnes'],
           d['par_partenaire'][0]['impressions'], d['par_partenaire'][0]['clics']) == (pa.id, 2, 6, 2), d['par_partenaire'])
        po = {x['portee']: x for x in d['par_portee']}
        ok('par_portee : 3 portees, tout en departement (forfait departement) : 2 campagnes / 6 imp',
           len(po) == 3 and (po['departement']['nb_campagnes'], po['departement']['impressions'],
           po['region']['impressions'], po['district']['impressions']) == (2, 6, 0, 0), po)
        top = d['top_campagnes']
        ok('top_campagnes : GA (4 imp) puis GB (2 imp)', [x['titre'] for x in top] == ['GA', 'GB'], top)
        ok('top_campagnes : tous les champs du contrat',
           {'id', 'titre', 'partenaire_nom', 'formule_nom', 'statut', 'statut_libelle', 'impressions',
            'personnes_touchees', 'clics', 'taux_clic', 'cible_pourcentage', 'cible_atteinte'} <= set(top[0]))
        ok('top_campagnes GA : 4 imp, 2 personnes distinctes (u1, u2), 1 clic, 25.0 %, statut_libelle Active',
           (top[0]['impressions'], top[0]['personnes_touchees'], top[0]['clics'], top[0]['taux_clic'],
            top[0]['statut_libelle']) == (4, 2, 1, 25.0, 'Active'), top[0])
        ok('aucun brouillon nulle part (titre GC absent)', 'GC-brouillon' not in json.dumps(d))

        print('\n=== 3. FILTRES ===')
        r = get(URL + '?du=2025-03-03&au=2025-03-05', superadmin).json()
        ok('sans filtre partenaire : inclut aussi l\'autre partenaire (7 impressions)', r['kpis']['impressions'] == 7
           and r['kpis']['annonceurs'] == 2, r['kpis'])
        r = get(URL + f'{Q}&formule={eclair.id}', superadmin).json()
        ok('?formule=Eclair : seulement GB (2 imp)', r['kpis']['impressions'] == 2 and r['kpis']['campagnes_diffusees'] == 1, r['kpis'])
        r = get(URL + Q + '&portee=departement', superadmin).json()
        ok('?portee=departement (effective) : 6 imp', r['kpis']['impressions'] == 6, r['kpis'])
        r = get(URL + Q + '&portee=region', superadmin).json()
        ok('?portee=region : 0 imp (forfait departement, stockee departement)', r['kpis']['impressions'] == 0, r['kpis'])
        r = get(URL + '?du=2025-03-03&au=2025-03-03&partenaire=%d' % pa.id, superadmin).json()
        ok('periode 1 jour : 2 imp', r['kpis']['impressions'] == 2 and len(r['par_jour']) == 1, r['kpis'])
        r = get(URL + '?du=2024-01-01&au=2024-01-03&partenaire=%d' % pa.id, superadmin).json()
        ok('periode vide : zeros, series completes (jamais d\'erreur)', r['kpis']['impressions'] == 0
           and r['kpis']['taux_clic'] == 0.0 and len(r['par_heure']) == 24 and r['top_campagnes'] == []
           and r['kpis']['revenus_estimes'] == 0, r['kpis'])
        r = get(URL, superadmin).json()
        ok('defaut = 30 derniers jours (31 points)', len(r['par_jour']) == 31, len(r['par_jour']))

        print('\n=== 4. CIBLE ATTEINTE (nb de clients actifs simule) ===')
        f50 = FormulePublicite.objects.create(nom='Cible50 QA', prix=1000, quota_partenaires=5,
                                              types_affichage=['carrousel'], cible_pourcentage_actifs=50)
        f100 = FormulePublicite.objects.create(nom='Cible100 QA', prix=1000, quota_partenaires=5,
                                               types_affichage=['carrousel'], cible_pourcentage_actifs=100)
        P50 = pub(f50, 'active', debut=t(3, 10), titre='P50'); P50.nb_personnes_touchees = 2; P50.save()
        P100 = pub(f100, 'active', debut=t(3, 10), titre='P100'); P100.nb_personnes_touchees = 2; P100.save()
        imp(P50, t(3, 12), 'carrousel', u1); imp(P100, t(3, 12), 'carrousel', u1)
        with patch('apps.publicites.stats.nb_clients_actifs', return_value=4), \
             patch('apps.publicites.models.nb_clients_actifs', return_value=4):
            r50 = get(URL + Q + f'&formule={f50.id}', superadmin).json()
            r100 = get(URL + Q + f'&formule={f100.id}', superadmin).json()
        ok('cible 50 % (2 touchees / 4 actifs = 50 %) : campagnes_cible_atteinte = 1, top cible_atteinte True',
           r50['kpis']['campagnes_cible_atteinte'] == 1 and r50['top_campagnes'][0]['cible_atteinte'] is True
           and r50['top_campagnes'][0]['cible_pourcentage'] == 50, r50['kpis'])
        ok('cible 100 % (50 %) : campagnes_cible_atteinte = 0, cible_atteinte False',
           r100['kpis']['campagnes_cible_atteinte'] == 0 and r100['top_campagnes'][0]['cible_atteinte'] is False, r100['kpis'])
        ok('sans cible : ne compte pas dans campagnes_cible_atteinte (GA/GB, 0)',
           get(URL + Q + f'&formule={eclair.id}', superadmin).json()['kpis']['campagnes_cible_atteinte'] == 0)

        print('\n=== 5. STATS PAR CAMPAGNE : liste admin = endpoint partenaire ===')
        A.nb_impressions, A.nb_clics, A.nb_personnes_touchees = 4, 1, 1; A.save()
        rp = get('/api/v1/publicites/mes-stats/', pa.user).json()['publicites']
        partenaire_A = next(x for x in rp if x['id'] == str(A.id))
        ra = get('/api/v1/publicites/admin/stats/', superadmin).json()['publicites']
        admin_A = next(x for x in ra if x['id'] == str(A.id))
        ok('la campagne est visible avec stats cote partenaire', partenaire_A['stats_visibles'] is True)
        ok('TOUS les champs de stats partenaire sont dans la liste admin (memes noms)',
           set(partenaire_A) <= set(admin_A), set(partenaire_A) - set(admin_A))
        ok('memes valeurs (impressions, personnes touchees, clics, taux de clic, repartition, cible)',
           all(partenaire_A[cle] == admin_A[cle] for cle in (
               'nb_impressions', 'nb_personnes_touchees', 'nb_clics', 'taux_clic',
               'impressions_par_type', 'cible_atteinte', 'cible_pourcentage', 'statut')), (partenaire_A, admin_A))
        ok('champs admin existants conserves (image_couverture, video, portee, stats_visibles_partenaire...)',
           {'image_couverture', 'video', 'portee', 'portee_effective', 'stats_visibles_partenaire'} <= set(admin_A))
        ok('liste admin : brouillon toujours exclu', str(C.id) not in {x['id'] for x in ra})

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback('annulation volontaire')
except Rollback as e:
    print('Rollback effectue :', e)

assert Publicite.objects.count() == avant and ImpressionPublicite.objects.count() == avant_i, 'donnees persistees !'
print(f'Aucune donnee persistee (publicites: {avant}, impressions: {avant_i}).')
