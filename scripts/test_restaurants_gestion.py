"""Tests : fiche restaurant, horaires, téléphones, carte (section/plat/
groupes d'options via /catalogue/), menus programmés, lignes de menu,
duplication, lecture publique (liste/détail, exclusion des plats réservés
aux menus), liste admin avec indicateurs. Droits restaurateur vs admin
(capacité gerer_restaurants) et traçabilité modifie_par_role.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_restaurants_gestion.py
"""
import json, uuid
from datetime import date, time
from django.db import transaction
from django.test import Client
from django.utils.text import slugify
from rest_framework_simplejwt.tokens import AccessToken
from apps.administration.models import PermissionsAdmin
from apps.catalog.models import Categorie, Article, SectionMenu
from apps.users.models import ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
class Rollback(Exception): pass
NB = 0
def ok(l, c, d=''):
    global NB
    print(('OK   ' if c else 'FAIL '), l, '' if c else d)
    assert c, f'{l} {d}'
    NB += 1
def h(user):
    return {'HTTP_AUTHORIZATION': f'Bearer {AccessToken.for_user(user)}', 'HTTP_HOST': HOST}
def j(url, method, user, corps=None):
    c = Client()
    fn = getattr(c, method)
    kw = {'secure': True, **h(user)}
    if corps is not None:
        return fn(url, json.dumps(corps), content_type='application/json', **kw)
    return fn(url, **kw)

