"""Tests : gabarits — phase 0 (correspondance type → gabarit, nouveaux
types, rattachement P1, champ gabarit dans l'annuaire / la vitrine / le
détail restaurant, moteur restaurants étendu aux nouveaux gabarits,
fonctions désactivées par gabarit, périmètre de la restauration inchangé).

Données propres, rollback, limitation de débit désactivée.
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_gabarits_phase0.py
"""
import json, uuid
from django.db import transaction
from django.test import Client
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.tokens import AccessToken
from apps.administration.models import PermissionsAdmin
from apps.catalog.models import Article, Categorie, PartenaireCategorie
from apps.geo.models import Departement
from apps.restaurants import gabarits, services
from apps.restaurants.models import ProfilRestaurant
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

SimpleRateThrottle.allow_request = lambda self, request, view: True
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

def utilisateur(username, role='client', staff=False, superuser=False):
    return User.objects.create(telephone=telephone_libre(), username=f'{username}_{uuid.uuid4().hex[:5]}',
                               role=role, est_verifie=True, is_staff=staff, is_superuser=superuser)

def req(method, url, user=None, corps=None):
    kw = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    if corps is None:
        return getattr(Client(), method)(url, **kw)
    return getattr(Client(), method)(url, json.dumps(corps), content_type='application/json', **kw)

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        dep = Departement.objects.order_by('id').first()
        T = ProfilPartenaire.TypePartenaire
        # Catégorie de test rattachée à tous les types testés (indépendante de la prod).
        cat = Categorie.objects.create(nom=f'QA Gabarits {uid}', slug=f'qa-gabarits-{uid}',
            types_partenaire=['fast_food', 'boulanger', 'pharmacien', 'boutique_mode', 'libraire', 'hotelier'],
            types_articles=['plat', 'produit'])

        def partenaire(type_, nom):
            return ProfilPartenaire.objects.create(user=utilisateur(f't_gab_{type_}', 'partenaire'), plan=plan,
                nom_commerce=f'{nom} {uid}', type_partenaire=type_, statut='actif', est_visible=True, departement=dep)

        P = {t: partenaire(t, n) for t, n in [
            ('restaurateur', 'Resto'), ('fast_food', 'Fast'), ('boulanger', 'Boulange'),
            ('pharmacien', 'Pharma'), ('boutique_mode', 'Mode'), ('libraire', 'Livres'),
            ('hotelier', 'Hotel'), ('coiffeur', 'Coiffure')]}
        super_ = utilisateur('t_gab_super', 'admin', staff=True, superuser=True)
        admin_sans = utilisateur('t_gab_sans', 'admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans)

        print('=== 1. TYPES ET CORRESPONDANCE (table unique) ===')
        ok('types crees : fast_food, boutique_mode (libraire deja present)',
           T('fast_food').label == 'Fast-food' and T('boutique_mode').label == 'Vendeur de chaussures / Mode'
           and T('libraire').label == 'Libraire')
        attendu = {'restaurateur': 'restaurant', 'fast_food': 'restaurant', 'boulanger': 'boulangerie',
                   'pharmacien': 'pharmacie', 'boutique_mode': 'mode', 'libraire': 'librairie',
                   'coiffeur': 'generique', 'commercant': 'generique', 'autre': 'generique'}
        ok('correspondance type -> gabarit', all(gabarits.gabarit_de_type(t) == g for t, g in attendu.items()),
           {t: gabarits.gabarit_de_type(t) for t in attendu})
        ok('types geres a part : valeurs propres', gabarits.gabarit_de_type('hotelier') == 'hotel'
           and gabarits.gabarit_de_type('loueur_maison') == 'location_maison'
           and gabarits.gabarit_de_type('loueur_voiture') == 'location_vehicule')
        ok('TYPES_MOTEUR = restaurant/fast_food/boulanger/pharmacien/boutique_mode/libraire',
           set(services.TYPES_MOTEUR) == {'restaurateur', 'fast_food', 'boulanger', 'pharmacien',
                                          'boutique_mode', 'libraire'})
        ok('TYPES_RESTAURATION = gabarit restaurant seulement',
           set(services.TYPES_RESTAURATION) == {'restaurateur', 'fast_food'})

        print('=== 2. RATTACHEMENT P1 ET FICHE AUTOMATIQUES ===')
        for t in ('fast_food', 'boutique_mode', 'libraire'):
            ok(f'{t} rattache a la categorie correspondante',
               PartenaireCategorie.objects.filter(partenaire=P[t], categorie=cat).exists())
        ok('fiche moteur creee pour chaque type du moteur', all(
            ProfilRestaurant.objects.filter(partenaire=P[t]).exists() for t in services.TYPES_MOTEUR))
        ok('pas de fiche moteur pour coiffeur / hotelier', not ProfilRestaurant.objects.filter(
            partenaire__in=[P['coiffeur'], P['hotelier']]).exists())

        print('=== 3. CHAMP GABARIT : ANNUAIRE, VITRINE, DETAIL ===')
        r = req('get', f'/api/v1/catalogue/categories/{cat.slug}/partenaires/')
        ok('annuaire -> 200', r.status_code == 200, r.content)
        cartes = {x['id']: x for x in r.json()}
        ok('annuaire : gabarit par carte', cartes[P['pharmacien'].id]['gabarit'] == 'pharmacie'
           and cartes[P['libraire'].id]['gabarit'] == 'librairie' and cartes[P['hotelier'].id]['gabarit'] == 'hotel',
           cartes.get(P['pharmacien'].id))
        cles_annuaire = {'id', 'nom_commerce', 'description', 'logo', 'photo_couverture', 'departement', 'region',
                         'latitude', 'longitude', 'adresse', 'quartier', 'localite_nom', 'quartier_nom', 'secteur',
                         'gabarit'}
        ok('annuaire : seul gabarit ajoute', set(cartes[P['pharmacien'].id]) == cles_annuaire,
           set(cartes[P['pharmacien'].id]) ^ cles_annuaire)
        r = req('get', f'/api/v1/auth/partenaires/{P["boutique_mode"].id}/')
        ok('vitrine : gabarit', r.status_code == 200 and r.json()['gabarit'] == 'mode', r.content)
        r = req('get', f'/api/v1/auth/partenaires/{P["coiffeur"].id}/')
        ok('vitrine generique', r.json()['gabarit'] == 'generique')
        for t, g in [('restaurateur', 'restaurant'), ('fast_food', 'restaurant'), ('pharmacien', 'pharmacie')]:
            r = req('get', f'/api/v1/restaurants/{P[t].id}/')
            ok(f'detail /restaurants/<{t}>/ -> 200, gabarit {g}', r.status_code == 200 and r.json()['gabarit'] == g,
               r.content[:200])
        ok('detail hotelier -> 404', req('get', f'/api/v1/restaurants/{P["hotelier"].id}/').status_code == 404)

        print('=== 4. MOTEUR ETENDU : mon-restaurant/ et admin/<id>/ ===')
        for t in services.TYPES_MOTEUR:
            ok(f'{t} : GET mon-restaurant/fiche -> 200',
               req('get', '/api/v1/restaurants/mon-restaurant/fiche/', P[t].user).status_code == 200)
            ok(f'{t} : GET admin/<id>/fiche (super) -> 200',
               req('get', f'/api/v1/restaurants/admin/{P[t].id}/fiche/', super_).status_code == 200)
        ok('hotelier / coiffeur -> 403 sur mon-restaurant', all(
            req('get', '/api/v1/restaurants/mon-restaurant/fiche/', P[t].user).status_code == 403
            for t in ('hotelier', 'coiffeur')))
        ok('admin sans capacite -> 403',
           req('get', f'/api/v1/restaurants/admin/{P["pharmacien"].id}/fiche/', admin_sans).status_code == 403)
        r = req('get', '/api/v1/restaurants/mon-restaurant/fiche/', P['libraire'].user)
        ok('fiche : gabarit + type_partenaire', r.json()['gabarit'] == 'librairie'
           and r.json()['type_partenaire'] == 'libraire', r.json())
        r = req('post', '/api/v1/restaurants/mon-restaurant/carte/sections/', P['pharmacien'].user,
                {'nom': 'Antalgiques', 'ordre': 1})
        ok('pharmacie : POST section -> 201', r.status_code == 201, r.content)
        r = req('post', '/api/v1/restaurants/mon-restaurant/carte/plats/', P['pharmacien'].user,
                {'nom': 'Paracétamol', 'prix': 500, 'section_menu': r.json()['id']})
        ok('pharmacie : POST produit -> 201, type produit', r.status_code == 201
           and Article.objects.get(pk=r.json()['id']).type == 'produit', r.content)
        r = req('post', '/api/v1/restaurants/mon-restaurant/carte/plats/', P['fast_food'].user,
                {'nom': 'Burger', 'prix': 2500})
        ok('fast-food : POST plat -> 201, type plat', r.status_code == 201
           and Article.objects.get(pk=r.json()['id']).type == 'plat', r.content)
        burger = r.json()['id']

        print('=== 5. FONCTIONS PAR GABARIT (menus, options) ===')
        menu = {'nature': 'date', 'date': '2030-01-01', 'service': 'midi', 'heure_debut': '11:00',
                'heure_fin': '14:00', 'titre': 'Menu'}
        r = req('post', '/api/v1/restaurants/mon-restaurant/menus/', P['pharmacien'].user, menu)
        ok('pharmacie : menus -> 400 details.gabarit', r.status_code == 400 and 'gabarit' in r.json()['details'],
           r.content)
        r = req('post', '/api/v1/restaurants/mon-restaurant/menus/', P['fast_food'].user, menu)
        ok('fast-food : menus -> 201', r.status_code == 201, r.content)
        livre = req('post', '/api/v1/restaurants/mon-restaurant/carte/plats/', P['libraire'].user,
                    {'nom': 'Le Petit Prince', 'prix': 3000, 'fiche_specifique': {'auteur': 'Saint-Exupéry'}}).json()['id']
        r = req('post', '/api/v1/restaurants/mon-restaurant/carte/groupes-options/', P['libraire'].user,
                {'article': livre, 'libelle': 'Couverture', 'min_choix': 0, 'max_choix': 1})
        ok('librairie : groupes d options -> 400', r.status_code == 400 and 'gabarit' in r.json()['details'], r.content)
        pain = req('post', '/api/v1/restaurants/mon-restaurant/carte/plats/', P['boulanger'].user,
                   {'nom': 'Gâteau', 'prix': 8000}).json()['id']
        r = req('post', '/api/v1/restaurants/mon-restaurant/carte/groupes-options/', P['boulanger'].user,
                {'article': pain, 'libelle': 'Parfum', 'min_choix': 1, 'max_choix': 1})
        ok('boulangerie : groupes d options -> 201', r.status_code == 201, r.content)

        print('=== 6. PERIMETRE RESTAURATION INCHANGE ===')
        ids = {x['id'] for x in req('get', '/api/v1/restaurants/').json()['resultats']}
        ok('liste /restaurants/ : restaurant et fast-food, pas pharmacie/librairie',
           {P['restaurateur'].id, P['fast_food'].id} <= ids and not ({P['pharmacien'].id, P['libraire'].id} & ids))
        r = req('get', '/api/v1/restaurants/admin/', super_)
        lignes = {x['id']: x for x in r.json()['resultats']}
        ok('liste admin : tous les types du moteur avec gabarit', lignes[P['pharmacien'].id]['gabarit'] == 'pharmacie'
           and lignes[P['fast_food'].id]['type_partenaire'] == 'fast_food' and P['coiffeur'].id not in lignes)
        r = req('get', '/api/v1/restaurants/admin/?gabarit=librairie', super_)
        ok('liste admin ?gabarit=librairie', {x['gabarit'] for x in r.json()['resultats']} == {'librairie'})

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
