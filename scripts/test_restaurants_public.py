"""Tests : lecture publique des restaurants (liste, détail, menus du jour,
panier avec variante/options/ligne de menu). Aucune exception ne doit
remonter, en anonyme comme connecté, quel que soit l'état du restaurant
(sans fiche, sans horaires, sans carte, sans menu, sans logo, département
absent/inconnu/non numérique). Création automatique de la fiche restaurant.

Autonome : le test crée ses propres données (district/région/département,
catégorie, restaurants, client) et ne dépend d'aucun restaurant réel. Seule
donnée de référence lue : le plan d'abonnement « Basique ». Transaction annulée.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_restaurants_public.py
"""
import json, uuid
from datetime import time
from django.db import transaction
from django.test import Client
from django.utils import timezone
from django.utils.text import slugify
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.gis.geos import Point
from apps.catalog.models import Article, Categorie
from apps.geo.models import Departement, District, Region
from apps.restaurants import services
from apps.restaurants.models import LigneMenu, MenuProgramme, ProfilRestaurant
from apps.users.models import HoraireOuverture, PlanAbonnement, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
# Limitation de débit DRF désactivée pour ce script : sinon tous les scripts partagent
# le compteur anonyme (60/min, client de test = 127.0.0.1) et la suite complète reçoit des 429.
from unittest import mock as _mock_debit
from rest_framework.views import APIView as _APIViewDebit
_mock_debit.patch.object(_APIViewDebit, 'get_throttles', return_value=[]).start()
class Rollback(Exception): pass
NB = 0
def ok(l, c, d=''):
    global NB
    print(('OK   ' if c else 'FAIL '), l, '' if c else d)
    assert c, f'{l} {d}'
    NB += 1

def anon(url):
    return Client(raise_request_exception=True).get(url, secure=True, HTTP_HOST=HOST)
def connecte(url, user):
    tok = AccessToken.for_user(user)
    return Client(raise_request_exception=True).get(
        url, secure=True, HTTP_HOST=HOST, HTTP_AUTHORIZATION=f'Bearer {tok}')

def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel

