"""Tests : liste admin paginée des pubs (admin/liste/), compteurs
(admin/compteurs/) et vue par partenaire (admin/partenaires/).

- pagination : 25 par défaut, page_size jusqu'à 100 (plafonné), count/next/previous ;
- chaque filtre (statut simple / multiple, partenaire, search, période,
  formule, origine, portee) comparé au résultat attendu calculé en Python ;
- chaque tri, ascendant et descendant (dates vides en dernier, départage
  stable par id, pages sans doublon ni trou) ; ordre inconnu -> 400 ;
- compteurs_statut (filtre statut ignoré), dans la liste et seuls ;
- vue par partenaire (comptes par statut, totaux, dernière pub, recherche,
  tri, filtres) ;
- droits : sans voir_stats -> 403, partenaire -> 403, anonyme -> 401 ;
- nombre de requêtes identique pour 5 et 25 pubs (et admin/stats/ pour 26 et 105) ;
- admin/stats/ : champs historiques, impressions_par_type identiques au
  calcul pub par pub, lignes identiques à admin/liste/.

Données propres (isolées par formule), transaction annulée (rien ne
persiste), limitation de débit désactivée, total OK / KO.
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_publicites_liste_admin.py
"""
import uuid
from datetime import datetime, timedelta

from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import PermissionsAdmin
from apps.publicites.models import FormulePublicite, ImpressionPublicite, Publicite
from apps.publicites.stats import _stats_pub
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
# Limitation de débit DRF désactivée pour ce script : sinon tous les scripts partagent
# le compteur anonyme (60/min, client de test = 127.0.0.1) et la suite complète reçoit des 429.
from unittest import mock as _mock_debit
from rest_framework.views import APIView as _APIViewDebit
_mock_debit.patch.object(_APIViewDebit, 'get_throttles', return_value=[]).start()

LISTE = '/api/v1/publicites/admin/liste/'
COMPTEURS = '/api/v1/publicites/admin/compteurs/'
PARTENAIRES = '/api/v1/publicites/admin/partenaires/'
STATS = '/api/v1/publicites/admin/stats/'
STATUTS = ['en_attente_paiement', 'en_attente_validation', 'active', 'terminee', 'rejetee']
CHAMPS_STATS = {
    'id', 'titre', 'formule', 'statut', 'nb_personnes_touchees', 'nb_impressions', 'nb_clics',
    'taux_clic', 'impressions_par_type', 'cible_pourcentage', 'cible_atteinte', 'debut_diffusion',
    'fin_diffusion', 'partenaire_id', 'nom_partenaire', 'partenaire_telephone', 'formule_id',
    'prix_formule', 'reconduite_le', 'reconduction_id', 'reconduction_statut', 'peut_etre_reconduite',
    'reconduite_depuis_id', 'statut_libelle', 'stats_visibles', 'image_couverture', 'video', 'portee',
    'stats_visibles_partenaire', 'portee_effective'}


class Rollback(Exception):
    pass


NB_OK, KO = 0, []


def ok(libelle, cond, detail=''):
    global NB_OK
    if cond:
        NB_OK += 1
        print('OK  ', libelle)
    else:
        KO.append(libelle)
        print('FAIL', libelle, str(detail)[:400])


def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel


def utilisateur(role='client', **kw):
    return User.objects.create(telephone=telephone_libre(), username=f't_liste_{uuid.uuid4().hex[:8]}',
                               role=role, est_verifie=True, **kw)