try:
    with transaction.atomic():
        pa = ProfilPartenaire.objects.filter(type_partenaire='restaurateur').first()
        superadmin = User.objects.filter(is_superuser=True).first()
        admin_sans = User.objects.create(telephone='+22507000001', username='t_r_sans',
            role='admin', is_staff=True, is_superuser=False, est_verifie=True)
        admin_sans.set_password('0000'); admin_sans.save()
        PermissionsAdmin.objects.create(admin=admin_sans)
        admin_avec = User.objects.create(telephone='+22507000002', username='t_r_avec',
            role='admin', is_staff=True, is_superuser=False, est_verifie=True)
        admin_avec.set_password('0000'); admin_avec.save()
        PermissionsAdmin.objects.create(admin=admin_avec, gerer_restaurants=True)

        print('=== FICHE (restaurateur) ===')
        r = j('/api/v1/restaurants/mon-restaurant/fiche/', 'get', pa.user)
        ok('GET fiche -> 200 (creation auto)', r.status_code == 200, r.content)
        r = j('/api/v1/restaurants/mon-restaurant/fiche/', 'patch', pa.user,
              {'delai_preparation_min': 30, 'services': ['sur_place', 'livraison'], 'specialites': ['Garba']})
        ok('PATCH fiche -> 200', r.status_code == 200 and r.json()['delai_preparation_min'] == 30, r.content)
        ok('traçabilité : modifie_par_role=restaurateur', r.json()['modifie_par_role'] == 'restaurateur')
        r = j('/api/v1/restaurants/mon-restaurant/fiche/', 'patch', pa.user, {'services': ['vol']})
        ok('service invalide -> 400', r.status_code == 400, r.content)

        print('=== FICHE (admin) ===')
        r = j(f'/api/v1/restaurants/admin/{pa.id}/fiche/', 'get', admin_sans)
        ok('admin sans capacite -> 403', r.status_code == 403, r.content)
        r = j(f'/api/v1/restaurants/admin/{pa.id}/fiche/', 'patch', admin_avec, {'delai_preparation_min': 15})
        ok('admin avec capacite -> 200', r.status_code == 200 and r.json()['delai_preparation_min'] == 15, r.content)
        ok('traçabilité : modifie_par_role=admin', r.json()['modifie_par_role'] == 'admin')

        print('=== HORAIRES ===')
        r = j('/api/v1/restaurants/mon-restaurant/horaires/', 'put', pa.user, {'horaires': [
            {'jour_semaine': 0, 'ouvert': True, 'heure_ouverture': '11:00', 'heure_fermeture': '22:00'},
            {'jour_semaine': 6, 'ouvert': False},
        ]})
        ok('PUT horaires -> 200, 2 lignes', r.status_code == 200 and len(r.json()) == 2, r.content)

        print('=== TELEPHONES ===')
        r = j('/api/v1/restaurants/mon-restaurant/telephones/', 'post', pa.user,
              {'libelle': 'Cuisine', 'numero': '+2250700000099'})
        ok('POST telephone -> 201', r.status_code == 201, r.content)
        tel_id = r.json()['id']
        r = j('/api/v1/restaurants/mon-restaurant/telephones/', 'get', pa.user)
        ok('GET telephones -> 1', r.status_code == 200 and len(r.json()['results']) == 1, r.content)

        print('=== CARTE : section + plat ===')
        cat = Categorie.objects.filter(est_archivee=False).first()
        section = SectionMenu.objects.create(partenaire=pa, nom='Grillades QA', ordre=1)
        plat = Article.objects.create(partenaire=pa, categorie=cat, nom='Poulet braise QA',
            slug=slugify('poulet-braise-qa-' + str(uuid.uuid4())[:6]), type='plat', prix=3000,
            section_menu=section)
        r = j(f'/api/v1/catalogue/groupes-options/?article={plat.id}', 'post', pa.user,
              {'article': plat.id, 'libelle': 'Garniture', 'min_choix': 1, 'max_choix': 1})
        ok('POST groupe-option (garniture, min=max=1) -> 201', r.status_code == 201, r.content)
        groupe_id = r.json()['id']
        r = j(f'/api/v1/catalogue/options/?groupe={groupe_id}', 'post', pa.user,
              {'groupe': groupe_id, 'nom': 'Riz', 'prix_supplement': 0})
        ok('POST option (Riz) -> 201', r.status_code == 201, r.content)
        r2 = j(f'/api/v1/catalogue/options/?groupe={groupe_id}', 'post', pa.user,
              {'groupe': groupe_id, 'nom': 'Attieke', 'prix_supplement': 500})
        ok('POST option (Attieke, +500) -> 201', r2.status_code == 201, r2.content)
        r = j(f'/api/v1/catalogue/options/?groupe={groupe_id}', 'get', admin_avec)
        ok('options non proprietaire (admin, lecture) -> 200, 2 options', r.status_code == 200 and len(r.json()['results']) == 2, r.content)

        print('=== MENUS ===')
        r = j('/api/v1/restaurants/mon-restaurant/menus/', 'post', pa.user, {
            'nature': 'hebdomadaire', 'jour_semaine': 1, 'service': 'midi',
            'heure_debut': '11:00', 'heure_fin': '15:00', 'titre': 'Menu lundi QA', 'publie': True})
        ok('POST menu -> 201', r.status_code == 201, r.content)
        menu_id = r.json()['id']
        ok('commandable=True (pas d heure limite)', r.json()['commandable'] is True)
        r = j('/api/v1/restaurants/mon-restaurant/menus/', 'post', pa.user, {
            'nature': 'date', 'service': 'midi', 'heure_debut': '11:00', 'heure_fin': '15:00'})
        ok('menu date sans date -> 400', r.status_code == 400, r.content)

        print('=== LIGNES DE MENU ===')
        r = j('/api/v1/restaurants/mon-restaurant/lignes-menu/', 'post', pa.user,
              {'menu': menu_id, 'plat': plat.id, 'prix_menu': 2000, 'stock_initial': 5, 'ordre': 1})
        ok('POST ligne-menu -> 201', r.status_code == 201, r.content)
        ligne_id = r.json()['id']
        ok('prix_effectif = prix_menu', float(r.json()['prix_effectif']) == 2000.0, r.json())
        autre_pa = ProfilPartenaire.objects.exclude(id=pa.id).first()
        autre_plat = Article.objects.create(partenaire=autre_pa, categorie=cat, nom='X autre QA',
            slug=slugify('x-autre-qa-' + str(uuid.uuid4())[:6]), type='plat', prix=1000)
        r = j('/api/v1/restaurants/mon-restaurant/lignes-menu/', 'post', pa.user,
              {'menu': menu_id, 'plat': autre_plat.id, 'ordre': 2})
        ok('plat d\'un autre restaurant -> 400', r.status_code == 400, r.content)

        print('=== DUPLICATION ===')
        r = j(f'/api/v1/restaurants/mon-restaurant/menus/{menu_id}/dupliquer/', 'post', pa.user,
              {'vers_jour_semaine': 2})
        ok('dupliquer -> 201, non publie', r.status_code == 201 and r.json()['publie'] is False, r.content)

        print('=== LECTURE PUBLIQUE ===')
        plat.est_reserve_aux_menus = False  # visible par defaut; on teste aussi le flag ensuite
        plat.save()
        c = Client()
        r = c.get(f'/api/v1/restaurants/?departement={pa.departement_id}', secure=True, HTTP_HOST=HOST)
        ok('liste publique (anonyme) -> 200', r.status_code == 200, r.content)
        ids = [x['id'] for x in r.json()['resultats']]
        ok('le restaurant y figure', pa.id in ids, ids)
        r = c.get(f'/api/v1/restaurants/{pa.id}/', secure=True, HTTP_HOST=HOST)
        ok('detail publique -> 200', r.status_code == 200, r.content)
        d = r.json()
        ok('carte presente avec la section et le plat (non reserve)',
           any(s['nom'] == 'Grillades QA' and any(p['nom'] == 'Poulet braise QA' for p in s['plats'])
               for s in d['carte']), d.get('carte'))
        noms_options = None
        for s in d['carte']:
            for p in s['plats']:
                if p['nom'] == 'Poulet braise QA':
                    noms_options = p['groupes_options']
        ok('groupes_options expose (Garniture, min=1 max=1, 2 options)',
           noms_options and noms_options[0]['libelle'] == 'Garniture'
           and noms_options[0]['min_choix'] == 1 and len(noms_options[0]['options']) == 2, noms_options)
        ok('menus_du_jour.midi = le menu publie', d['menus_du_jour']['midi'] is not None
           and d['menus_du_jour']['midi']['titre'] == 'Menu lundi QA', d['menus_du_jour'])

        plat.est_reserve_aux_menus = True
        plat.save()
        r = c.get(f'/api/v1/restaurants/{pa.id}/', secure=True, HTTP_HOST=HOST)
        d2 = r.json()
        ok('plat reserve aux menus EXCLU de la carte publique',
           not any(p['nom'] == 'Poulet braise QA' for s in d2['carte'] for p in s['plats']), d2['carte'])
        ok('mais toujours utilisable dans les menus (menus_du_jour inchange)',
           d2['menus_du_jour']['midi'] is not None)

        print('=== LISTE ADMIN INDICATEURS ===')
        r = j('/api/v1/restaurants/admin/', 'get', admin_avec)
        ok('liste admin -> 200', r.status_code == 200, r.content)
        ligne = next(x for x in r.json()['resultats'] if x['id'] == pa.id)
        ok('indicateurs presents', {'ouvert', 'menu_du_jour_publie', 'commandes_du_jour', 'a_une_fiche'} <= set(ligne), ligne)
        r = j('/api/v1/restaurants/admin/', 'get', admin_sans)
        ok('liste admin sans capacite -> 403', r.status_code == 403)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
