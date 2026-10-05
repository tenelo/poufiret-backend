"""Tests : menu Paramètres (dictionnaire de recherche, termes sans résultat,
ordre et visibilité des catégories). Droits gerer_parametres (403, super-admin,
anti-escalade), normalisation des mots-clés, regroupement et traitement des
termes, testeur sans journalisation, réordonnancement (400 hors niveau),
tri et masquage dans la grille publique, bout en bout avec la recherche.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_parametres_admin.py
"""
import json, uuid
from django.db import transaction
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken
from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.administration.views import _filtrer_anti_escalade
from apps.catalog.models import Categorie, RechercheSansResultat
from apps.users.models import User

HOST = 'poufiret.tenelo.cloud'
class Rollback(Exception): pass
NB = 0
def ok(l, c, d=''):
    global NB
    print(('OK   ' if c else 'FAIL '), l, '' if c else d)
    assert c, f'{l} {d}'
    NB += 1

def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel

def utilisateur(username, staff=False, superuser=False):
    u = User.objects.create(telephone=telephone_libre(), username=username, role='admin' if staff else 'client',
                            est_verifie=True, is_staff=staff, is_superuser=superuser)
    u.set_password('1234'); u.save()
    return u

def req(method, url, user=None, corps=None):
    kw = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    c = Client()
    if corps is None:
        return getattr(c, method)(url, **kw)
    return getattr(c, method)(url, json.dumps(corps), content_type='application/json', **kw)