CHAMPS_STATUT = {'est_ouvert', 'prochaine_ouverture', 'message_statut'}

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        district = District.objects.create(nom=f'District QA pub {uid}')
        region = Region.objects.create(nom=f'Region QA pub {uid}', district=district)
        dep = Departement.objects.create(nom=f'Dep QA pub {uid}', region=region)
        ferke = dep.id
        cat_resto = Categorie.objects.create(
            nom=f'Restaurants QA {uid}', slug=f'restaurants-qa-{uid}',
            types_partenaire=['restaurateur'], types_articles=['plat'])

        def partenaire(nom, type_partenaire='restaurateur', **kw):
            u = User.objects.create(telephone=telephone_libre(), username=f't_pub_{slugify(nom)}_{uid}',
                                    role='partenaire', est_verifie=True)
            return ProfilPartenaire.objects.create(
                user=u, plan=plan, nom_commerce=f'{nom} {uid}', type_partenaire=type_partenaire,
                statut='actif', est_visible=True, departement=dep, **kw)

        # « Capi » : restaurant vide (ni horaires, ni carte, ni menu).
        resto_vide = partenaire('Resto vide QA')
        # « Sara » : logo/couverture posés, sans localisation.
        resto_sara = partenaire('Resto Sara QA', logo='partenaires/logo_qa.png',
                                photo_couverture='partenaires/couv_qa.png')
        resto_sans_fiche = partenaire('Resto sans fiche QA')
        for p in (resto_vide, resto_sara, resto_sans_fiche):
            services.fiche_de(p)  # état de départ connu : fiche présente

        print('=== 1. QUATRE ENDPOINTS EN 200 (anonyme) ===')
        urls = [f'/api/v1/restaurants/?departement={ferke}', f'/api/v1/restaurants/{resto_vide.id}/',
                f'/api/v1/restaurants/menus-du-jour/?departement={ferke}',
                f'/api/v1/restaurants/{resto_sara.id}/']
        for url in urls:
            ok(f'anonyme {url} -> 200', anon(url).status_code == 200, url)

        client = User.objects.create(telephone=telephone_libre(), username=f't_pub_client_{uid}',
                                     role='client', est_verifie=True)
        client.set_password('0000'); client.save()
        print('=== 2. QUATRE ENDPOINTS EN 200 (connecté) ===')
        for url in urls:
            ok(f'connecte {url} -> 200', connecte(url, client).status_code == 200, url)

        print('=== 3. RESTAURANT SANS FICHE : fiche creee a la lecture ===')
        ProfilRestaurant.objects.filter(partenaire=resto_sans_fiche).delete()
        r = anon(f'/api/v1/restaurants/?departement={ferke}')
        ok('liste -> 200 avec restaurant sans fiche', r.status_code == 200, r.content)
        ok('restaurant sans fiche present dans la liste',
           any(x['id'] == resto_sans_fiche.id for x in r.json()['resultats']))
        ok('fiche recreee par la lecture', ProfilRestaurant.objects.filter(partenaire=resto_sans_fiche).exists())
        ProfilRestaurant.objects.filter(partenaire=resto_sans_fiche).delete()
        r = anon(f'/api/v1/restaurants/{resto_sans_fiche.id}/')
        ok('detail restaurant sans fiche -> 200', r.status_code == 200, r.content)
        ok('statut present sur detail sans fiche', CHAMPS_STATUT <= set(r.json()), r.json().keys())

        print('=== 4. SANS HORAIRES : statut degrade propre ===')
        ok('pre-requis : aucun horaire', not HoraireOuverture.objects.filter(partenaire=resto_vide).exists())
        d = anon(f'/api/v1/restaurants/{resto_vide.id}/').json()
        ok('est_ouvert = false', d['est_ouvert'] is False, d)
        ok('message_statut = Horaires non renseignés', d['message_statut'] == 'Horaires non renseignés', d)
        ok('prochaine_ouverture = null', d['prochaine_ouverture'] is None, d)
        ligne = next(x for x in anon(f'/api/v1/restaurants/?departement={ferke}').json()['resultats']
                     if x['id'] == resto_vide.id)
        ok('liste : statut present sans horaires', CHAMPS_STATUT <= set(ligne)
           and ligne['message_statut'] == 'Horaires non renseignés', ligne)

        print('=== 5. SANS CARTE NI MENU ===')
        ok('carte vide -> liste', d['carte'] == [], d['carte'])
        ok('menus_du_jour tous null', all(v is None for v in d['menus_du_jour'].values()), d['menus_du_jour'])

        print('=== 6. SANS LOGO NI COUVERTURE ===')
        d = anon(f'/api/v1/restaurants/{resto_sara.id}/').json()
        ok('pre-requis : logo/couverture presents (URL absolue)',
           (d['logo'] or '').startswith('http') and (d['couverture'] or '').startswith('http'), d['logo'])
        resto_sara.logo = None
        resto_sara.photo_couverture = None
        resto_sara.save()
        d = anon(f'/api/v1/restaurants/{resto_sara.id}/').json()
        ok('logo = null', d['logo'] is None, d['logo'])
        ok('couverture = null', d['couverture'] is None, d['couverture'])
        ligne = next(x for x in anon(f'/api/v1/restaurants/?departement={ferke}').json()['resultats']
                     if x['id'] == resto_sara.id)
        ok('liste : logo/couverture null sans erreur', ligne['logo'] is None and ligne['couverture'] is None)

        print('=== 7. DEPARTEMENT ABSENT / INCONNU / NON NUMERIQUE ===')
        for url in ['/api/v1/restaurants/', '/api/v1/restaurants/?departement=999999',
                    '/api/v1/restaurants/?departement=abc', '/api/v1/restaurants/menus-du-jour/',
                    '/api/v1/restaurants/menus-du-jour/?departement=abc']:
            ok(f'{url} -> 200', anon(url).status_code == 200, url)

        print('=== 8. MENU DU JOUR PUBLIE : statut present dans menus-du-jour ===')
        plat = Article.objects.create(partenaire=resto_sara, categorie=cat_resto, nom='Garba QA public',
            slug=slugify('garba-qa-public-' + str(uuid.uuid4())[:6]), type='plat', prix=1500)
        fiche = services.fiche_de(resto_sara)
        menu = MenuProgramme.objects.create(restaurant=fiche, nature='hebdomadaire',
            jour_semaine=timezone.localdate().isoweekday(), service='midi',
            heure_debut=time(0, 0), heure_fin=time(23, 59), publie=True, titre='Menu du jour QA')
        LigneMenu.objects.create(menu=menu, plat=plat, prix_menu=2000, ordre=1)
        r = anon(f'/api/v1/restaurants/menus-du-jour/?departement={ferke}')
        entree = next((x for x in r.json()['resultats'] if x['partenaire_id'] == resto_sara.id), None)
        ok('menus-du-jour contient le restaurant avec menu', entree is not None, r.json())
        ok('menus-du-jour : statut present', entree and CHAMPS_STATUT <= set(entree), entree)
        ok('menus-du-jour : restaurant sans menu absent',
           all(x['partenaire_id'] != resto_vide.id for x in r.json()['resultats']))
        d = anon(f'/api/v1/restaurants/{resto_sara.id}/').json()
        ok('detail : menus_du_jour.midi renseigne', d['menus_du_jour']['midi'] is not None, d['menus_du_jour'])

        print('=== 8b. LOCALISATION DANS LA LISTE ET LE DETAIL ===')
        ok('detail : localite_id/localite_nom/quartier_id/quartier_nom presents',
           {'localite_id', 'localite_nom', 'quartier_id', 'quartier_nom'} <= set(d), d.keys())
        ligne = next(x for x in anon(f'/api/v1/restaurants/?departement={ferke}').json()['resultats']
                     if x['id'] == resto_sara.id)
        ok('liste : localite_nom/quartier_nom presents',
           {'localite_id', 'localite_nom', 'quartier_id', 'quartier_nom'} <= set(ligne), ligne.keys())

        print('=== 9. LATITUDE / LONGITUDE ===')
        ok('sans localisation -> latitude/longitude null', d['latitude'] is None and d['longitude'] is None, d)
        resto_sara.localisation = Point(-5.5, 9.4, srid=4326)
        resto_sara.save()
        d = anon(f'/api/v1/restaurants/{resto_sara.id}/').json()
        ok('avec localisation -> latitude=9.4 longitude=-5.5',
           abs(d['latitude'] - 9.4) < 1e-6 and abs(d['longitude'] + 5.5) < 1e-6, d)

        print('=== 10. SIGNAL : passage au type restaurateur cree la fiche ===')
        non_resto = partenaire('Commerce QA', type_partenaire='commercant')
        ok('pre-requis : pas de fiche pour un commercant',
           not ProfilRestaurant.objects.filter(partenaire=non_resto).exists())
        non_resto.type_partenaire = 'restaurateur'
        non_resto.save()
        ok('fiche creee au passage en restaurateur',
           ProfilRestaurant.objects.filter(partenaire=non_resto).exists())

        print('=== 11. PANIER : variante, options, ligne de menu ===')
        grillade = Article.objects.create(partenaire=resto_sara, categorie=cat_resto,
            nom='Grillade QA panier', slug=slugify('grillade-qa-panier-' + str(uuid.uuid4())[:6]),
            type='plat', prix=3000)
        var = grillade.variantes.create(nom='Demi', prix_supplement=-500)
        groupe = grillade.groupes_options.create(libelle='Garniture', min_choix=1, max_choix=1)
        riz = groupe.options.create(nom='Riz', prix_supplement=0)
        tc = Client(raise_request_exception=True)
        tok = AccessToken.for_user(client)
        kw = {'secure': True, 'HTTP_HOST': HOST, 'HTTP_AUTHORIZATION': f'Bearer {tok}'}
        r = tc.post('/api/v1/orders/paniers/ajouter/', json.dumps({
            'article': grillade.id, 'quantite': 1, 'variante_id': var.id, 'option_ids': [riz.id]}),
            content_type='application/json', **kw)
        ok('ajout grillade variante + option -> 201', r.status_code == 201, r.content)
        r = tc.post('/api/v1/orders/paniers/ajouter/', json.dumps({
            'ligne_menu': LigneMenu.objects.get(menu=menu).id, 'quantite': 1}),
            content_type='application/json', **kw)
        ok('ajout ligne de menu -> 201', r.status_code == 201, r.content)
        r = tc.get('/api/v1/orders/paniers/', secure=True, HTTP_HOST=HOST,
                   HTTP_AUTHORIZATION=f'Bearer {tok}')
        ok('GET paniers -> 200', r.status_code == 200, r.content)
        lignes = r.json()['results'][0]['lignes'] if isinstance(r.json(), dict) and 'results' in r.json() \
            else r.json()[0]['lignes']
        l_grill = next(l for l in lignes if l['article_nom'] == 'Grillade QA panier')
        l_menu = next(l for l in lignes if l['ligne_menu'] is not None)
        ok('variante_nom = Demi', l_grill['variante_nom'] == 'Demi', l_grill)
        ok('options = [{nom: Riz, prix_supplement: 0}]',
           l_grill['options'] == [{'nom': 'Riz', 'prix_supplement': 0}], l_grill['options'])
        ok('ligne menu : ligne_menu renseigne et variante_nom null',
           l_menu['variante_nom'] is None and l_menu['options'] == [], l_menu)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
