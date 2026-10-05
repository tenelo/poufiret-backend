"""Tests : lecture publique des restaurants (liste, détail, menus du jour,
panier avec variante/options/ligne de menu). Aucune exception ne doit
remonter, en anonyme comme connecté, quel que soit l'état du restaurant
(sans fiche, sans horaires, sans carte, sans menu, sans logo, département
absent/inconnu/non numérique). Création automatique de la fiche restaurant.

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
from apps.restaurants.models import LigneMenu, MenuProgramme, ProfilRestaurant
from apps.users.models import HoraireOuverture, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
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

CHAMPS_STATUT = {'est_ouvert', 'prochaine_ouverture', 'message_statut'}

try:
    with transaction.atomic():
        ferke = 1
        chez_capi = ProfilPartenaire.objects.get(id=53)
        chez_sara = ProfilPartenaire.objects.get(id=54)
        autre_resto = ProfilPartenaire.objects.get(id=8)

        print('=== 1. QUATRE ENDPOINTS EN 200 (anonyme) ===')
        for url in [f'/api/v1/restaurants/?departement={ferke}', '/api/v1/restaurants/53/',
                    f'/api/v1/restaurants/menus-du-jour/?departement={ferke}',
                    '/api/v1/restaurants/54/']:
            ok(f'anonyme {url} -> 200', anon(url).status_code == 200, url)

        client = User.objects.create(telephone='+22507000040', username='t_pub_client',
                                     role='client', est_verifie=True)
        client.set_password('0000'); client.save()
        print('=== 2. QUATRE ENDPOINTS EN 200 (connecté) ===')
        for url in [f'/api/v1/restaurants/?departement={ferke}', '/api/v1/restaurants/53/',
                    f'/api/v1/restaurants/menus-du-jour/?departement={ferke}',
                    '/api/v1/restaurants/54/']:
            ok(f'connecte {url} -> 200', connecte(url, client).status_code == 200, url)

        print('=== 3. RESTAURANT SANS FICHE : fiche creee a la lecture ===')
        ProfilRestaurant.objects.filter(partenaire=autre_resto).delete()
        r = anon(f'/api/v1/restaurants/?departement={ferke}')
        ok('liste -> 200 avec restaurant sans fiche', r.status_code == 200, r.content)
        ok('restaurant sans fiche present dans la liste',
           any(x['id'] == autre_resto.id for x in r.json()['resultats']))
        ok('fiche recreee par la lecture', ProfilRestaurant.objects.filter(partenaire=autre_resto).exists())
        ProfilRestaurant.objects.filter(partenaire=autre_resto).delete()
        r = anon(f'/api/v1/restaurants/{autre_resto.id}/')
        ok('detail restaurant sans fiche -> 200', r.status_code == 200, r.content)
        ok('statut present sur detail sans fiche', CHAMPS_STATUT <= set(r.json()), r.json().keys())

        print('=== 4. SANS HORAIRES : statut degrade propre ===')
        HoraireOuverture.objects.filter(partenaire=chez_capi).delete()
        d = anon(f'/api/v1/restaurants/{chez_capi.id}/').json()
        ok('est_ouvert = false', d['est_ouvert'] is False, d)
        ok('message_statut = Horaires non renseignés', d['message_statut'] == 'Horaires non renseignés', d)
        ok('prochaine_ouverture = null', d['prochaine_ouverture'] is None, d)
        ligne = next(x for x in anon(f'/api/v1/restaurants/?departement={ferke}').json()['resultats']
                     if x['id'] == chez_capi.id)
        ok('liste : statut present sans horaires', CHAMPS_STATUT <= set(ligne)
           and ligne['message_statut'] == 'Horaires non renseignés', ligne)

        print('=== 5. SANS CARTE NI MENU ===')
        ok('carte vide -> liste', d['carte'] == [], d['carte'])
        ok('menus_du_jour tous null', all(v is None for v in d['menus_du_jour'].values()), d['menus_du_jour'])

        print('=== 6. SANS LOGO NI COUVERTURE ===')
        chez_sara.logo = None
        chez_sara.photo_couverture = None
        chez_sara.save()
        d = anon(f'/api/v1/restaurants/{chez_sara.id}/').json()
        ok('logo = null', d['logo'] is None, d['logo'])
        ok('couverture = null', d['couverture'] is None, d['couverture'])
        ligne = next(x for x in anon(f'/api/v1/restaurants/?departement={ferke}').json()['resultats']
                     if x['id'] == chez_sara.id)
        ok('liste : logo/couverture null sans erreur', ligne['logo'] is None and ligne['couverture'] is None)

        print('=== 7. DEPARTEMENT ABSENT / INCONNU / NON NUMERIQUE ===')
        for url in ['/api/v1/restaurants/', '/api/v1/restaurants/?departement=999999',
                    '/api/v1/restaurants/?departement=abc', '/api/v1/restaurants/menus-du-jour/',
                    '/api/v1/restaurants/menus-du-jour/?departement=abc']:
            ok(f'{url} -> 200', anon(url).status_code == 200, url)

        print('=== 8. MENU DU JOUR PUBLIE : statut present dans menus-du-jour ===')
        cat = Categorie.objects.filter(est_archivee=False, types_partenaire__contains=['restaurateur']).first()
        plat = Article.objects.create(partenaire=chez_sara, categorie=cat, nom='Garba QA public',
            slug=slugify('garba-qa-public-' + str(uuid.uuid4())[:6]), type='plat', prix=1500)
        fiche = ProfilRestaurant.objects.get(partenaire=chez_sara)
        menu = MenuProgramme.objects.create(restaurant=fiche, nature='hebdomadaire',
            jour_semaine=timezone.localdate().isoweekday(), service='midi',
            heure_debut=time(0, 0), heure_fin=time(23, 59), publie=True, titre='Menu du jour QA')
        LigneMenu.objects.create(menu=menu, plat=plat, prix_menu=2000, ordre=1)
        r = anon(f'/api/v1/restaurants/menus-du-jour/?departement={ferke}')
        entree = next((x for x in r.json()['resultats'] if x['partenaire_id'] == chez_sara.id), None)
        ok('menus-du-jour contient le restaurant avec menu', entree is not None, r.json())
        ok('menus-du-jour : statut present', entree and CHAMPS_STATUT <= set(entree), entree)
        d = anon(f'/api/v1/restaurants/{chez_sara.id}/').json()
        ok('detail : menus_du_jour.midi renseigne', d['menus_du_jour']['midi'] is not None, d['menus_du_jour'])

        print('=== 9. LATITUDE / LONGITUDE ===')
        d = anon(f'/api/v1/restaurants/{chez_sara.id}/').json()
        ok('sans localisation -> latitude/longitude null', d['latitude'] is None and d['longitude'] is None, d)
        chez_sara.localisation = Point(-5.5, 9.4, srid=4326)
        chez_sara.save()
        d = anon(f'/api/v1/restaurants/{chez_sara.id}/').json()
        ok('avec localisation -> latitude=9.4 longitude=-5.5',
           abs(d['latitude'] - 9.4) < 1e-6 and abs(d['longitude'] + 5.5) < 1e-6, d)

        print('=== 10. SIGNAL : passage au type restaurateur cree la fiche ===')
        non_resto = ProfilPartenaire.objects.exclude(
            type_partenaire='restaurateur').filter(type_partenaire='commercant').first()
        if non_resto is None:
            non_resto = ProfilPartenaire.objects.exclude(type_partenaire='restaurateur').first()
        ProfilRestaurant.objects.filter(partenaire=non_resto).delete()
        non_resto.type_partenaire = 'restaurateur'
        non_resto.save()
        ok('fiche creee au passage en restaurateur',
           ProfilRestaurant.objects.filter(partenaire=non_resto).exists())

        print('=== 11. PANIER : variante, options, ligne de menu ===')
        cat_resto = Categorie.objects.filter(est_archivee=False, types_partenaire__contains=['restaurateur']).first()
        grillade = Article.objects.create(partenaire=chez_sara, categorie=cat_resto,
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