def entetes(user=None):
    e = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        e['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    return e


try:
    with transaction.atomic():
        c = Client()
        uid = uuid.uuid4().hex[:6]
        maintenant = timezone.now()
        plan = PlanAbonnement.objects.get(libelle='Basique')
        superadmin = utilisateur('admin', is_staff=True, is_superuser=True)
        admin_stats = utilisateur('admin', is_staff=True)
        PermissionsAdmin.objects.create(admin=admin_stats, voir_stats=True)
        admin_sans = utilisateur('admin', is_staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans, valider_publicite=True)

        def partenaire(nom):
            u = utilisateur('partenaire')
            return u, ProfilPartenaire.objects.create(
                user=u, plan=plan, nom_commerce=f'{nom} {uid}', type_partenaire='commercant',
                statut='actif', est_visible=True)

        p1_user, P1 = partenaire('Alpha')
        _, P2 = partenaire('Beta')
        _, P3 = partenaire('Gamma')
        F = FormulePublicite.objects.create(nom=f'Formule Liste {uid}', prix=5000, duree_jours=7,
                                            quota_partenaires=10000, types_affichage=['carrousel'],
                                            cible_pourcentage_actifs=0)
        F2 = FormulePublicite.objects.create(nom=f'Formule Lest {uid}', prix=3000, duree_jours=7,
                                             quota_partenaires=10000, types_affichage=['carrousel'],
                                             cible_pourcentage_actifs=0)

        # ── 26 pubs sur F : statuts, partenaires, dates, compteurs variés ──
        pubs = []
        for i in range(26):
            st = STATUTS[i % 5]
            diffusee = st in ('active', 'terminee')
            debut = maintenant - timedelta(days=3 * i) if diffusee else None
            p = Publicite.objects.create(
                partenaire=P1 if i % 2 else P2, formule=F, titre=f'Pub {i:02d} {uid}',
                portee='district' if i == 7 else 'departement',
                image_couverture='publicites/couvertures/liste.jpg', statut=st,
                debut_diffusion=debut, fin_diffusion=debut + timedelta(days=7) if debut else None,
                nb_impressions=(i % 7) * 10, nb_clics=i // 2, nb_personnes_touchees=i,
                est_faveur=(i % 3 == 0), cree_par_admin=superadmin if i % 5 == 0 else None)
            pubs.append(p)
        for i, p in enumerate(pubs):  # cree_le distincts et connus
            Publicite.objects.filter(pk=p.pk).update(cree_le=maintenant - timedelta(hours=i))
        Publicite.objects.create(partenaire=P1, formule=F, titre=f'Brouillon {uid}',
                                 image_couverture='publicites/couvertures/liste.jpg', statut='brouillon')
        # Reconduction (champs annotés) et impressions par type
        Publicite.objects.create(partenaire=P2, formule=F2, titre=f'Copie {uid}', reconduite_depuis=pubs[3],
                                 image_couverture='publicites/couvertures/liste.jpg', statut='active')
        for p, types in ((pubs[1], ['carrousel', 'carrousel', 'interstitiel']), (pubs[2], ['bandeau_bas'])):
            for t in types:
                ImpressionPublicite.objects.create(publicite=p, type_affichage=t)
        pubs = list(Publicite.objects.filter(formule=F).exclude(statut='brouillon')
                    .select_related('partenaire__plan', 'formule'))
        par_id = {str(p.id): p for p in pubs}

        def tous_ids(params, user=superadmin):
            """Ids de toutes les pages (page_size=100) restreintes à la formule F."""
            r = c.get(LISTE, {'formule': str(F.id), 'page_size': 100, **params}, **entetes(user))
            assert r.status_code == 200, r.content[:300]
            return [x['id'] for x in r.json()['results']]

        def attendu(pred):
            return {str(p.id) for p in pubs if pred(p)}

        print('=== 1. PAGINATION ===')
        r = c.get(LISTE, {'formule': str(F.id)}, **entetes(superadmin))
        d = r.json()
        ok('200, format DRF + compteurs_statut', r.status_code == 200
           and {'count', 'next', 'previous', 'results', 'compteurs_statut'} <= set(d), list(d))
        ok('25 par defaut, count 26, next renseigne, previous null', (
            len(d['results']), d['count'], bool(d['next']), d['previous']) == (25, 26, True, None),
           (len(d['results']), d['count'], d['next'], d['previous']))
        d2 = c.get(LISTE, {'formule': str(F.id), 'page': 2}, **entetes(superadmin)).json()
        ok('page 2 : 1 pub, next null, previous renseigne',
           (len(d2['results']), d2['next'], bool(d2['previous'])) == (1, None, True), d2)
        ok('page 1 + page 2 = toutes les pubs, sans doublon', len(
            {x['id'] for x in d['results'] + d2['results']}) == 26 == len(par_id))
        ok('page_size=7 respecte', len(c.get(LISTE, {'formule': str(F.id), 'page_size': 7},
                                             **entetes(superadmin)).json()['results']) == 7)
        lest = [Publicite(partenaire=P3, formule=F2, titre=f'Lest {k:03d} {uid}', statut='terminee',
                          image_couverture='publicites/couvertures/liste.jpg') for k in range(105)]
        Publicite.objects.bulk_create(lest)
        d = c.get(LISTE, {'formule': str(F2.id), 'page_size': 500}, **entetes(superadmin)).json()
        ok('page_size=500 plafonne a 100', (len(d['results']), d['count']) == (100, 106),
           (len(d['results']), d['count']))
        brouillon_id = str(Publicite.objects.get(titre=f'Brouillon {uid}').id)
        ok('brouillon exclu (liste et filtre statut=brouillon)', brouillon_id not in tous_ids({})
           and tous_ids({'statut': 'brouillon'}) == [])

        print('=== 2. FILTRES ===')
        ok('statut simple', set(tous_ids({'statut': 'active'})) == attendu(lambda p: p.statut == 'active'))
        ok('statut multiple (virgules)', set(tous_ids({'statut': 'active,rejetee'})) == attendu(
            lambda p: p.statut in ('active', 'rejetee')))
        r = c.get(LISTE + f'?formule={F.id}&page_size=100&statut=terminee&statut=en_attente_paiement',
                  **entetes(superadmin))
        ok('statut multiple (repete)', {x['id'] for x in r.json()['results']} == attendu(
            lambda p: p.statut in ('terminee', 'en_attente_paiement')))
        ok('partenaire', set(tous_ids({'partenaire': P1.id})) == attendu(lambda p: p.partenaire_id == P1.id))
        ok('search titre', set(tous_ids({'search': f'Pub 07 {uid}'})) == attendu(lambda p: p.titre.startswith('Pub 07')))
        ok('search nom du commerce', set(tous_ids({'search': f'Beta {uid}'})) == attendu(
            lambda p: p.partenaire_id == P2.id))
        ok('formule', len(tous_ids({})) == 26)

        def jour(dt):
            return timezone.localtime(dt).date()

        dd, df = timezone.localdate() - timedelta(days=40), timezone.localdate() - timedelta(days=20)
        chevauche = attendu(lambda p: p.debut_diffusion is not None
                            and jour(p.fin_diffusion) >= dd and jour(p.debut_diffusion) <= df)
        ok('periode [date_debut, date_fin] (chevauchement)', set(tous_ids(
            {'date_debut': str(dd), 'date_fin': str(df)})) == chevauche and chevauche, len(chevauche))
        ok('date_debut seule', set(tous_ids({'date_debut': str(dd)})) == attendu(
            lambda p: p.fin_diffusion is not None and jour(p.fin_diffusion) >= dd))
        ok('date_fin seule', set(tous_ids({'date_fin': str(df)})) == attendu(
            lambda p: p.debut_diffusion is not None and jour(p.debut_diffusion) <= df))
        ok('date invalide -> 400', c.get(LISTE, {'date_debut': '12/11/2026'}, **entetes(superadmin)).status_code == 400)
        ok('date_debut > date_fin -> 400', c.get(LISTE, {'date_debut': str(df), 'date_fin': str(dd)},
                                               **entetes(superadmin)).status_code == 400)
        ok('origine payee', set(tous_ids({'origine': 'payee'})) == attendu(lambda p: not p.est_faveur))
        ok('origine offerte', set(tous_ids({'origine': 'offerte'})) == attendu(lambda p: p.est_faveur))
        ok('origine admin', set(tous_ids({'origine': 'admin'})) == attendu(lambda p: p.cree_par_admin_id))
        ok('origine offerte,admin (OU)', set(tous_ids({'origine': 'offerte,admin'})) == attendu(
            lambda p: p.est_faveur or p.cree_par_admin_id))
        ok('origine inconnue -> 400', c.get(LISTE, {'origine': 'gratuite'}, **entetes(superadmin)).status_code == 400)
        ok('portee (effective)', set(tous_ids({'portee': 'district'})) == attendu(
            lambda p: p.portee_effective == 'district'))
        ok('filtres combines', set(tous_ids({'partenaire': P1.id, 'statut': 'terminee,active', 'origine': 'payee'}))
           == attendu(lambda p: p.partenaire_id == P1.id and p.statut in ('terminee', 'active') and not p.est_faveur))

        print('=== 3. TRIS ===')
        champs = {'cree_le': 'cree_le', 'debut_diffusion': 'debut_diffusion', 'fin_diffusion': 'fin_diffusion',
                  'affichages': 'nb_impressions', 'clics': 'nb_clics',
                  'partenaire': lambda p: p.partenaire.nom_commerce, 'titre': 'titre'}
        frais = {str(p.id): p for p in Publicite.objects.filter(formule=F).exclude(statut='brouillon')
                 .select_related('partenaire')}

        def ordre_attendu(champ, desc):
            val = champ if callable(champ) else (lambda p, n=champ: getattr(p, n))
            par_id_trie = sorted(frais.values(), key=lambda p: p.id)  # départage : id croissant
            pleins = [p for p in par_id_trie if val(p) is not None]
            vides = [p for p in par_id_trie if val(p) is None]
            pleins.sort(key=val, reverse=desc)  # tri stable : l'ordre par id est conservé
            return [str(p.id) for p in pleins + vides]

        for cle, champ in champs.items():
            for desc in (False, True):
                ordre = ('-' if desc else '') + cle
                ok(f'tri {ordre}', tous_ids({'ordre': ordre}) == ordre_attendu(champ, desc))
        ok('tri par defaut = -cree_le', tous_ids({}) == ordre_attendu('cree_le', True))
        ok('dates vides en dernier (asc et desc)', all(
            all(frais[i].debut_diffusion is None for i in tous_ids({'ordre': o})[-15:])
            for o in ('debut_diffusion', '-debut_diffusion')))
        pages = []
        for n in range(1, 7):
            pages += [x['id'] for x in c.get(LISTE, {'formule': str(F.id), 'ordre': 'clics', 'page_size': 5,
                                                     'page': n}, **entetes(superadmin)).json()['results']]
        ok('departage stable : pages de 5 (ex aequo sur clics) = ordre complet, sans doublon',
           pages == tous_ids({'ordre': 'clics'}) and len(set(pages)) == 26)
        r = c.get(LISTE, {'ordre': '-popularite'}, **entetes(superadmin))
        ok('ordre inconnu -> 400, message clair', r.status_code == 400 and 'Ordre inconnu' in r.json()['message'],
           r.content[:200])

        print('=== 4. COMPTEURS ===')
        reel = {s: sum(1 for p in pubs if p.statut == s) for s in STATUTS}
        reel['total'] = 26
        d = c.get(LISTE, {'formule': str(F.id), 'statut': 'active'}, **entetes(superadmin)).json()
        ok('liste : compteurs_statut avec filtre statut ignore', d['compteurs_statut'] == reel, d['compteurs_statut'])
        d = c.get(COMPTEURS, {'formule': str(F.id), 'statut': 'active'}, **entetes(superadmin)).json()
        ok('admin/compteurs : memes compteurs', d == {'compteurs_statut': reel}, d)
        d = c.get(COMPTEURS, {'formule': str(F.id), 'origine': 'offerte'}, **entetes(admin_stats)).json()
        ok('admin/compteurs : autres filtres appliques (origine)', d['compteurs_statut']['total'] == len(
            attendu(lambda p: p.est_faveur)), d)
        ok('admin/compteurs : filtre invalide -> 400', c.get(COMPTEURS, {'origine': 'x'},
                                                            **entetes(superadmin)).status_code == 400)

        print('=== 5. VUE PAR PARTENAIRE ===')
        r = c.get(PARTENAIRES, {'formule': str(F.id)}, **entetes(superadmin))
        d = r.json()
        lignes = {x['partenaire_id']: x for x in d.get('results', [])}
        ok('200, 2 partenaires (Gamma n a pas de pub sur F)', r.status_code == 200 and d['count'] == 2
           and set(lignes) == {P1.id, P2.id}, d)
        for prof in (P1, P2):
            siennes = [p for p in pubs if p.partenaire_id == prof.id]
            x = lignes.get(prof.id, {})
            ok(f'{prof.nom_commerce} : nombre, statuts, totaux, derniere pub', (
                x.get('nom_commerce'), x.get('nb_publicites'), x.get('par_statut'), x.get('total_affichages'),
                x.get('total_clics'), x.get('telephone')) == (
                prof.nom_commerce, len(siennes), {s: sum(1 for p in siennes if p.statut == s) for s in STATUTS},
                sum(p.nb_impressions for p in siennes), sum(p.nb_clics for p in siennes), prof.user.telephone)
               and x.get('derniere_pub_le') and abs(datetime.fromisoformat(x['derniere_pub_le'].replace(
                'Z', '+00:00')) - max(frais[str(p.id)].cree_le for p in siennes)) < timedelta(seconds=1), x)
        d = c.get(PARTENAIRES, {'formule': str(F.id), 'search': f'alpha {uid}'}, **entetes(superadmin)).json()
        ok('recherche par nom (insensible a la casse)', [x['partenaire_id'] for x in d['results']] == [P1.id], d)
        d = c.get(PARTENAIRES, {'formule': str(F.id), 'ordre': 'nom'}, **entetes(superadmin)).json()
        ok('tri nom', [x['partenaire_id'] for x in d['results']] == [P1.id, P2.id])
        d = c.get(PARTENAIRES, {'formule': str(F.id), 'ordre': '-nom'}, **entetes(superadmin)).json()
        ok('tri -nom', [x['partenaire_id'] for x in d['results']] == [P2.id, P1.id])
        d = c.get(PARTENAIRES, {'formule': str(F.id)}, **entetes(superadmin)).json()
        ok('tri par defaut -derniere_pub (pub 00 = Beta, la plus recente)',
           [x['partenaire_id'] for x in d['results']] == [P2.id, P1.id])
        for ordre in ('nb_publicites', '-affichages', 'clics', 'derniere_pub'):
            ok(f'tri partenaires {ordre} -> 200', c.get(PARTENAIRES, {'formule': str(F.id), 'ordre': ordre},
                                                        **entetes(superadmin)).status_code == 200)
        ok('partenaires : ordre inconnu -> 400', c.get(PARTENAIRES, {'ordre': 'ca'},
                                                       **entetes(superadmin)).status_code == 400)
        d = c.get(PARTENAIRES, {'formule': str(F.id), 'origine': 'offerte'}, **entetes(superadmin)).json()
        ok('filtre origine applique aux pubs comptees', sum(x['nb_publicites'] for x in d['results']) == len(
            attendu(lambda p: p.est_faveur)), d)
        d = c.get(PARTENAIRES, {'formule': str(F.id), 'date_debut': str(dd), 'date_fin': str(df)},
                  **entetes(superadmin)).json()
        ok('filtre periode applique aux pubs comptees', sum(x['nb_publicites'] for x in d['results']) == len(
            chevauche), d)
        d = c.get(PARTENAIRES, {'formule': str(F2.id), 'page_size': 1}, **entetes(superadmin)).json()
        ok('partenaires pagine (page_size=1)', len(d['results']) == 1 and d['count'] == 2 and d['next'], d)

        print('=== 6. DROITS ===')
        for url in (LISTE, COMPTEURS, PARTENAIRES):
            ok(f'{url} : admin avec voir_stats -> 200', c.get(url, **entetes(admin_stats)).status_code == 200)
            ok(f'{url} : admin sans voir_stats -> 403', c.get(url, **entetes(admin_sans)).status_code == 403)
            ok(f'{url} : partenaire -> 403', c.get(url, **entetes(p1_user)).status_code == 403)
            ok(f'{url} : anonyme -> 401', c.get(url, **entetes()).status_code == 401)

        print('=== 7. NOMBRE DE REQUETES ===')

        def nb_requetes(url, params):
            with CaptureQueriesContext(connection) as ctx:
                r = c.get(url, params, **entetes(superadmin))
            assert r.status_code == 200, r.content[:300]
            return len(ctx.captured_queries)

        n5 = nb_requetes(LISTE, {'formule': str(F.id), 'page_size': 5})
        n25 = nb_requetes(LISTE, {'formule': str(F.id), 'page_size': 25})
        ok(f'admin/liste : meme nombre de requetes pour 5 et 25 pubs ({n5} / {n25})', n5 == n25 and n25 <= 12)
        n_p1 = nb_requetes(PARTENAIRES, {'formule': str(F.id), 'page_size': 1})
        n_p2 = nb_requetes(PARTENAIRES, {'formule': str(F.id), 'page_size': 2})
        ok(f'admin/partenaires : meme nombre pour 1 et 2 partenaires ({n_p1} / {n_p2})', n_p1 == n_p2)
        s26 = nb_requetes(STATS, {'formule': str(F.id)})
        s105 = nb_requetes(STATS, {'formule': str(F2.id)})
        ok(f'admin/stats : plus de requete par pub (26 pubs : {s26}, 106 pubs : {s105})', s26 == s105)

        print('=== 8. ADMIN/STATS INCHANGE ===')
        r = c.get(STATS, {'formule': str(F.id)}, **entetes(superadmin))
        d = r.json()
        ok('admin/stats : 200, cles historiques', r.status_code == 200 and set(d) == {
            'totaux', 'compteurs_statut', 'publicites'}, list(d))
        ok('admin/stats : totaux historiques', set(d['totaux']) == {
            'nb_publicites', 'nb_actives', 'total_impressions', 'total_personnes_touchees', 'total_clics'}
           and d['totaux']['nb_publicites'] == 26, d['totaux'])
        ok('admin/stats : compteurs_statut', d['compteurs_statut'] == reel, d['compteurs_statut'])
        ok('admin/stats : 26 lignes, champs historiques exacts', len(d['publicites']) == 26 and all(
            set(x) == CHAMPS_STATS for x in d['publicites']), set(d['publicites'][0]) ^ CHAMPS_STATS)
        ok('admin/stats : impressions_par_type = calcul pub par pub', all(
            x['impressions_par_type'] == _stats_pub(frais[x['id']])['impressions_par_type'] for x in d['publicites']))
        ip = {x['id']: x['impressions_par_type'] for x in d['publicites']}
        id01 = str(Publicite.objects.get(titre=f'Pub 01 {uid}').id)
        id02 = str(Publicite.objects.get(titre=f'Pub 02 {uid}').id)
        ok('impressions_par_type : valeurs attendues', ip[id01] == {'carrousel': 2, 'interstitiel': 1}
           and ip[id02] == {'bandeau_bas': 1}, (ip[id01], ip[id02]))
        ok('admin/stats : reconduction annotee', next(x for x in d['publicites'] if x['titre'] == f'Pub 03 {uid}')
           ['reconduction_statut'] == 'active')
        liste = c.get(LISTE, {'formule': str(F.id), 'page_size': 100}, **entetes(superadmin)).json()['results']
        ok('admin/liste : lignes identiques a admin/stats', sorted(liste, key=lambda x: x['id']) == sorted(
            d['publicites'], key=lambda x: x['id']))
        ok('admin/stats sans nouveaux parametres : meme liste qu avant (filtre formule seul)',
           {x['id'] for x in d['publicites']} == set(par_id))

        raise Rollback()
except Rollback:
    print('\nRollback effectue (rien persiste).')

print(f'\n=== TOTAL : {NB_OK} OK / {len(KO)} KO ===')
if KO:
    print('KO :', *KO, sep='\n - ')
    raise SystemExit(1)