try:
    with transaction.atomic():
        P = '/api/v1/administration/parametres/'
        superadmin = utilisateur('t_par_super', staff=True, superuser=True)
        admin_sans = utilisateur('t_par_sans', staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans)
        admin_avec = utilisateur('t_par_avec', staff=True)
        PermissionsAdmin.objects.create(admin=admin_avec, gerer_parametres=True)
        restaurants = Categorie.objects.get(nom='Restaurants')

        print('=== 1. DROITS ===')
        ok('admin sans capacite -> 403', req('get', P + 'recherche/categories/', admin_sans).status_code == 403)
        ok('anonyme -> 401/403', req('get', P + 'recherche/categories/').status_code in (401, 403))
        ok('super-admin -> 200', req('get', P + 'recherche/categories/', superadmin).status_code == 200)
        ok('admin avec capacite -> 200', req('get', P + 'recherche/categories/', admin_avec).status_code == 200)
        ok('anti-escalade : non super-admin ne peut pas poser gerer_parametres',
           'gerer_parametres' not in _filtrer_anti_escalade({'gerer_parametres': True, 'gerer_commandes': True}, admin_avec))
        ok('anti-escalade : super-admin le pose',
           _filtrer_anti_escalade({'gerer_parametres': True}, superadmin) == {'gerer_parametres': True})
        ok('sans capacite : ordre refuse', req('post', P + 'categories/ordre/', admin_sans,
           {'parent_id': None, 'ordre': []}).status_code == 403)

        print('=== 2. MOTS-CLES : normalisation ===')
        r = req('patch', f'{P}recherche/categories/{restaurants.id}/', admin_avec,
                {'mots_cles': ['  Garba ', 'garba', 'Grillade   Poulet', '', 'GRILLADE poulet']})
        ok('PATCH mots_cles -> 200', r.status_code == 200, r.content)
        ok('minuscules, espaces unifies, sans doublon ni vide',
           r.json()['mots_cles'] == ['garba', 'grillade poulet'], r.json())
        ok('mots_cles non liste -> 400', req('patch', f'{P}recherche/categories/{restaurants.id}/', admin_avec,
           {'mots_cles': 'garba'}).status_code == 400)
        ok('mots_cles absent -> 400', req('patch', f'{P}recherche/categories/{restaurants.id}/', admin_avec,
           {}).status_code == 400)
        r = req('get', P + 'recherche/categories/', admin_avec)
        ok('GET : mots_cles relus', any(c['id'] == restaurants.id and c['mots_cles'] == ['garba', 'grillade poulet']
                                       for c in r.json()['resultats']))
        ok('GET : champs id/nom/parent_id/mots_cles', set(r.json()['resultats'][0]) == {'id', 'nom', 'parent_id', 'mots_cles'})

        print('=== 3. TERMES SANS RESULTAT : regroupement ===')
        RechercheSansResultat.objects.all().delete()
        RechercheSansResultat.objects.create(terme='garba', nb_occurrences=3)
        RechercheSansResultat.objects.create(terme='garba ', nb_occurrences=2)
        RechercheSansResultat.objects.create(terme='xyzqq', nb_occurrences=1)
        r = req('get', P + 'recherche/sans-resultat/?statut=tous', admin_avec)
        ok('GET -> 200 {resultats, compteurs}', r.status_code == 200 and {'resultats', 'compteurs'} <= set(r.json()), r.content[:150])
        res = r.json()['resultats']
        ok('« garba » et « garba  » regroupes : nb = 5', res[0]['terme'] == 'garba' and res[0]['nb_recherches'] == 5, res)
        ok('tri par nb_recherches decroissant', [x['nb_recherches'] for x in res] == sorted([x['nb_recherches'] for x in res], reverse=True))
        ok('champs attendus', set(res[0]) == {'id', 'terme', 'nb_recherches', 'derniere_recherche', 'statut'}, res[0])
        ok('compteurs : a_traiter=2 traite=0 ignore=0', r.json()['compteurs'] == {'a_traiter': 2, 'traite': 0, 'ignore': 0}, r.json()['compteurs'])
        ok('filtre statut=traite vide', req('get', P + 'recherche/sans-resultat/?statut=traite', admin_avec).json()['resultats'] == [])
        ok('statut invalide -> 400', req('get', P + 'recherche/sans-resultat/?statut=zz', admin_avec).status_code == 400)
        ok('date invalide -> 400', req('get', P + 'recherche/sans-resultat/?du=hier', admin_avec).status_code == 400)
        ok('plage de dates acceptee -> 200',
           req('get', P + 'recherche/sans-resultat/?du=2000-01-01&au=2999-12-31', admin_avec).status_code == 200)

        print('=== 4. TRAITER : ajouter un mot-cle ===')
        id_garba = res[0]['id']
        r = req('post', f'{P}recherche/sans-resultat/{id_garba}/traiter/', admin_avec,
                {'action': 'ajouter_mot_cle'})
        ok('categorie_id manquante -> 400', r.status_code == 400, r.content)
        r = req('post', f'{P}recherche/sans-resultat/{id_garba}/traiter/', admin_avec,
                {'action': 'action_inconnue'})
        ok('action inconnue -> 400', r.status_code == 400, r.content)
        r = req('post', f'{P}recherche/sans-resultat/{id_garba}/traiter/', admin_avec,
                {'action': 'ajouter_mot_cle', 'categorie_id': restaurants.id})
        ok('ajouter_mot_cle -> 200', r.status_code == 200, r.content)
        ok('statut traite et categorie renvoyee', r.json()['statut'] == 'traite' and r.json()['categorie']['id'] == restaurants.id, r.json())
        restaurants.refresh_from_db()
        ok('« garba » ajoute aux mots-cles (pas de doublon)', restaurants.mots_cles.count('garba') == 1, restaurants.mots_cles)
        ok('toutes les occurrences du terme marquees traitees',
           RechercheSansResultat.objects.filter(terme__in=['garba', 'garba ']).exclude(statut='traite').count() == 0)
        ok('terme sans rapport intact', RechercheSansResultat.objects.get(terme='xyzqq').statut == 'a_traiter')
        r = req('get', P + 'recherche/sans-resultat/?statut=a_traiter', admin_avec)
        ok('compteurs mis a jour : a_traiter=1 traite=1',
           r.json()['compteurs'] == {'a_traiter': 1, 'traite': 1, 'ignore': 0}, r.json()['compteurs'])

        print('=== 5. TRAITER : ignorer ===')
        id_xyz = RechercheSansResultat.objects.get(terme='xyzqq').id
        r = req('post', f'{P}recherche/sans-resultat/{id_xyz}/traiter/', admin_avec, {'action': 'ignorer'})
        ok('ignorer -> 200 statut ignore', r.status_code == 200 and r.json()['statut'] == 'ignore', r.content)
        ok('compteur ignore = 1', req('get', P + 'recherche/sans-resultat/?statut=ignore', admin_avec).json()['compteurs']['ignore'] == 1)
        ok('terme inconnu -> 404', req('post', f'{P}recherche/sans-resultat/999999/traiter/', admin_avec,
           {'action': 'ignorer'}).status_code == 404)

        print('=== 6. TESTEUR : meme moteur, sans journaliser ===')
        avant = RechercheSansResultat.objects.count()
        r = req('get', P + 'recherche/tester/?q=restaurant', admin_avec)
        ok('tester -> 200 {categories, partenaires, articles, total}',
           r.status_code == 200 and {'categories', 'partenaires', 'articles', 'total'} <= set(r.json()), r.content[:150])
        ok('tester trouve la categorie Restaurants', any(c['id'] == restaurants.id for c in r.json()['categories']))
        r = req('get', P + 'recherche/tester/?q=zzqqwwxx', admin_avec)
        ok('tester sans resultat : total = 0', r.json()['total'] == 0)
        ok('tester : aucune journalisation', RechercheSansResultat.objects.count() == avant,
           (avant, RechercheSansResultat.objects.count()))

        print('=== 7. ORDRE DES CATEGORIES ===')
        r = req('get', P + 'categories/', admin_avec)
        ok('GET categories -> 200 {resultats}', r.status_code == 200 and 'resultats' in r.json(), r.content[:150])
        champs = {'id', 'nom', 'icone', 'image', 'ordre', 'est_active', 'parent_id', 'nb_partenaires'}
        ok('champs attendus', set(r.json()['resultats'][0]) == champs, r.json()['resultats'][0])
        cles = [(x['parent_id'] or 0, x['ordre'], x['nom']) for x in r.json()['resultats']]
        ok('trie par parent puis ordre', cles == sorted(cles))
        racines = list(Categorie.objects.filter(parent__isnull=True, est_archivee=False).order_by('ordre', 'nom')[:3])
        ids = [c.id for c in reversed(racines)]
        r = req('post', P + 'categories/ordre/', admin_avec, {'parent_id': None, 'ordre': ids})
        ok('reordonnancement -> 200', r.status_code == 200, r.content)
        ok('ordre = 1..n dans l ordre donne', [Categorie.objects.get(pk=i).ordre for i in ids] == [1, 2, 3],
           [Categorie.objects.get(pk=i).ordre for i in ids])
        ok('les autres racines suivent (ordre n+1..)',
           all(Categorie.objects.get(pk=c.id).ordre > 3 for c in Categorie.objects.filter(parent__isnull=True,
               est_archivee=False).exclude(id__in=ids)))
        ok('id hors niveau -> 400 (cle ordre)', req('post', P + 'categories/ordre/', admin_avec,
           {'parent_id': None, 'ordre': [999999]}).json()['details'].keys() == {'ordre'})
        ok('doublon -> 400', req('post', P + 'categories/ordre/', admin_avec,
           {'parent_id': None, 'ordre': [ids[0], ids[0]]}).status_code == 400)
        ok('ordre non liste -> 400', req('post', P + 'categories/ordre/', admin_avec,
           {'parent_id': None, 'ordre': 'abc'}).status_code == 400)
        ok('parent inconnu -> 404', req('post', P + 'categories/ordre/', admin_avec,
           {'parent_id': 999999, 'ordre': []}).status_code == 404)

        print('=== 8. VISIBILITE ET TRI DANS LA GRILLE PUBLIQUE ===')
        grille = lambda: [c['id'] for c in req('get', '/api/v1/catalogue/categories/', None).json()['results']]
        ok('publique : Restaurants visible au depart', restaurants.id in grille())
        ok('PATCH est_active=false -> 200', req('patch', f'{P}categories/{restaurants.id}/', admin_avec,
           {'est_active': False}).json()['est_active'] is False)
        ok('publique : Restaurants masquee', restaurants.id not in grille())
        ok('est_active non booleen -> 400', req('patch', f'{P}categories/{restaurants.id}/', admin_avec,
           {'est_active': 'oui'}).status_code == 400)
        req('patch', f'{P}categories/{restaurants.id}/', admin_avec, {'est_active': True})
        ok('publique : Restaurants de nouveau visible', restaurants.id in grille())
        publics = req('get', '/api/v1/catalogue/categories/', None).json()['results']
        cles_pub = [(c['ordre'], c['nom']) for c in publics if c.get('parent') is None]
        ok('publique : tri par ordre puis nom', cles_pub == sorted(cles_pub), cles_pub[:5])
        ok('publique : les 3 racines reordonnees en tete',
           grille()[:3] == ids, (grille()[:3], ids))

        print('=== 9. BOUT EN BOUT : mot-cle -> recherche publique ===')
        terme = 'mot' + uuid.uuid4().hex[:6]
        r = req('patch', f'{P}recherche/categories/{restaurants.id}/', admin_avec, {'mots_cles': [terme]})
        r = req('get', f'/api/v1/catalogue/recherche/?q={terme}', None)
        ok('recherche publique trouve la categorie par son mot-cle',
           any(c['id'] == restaurants.id for c in r.json()['categories']), r.json())
        avant = RechercheSansResultat.objects.count()
        req('get', '/api/v1/catalogue/recherche/?q=zzqqwwxxyy', None)
        ok('recherche publique sans resultat : journalise (nouveau terme)',
           RechercheSansResultat.objects.filter(terme='zzqqwwxxyy').exists())
        req('get', f'/api/v1/catalogue/recherche/?q={terme}', None)
        ok('recherche publique avec resultat : non journalisee',
           not RechercheSansResultat.objects.filter(terme=terme).exists())

        print('=== 10. JOURNAL DES ACTIONS ===')
        actions = set(JournalModeration.objects.filter(acteur=admin_avec).values_list('action', flat=True))
        ok('actions journalisees : mots-cles, ordre, visibilite, traitement, ignore',
           {'param_mots_cles', 'param_ordre_categ', 'param_categorie_visib',
            'param_recherche_traite', 'param_recherche_ignore'} <= actions, actions)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
