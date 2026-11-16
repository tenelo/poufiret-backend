"""Tests : gabarit fast-food dédié.

- gabarit fast_food (« Fast-food » : Rubrique / Produit / Tailles), sans menus,
  options actives, dans la restauration (liste, commandes, ouverture, canal) ;
- combos v1 : article « Menu » + groupes d'options (min/max réglés par le
  partenaire), est_combo + prix_reference (gestion partenaire et admin,
  validation), prix_reference exposé seulement s'il dépasse le prix ;
  produits vendables seuls ; panier : groupes obligatoires / facultatifs ;
- temps de préparation par article : modifiable (gestion) et exposé (app) ;
- « le plus commandé » : top 3 sur 30 jours (commandes non annulées, articles
  actifs), populaire + rang_populaire, une requête groupée par réponse ;
- autres gabarits inchangés (pas de champs fast-food).

Données propres, transaction annulée (rien ne persiste), limitation de débit
désactivée, total OK / KO.
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_fast_food.py
"""
import json
import sys
import traceback
import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.catalog.models import Article, Categorie, SectionMenu
from apps.geo.models import Departement
from apps.notifications.canaux import commande_est_restaurant
from apps.orders.models import Commande, LigneCommande
from apps.restaurants import gabarits
from apps.restaurants import services as services_resto
from apps.restaurants.models import ProfilRestaurant
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
# Limitation de débit DRF désactivée pour ce script : sinon tous les scripts partagent
# le compteur anonyme (60/min, client de test = 127.0.0.1) et la suite complète reçoit des 429.
from unittest import mock as _mock_debit
from rest_framework.views import APIView as _APIViewDebit
_mock_debit.patch.object(_APIViewDebit, 'get_throttles', return_value=[]).start()

MON = '/api/v1/restaurants/mon-restaurant'
PANIER = '/api/v1/orders/paniers/ajouter/'


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
        print('FAIL', libelle, str(detail)[:500])


def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel


def utilisateur(role='client', **kw):
    return User.objects.create(telephone=telephone_libre(), username=f't_ff_{uuid.uuid4().hex[:8]}',
                               role=role, est_verifie=True, **kw)


def req(method, url, user=None, corps=None):
    kw = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    if corps is None:
        return getattr(Client(), method)(url, **kw)
    return getattr(Client(), method)(url, json.dumps(corps), content_type='application/json', **kw)


def contenu(r):
    try:
        return json.dumps(r.json(), ensure_ascii=False)[:400]
    except Exception:
        return r.content[:400]


def details(r):
    return set((r.json().get('details') or {})) if r.status_code == 400 else r.status_code


try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        dep = Departement.objects.filter(est_actif=True).order_by('id').first()
        # La catégorie « Fast-food » réelle déclare fast_food ; à défaut (autre
        # environnement), une catégorie de test (transaction annulée).
        if not Categorie.objects.filter(est_archivee=False, types_partenaire__contains=['fast_food']).exists():
            Categorie.objects.create(nom=f'QA Fast-food {uid}', slug=f'qa-fast-food-{uid}',
                                     types_partenaire=['fast_food'], types_articles=['plat', 'produit'])

        def partenaire(type_, nom):
            u = utilisateur('partenaire')
            return ProfilPartenaire.objects.create(
                user=u, plan=plan, nom_commerce=f'{nom} {uid}', type_partenaire=type_,
                statut='actif', est_visible=True, departement=dep)

        ff = partenaire('fast_food', 'Burger Express')
        resto = partenaire('restaurateur', 'Maquis')
        superadmin = utilisateur('admin', is_staff=True, is_superuser=True)
        client = utilisateur('client')

        print('=== 1. GABARIT ===')
        ok('gabarit fast_food', gabarits.gabarit_de(ff) == 'fast_food')
        ok('fast_food reste dans le moteur et la restauration', 'fast_food' in gabarits.TYPES_MOTEUR
           and 'fast_food' in services_resto.TYPES_RESTAURATION)
        ok('restaurateur : gabarit restaurant inchange', gabarits.gabarit_de(resto) == 'restaurant')
        m = req('get', '/api/v1/restaurants/meta/gabarits/').json().get('fast_food', {})
        ok('meta : Fast-food, Rubrique / Produit / Tailles, sans menus, options actives', (
            m.get('libelle'), m.get('libelle_section'), m.get('libelle_produit'), m.get('libelle_variantes'),
            m.get('menus_actifs'), m.get('options_actives')) == (
            'Fast-food', 'Rubrique', 'Produit', 'Tailles', False, True), m)
        ok('meta : champs est_combo (booleen), prix_reference (entier)', [
            (c['cle'], c['type']) for c in m.get('champs', [])] == [('est_combo', 'booleen'),
                                                                 ('prix_reference', 'entier')], m.get('champs'))
        ok('fiche moteur creee', ProfilRestaurant.objects.filter(partenaire=ff).exists())
        ok('detail public : gabarit fast_food', req('get', f'/api/v1/restaurants/{ff.id}/').json().get(
            'gabarit') == 'fast_food')
        ok('liste /restaurants/ : fast-food present', ff.id in {
            x['id'] for x in req('get', '/api/v1/restaurants/').json()['resultats']})

        print('=== 2. MENUS REFUSES ===')
        menu = {'nature': 'date', 'date': '2030-01-01', 'service': 'midi', 'heure_debut': '11:00',
                'heure_fin': '14:00', 'titre': 'Menu'}
        r = req('post', f'{MON}/menus/', ff.user, menu)
        ok('partenaire : menus -> 400 details.gabarit', details(r) == {'gabarit'}, contenu(r))
        r = req('post', f'/api/v1/restaurants/admin/{ff.id}/menus/', superadmin, menu)
        ok('admin : menus -> 400 details.gabarit', details(r) == {'gabarit'}, contenu(r))

        print('=== 3. CARTE : COMBOS, TEMPS DE PREPARATION ===')
        rubrique = req('post', f'{MON}/carte/sections/', ff.user, {'nom': 'Burgers'}).json()['id']

        def produit(corps, user=None, url=f'{MON}/carte/plats/'):
            return req('post', url, user or ff.user, {'section_menu': rubrique, **corps})

        r = produit({'nom': 'Burger', 'prix': 2500, 'temps_preparation_min': 10})
        ok('Burger -> 201, type plat, temps 10 min', r.status_code == 201 and r.json()['temps_preparation_min'] == 10
           and Article.objects.get(pk=r.json()['id']).type == 'plat', contenu(r))
        burger = r.json()['id']
        frites = produit({'nom': 'Frites', 'prix': 1000}).json()['id']
        coca = produit({'nom': 'Coca', 'prix': 500}).json()['id']
        r = produit({'nom': 'Menu Burger', 'prix': 3500, 'temps_preparation_min': 12,
                     'fiche_specifique': {'est_combo': True, 'prix_reference': 4000}})
        ok('Menu Burger (combo, au lieu de 4000) -> 201', r.status_code == 201
           and r.json()['fiche_specifique'] == {'est_combo': True, 'prix_reference': 4000}, contenu(r))
        menu_burger = r.json()['id']
        r = produit({'nom': 'Menu Wrap', 'prix': 3000, 'fiche_specifique': {'est_combo': True, 'prix_reference': 3000}})
        menu_wrap = r.json()['id']
        ok('fiche : prix_reference texte -> 400', details(produit({'nom': 'X', 'prix': 1, 'fiche_specifique': {
            'prix_reference': 'quatre mille'}})) == {'fiche_specifique.prix_reference'})
        ok('fiche : prix_reference negatif -> 400', details(produit({'nom': 'X', 'prix': 1, 'fiche_specifique': {
            'prix_reference': -5}})) == {'fiche_specifique.prix_reference'})
        ok('fiche : champ inconnu -> 400', details(produit({'nom': 'X', 'prix': 1, 'fiche_specifique': {
            'auteur': 'x'}})) == {'fiche_specifique.auteur'})
        ok('temps de preparation negatif -> 400', details(produit({'nom': 'X', 'prix': 1,
                                                                  'temps_preparation_min': -1}))
           == {'temps_preparation_min'})
        r = req('patch', f'{MON}/carte/plats/{burger}/', ff.user, {'temps_preparation_min': 8})
        ok('PATCH temps de preparation (partenaire) -> 8', r.status_code == 200
           and r.json()['temps_preparation_min'] == 8, contenu(r))
        r = req('patch', f'/api/v1/restaurants/admin/{ff.id}/carte/plats/{frites}/', superadmin,
                {'temps_preparation_min': 5, 'fiche_specifique': {'est_combo': False}})
        ok('PATCH admin : temps + fiche fast-food -> 200', r.status_code == 200
           and r.json()['temps_preparation_min'] == 5, contenu(r))
        r = req('patch', f'/api/v1/restaurants/admin/{ff.id}/carte/plats/{menu_wrap}/', superadmin,
                {'fiche_specifique': {'est_combo': True, 'prix_reference': 2500}})
        ok('PATCH admin : prix_reference du Menu Wrap -> 2500', r.status_code == 200
           and r.json()['fiche_specifique']['prix_reference'] == 2500, contenu(r))

        # Groupes du combo : réglés par le partenaire (obligatoire si min >= 1).
        def groupe(article, libelle, mini, maxi, options):
            r = req('post', f'{MON}/carte/groupes-options/', ff.user,
                    {'article': article, 'libelle': libelle, 'min_choix': mini, 'max_choix': maxi})
            ok(f'groupe {libelle} ({mini}..{maxi}) -> 201', r.status_code == 201, contenu(r))
            ids = []
            for nom, prix in options:
                o = req('post', f'{MON}/carte/options/', ff.user,
                        {'groupe': r.json()['id'], 'nom': nom, 'prix_supplement': prix})
                ids.append(o.json().get('id'))
            return ids

        o_frites, o_alloco = groupe(menu_burger, 'Accompagnement', 1, 1, [('Frites', 0), ('Alloco', 0)])
        o_coca, o_fanta = groupe(menu_burger, 'Boisson', 1, 1, [('Coca', 0), ('Fanta', 0)])
        o_ketchup, o_mayo = groupe(menu_burger, 'Sauces', 0, 2, [('Ketchup', 0), ('Mayo', 100)])
        r = req('post', f'{MON}/carte/variantes/', ff.user, {'article': coca, 'nom': 'Petit', 'prix': 500})
        r2 = req('post', f'{MON}/carte/variantes/', ff.user, {'article': coca, 'nom': 'Grand', 'prix': 800})
        ok('tailles du Coca -> 201', r.status_code == r2.status_code == 201, contenu(r2))
        coca_grand = r2.json()['id']

        print('=== 4. API APP : COMBO, TEMPS, CHAMPS ===')

        def produits(partenaire):
            d = req('get', f'/api/v1/restaurants/{partenaire.id}/produits/').json()
            return {x['id']: x for x in (d['results'] if isinstance(d, dict) and 'results' in d else d)}

        p = produits(ff)
        x = p[menu_burger]
        ok('Menu Burger : est_combo, prix_reference 4000 (> 3500), temps 12', (
            x['est_combo'], x['prix_reference'], x['temps_preparation_min']) == (True, 4000, 12), x)
        ok('Menu Burger : groupes Accompagnement / Boisson / Sauces avec min/max', [
            (g['libelle'], g['min_choix'], g['max_choix']) for g in x['groupes_options']] == [
            ('Accompagnement', 1, 1), ('Boisson', 1, 1), ('Sauces', 0, 2)], x['groupes_options'])
        ok('Menu Wrap : prix_reference 2500 <= prix 3000 -> null', p[menu_wrap]['prix_reference'] is None
           and p[menu_wrap]['est_combo'] is True, p[menu_wrap])
        ok('Burger : pas combo, prix_reference null, temps 8', (
            p[burger]['est_combo'], p[burger]['prix_reference'], p[burger]['temps_preparation_min']) == (False, None, 8))
        ok('Coca : tailles exposees, a partir de 500', [v['nom'] for v in p[coca]['variantes']] == ['Petit', 'Grand']
           and Decimal(str(p[coca]['prix_a_partir_de'])) == 500, p[coca])
        ok('champs fast-food sur chaque produit', all({'est_combo', 'prix_reference', 'populaire', 'rang_populaire',
                                                       'temps_preparation_min'} <= set(v) for v in p.values()))
        d = req('get', f'/api/v1/restaurants/{ff.id}/').json()
        plat = next(pl for s in d['carte'] for pl in s['plats'] if pl['id'] == menu_burger)
        ok('detail /restaurants/<id>/ (carte) : memes champs combo', (plat['est_combo'], plat['prix_reference'])
           == (True, 4000), plat)
        d = req('get', f'/api/v1/restaurants/produits/{menu_burger}/').json()
        ok('fiche produit : combo + temps', (d['est_combo'], d['prix_reference'], d['temps_preparation_min'])
           == (True, 4000, 12), d)
        sec_r = SectionMenu.objects.create(partenaire=resto, nom='Plats')
        Article.objects.create(partenaire=resto, categorie=Categorie.objects.filter(est_archivee=False).first(),
                               nom=f'Garba {uid}', slug=f'garba-ff-{uid}', type='plat', prix=1000,
                               temps_preparation_min=15, section_menu=sec_r)
        pr = list(produits(resto).values())
        ok('restaurant : temps de preparation expose, aucun champ fast-food', pr and pr[0]['temps_preparation_min'] == 15
           and not ({'est_combo', 'prix_reference', 'populaire', 'rang_populaire'} & set(pr[0])), pr[:1])

        print('=== 5. PANIER : COMBO ET PRODUITS SEULS ===')

        def ajouter(article, **kw):
            return req('post', PANIER, client, {'article': article, 'quantite': 1, **kw})

        r = ajouter(menu_burger)
        ok('combo sans accompagnement ni boisson -> 400 (groupes obligatoires)', r.status_code == 400
           and 'Accompagnement' in r.json().get('message', ''), contenu(r))
        r = ajouter(menu_burger, option_ids=[o_frites])
        ok('combo sans boisson -> 400', r.status_code == 400 and 'Boisson' in r.json().get('message', ''), contenu(r))
        r = ajouter(menu_burger, option_ids=[o_alloco, o_fanta])
        ligne = next((l for l in r.json().get('lignes', []) if l['article'] == menu_burger), None)
        ok('combo complet sans sauce (facultative) -> 201, 3500', r.status_code == 201 and ligne
           and Decimal(str(ligne['prix_ligne'])) == 3500, contenu(r))
        r = ajouter(menu_burger, option_ids=[o_frites, o_coca, o_ketchup, o_mayo])
        lignes = [l for l in r.json().get('lignes', []) if l['article'] == menu_burger]
        ok('combo + 2 sauces (Mayo +100) -> 201, 3600', r.status_code == 201
           and any(Decimal(str(l['prix_ligne'])) == 3600 for l in lignes), contenu(r))
        r = ajouter(burger)
        ok('Burger vendu seul -> 201', r.status_code == 201, contenu(r))
        ok('Coca sans taille -> 400 « Choisissez un format. »', ajouter(coca).json().get('message')
           == 'Choisissez un format.')
        r = ajouter(coca, variante_id=coca_grand)
        ok('Coca Grand -> 201, 800', r.status_code == 201 and any(
            l['article'] == coca and Decimal(str(l['prix_unitaire'])) == 800 for l in r.json()['lignes']), contenu(r))
        panier_id = r.json()['id']
        r = req('post', f'/api/v1/orders/paniers/{panier_id}/valider/', client, {'mode_livraison': 'emporter'})
        ok('fast-food sans horaires : validation -> 400 (regle d ouverture de la restauration)', r.status_code == 400
           and r.json()['message'] == services_resto.message_statut(services_resto.fiche_de(ff)), contenu(r))

        print('=== 6. LE PLUS COMMANDE ===')
        maintenant = timezone.now()
        compteur = [0]

        def commande(lignes, statut='livree', il_y_a_jours=0):
            compteur[0] += 1
            c = Commande.objects.create(numero=f'PFR-FF-{uid}-{compteur[0]}', user=client, partenaire=ff,
                                        statut=statut, sous_total=1000, total=1000)
            if il_y_a_jours:
                Commande.objects.filter(pk=c.pk).update(created_at=maintenant - timedelta(days=il_y_a_jours))
            for art, q in lignes:
                LigneCommande.objects.create(commande=c, article_id=art, nom_article='x', quantite=q,
                                             prix_unitaire=1000, prix_ligne=1000 * q)
            return c

        ancien = Article.objects.create(partenaire=ff, categorie=Article.objects.get(pk=burger).categorie,
                                        nom=f'Ancien {uid}', slug=f'ancien-ff-{uid}', type='plat', prix=100,
                                        est_actif=False)
        c_ok = commande([(burger, 3), (frites, 3), (coca, 2), (menu_burger, 1)])
        commande([(burger, 2), (menu_burger, 1)], statut='nouvelle')
        commande([(menu_burger, 10)], statut='annulee')           # exclue : annulée
        commande([(menu_wrap, 12)], statut='refusee')             # exclue : refusée
        commande([(menu_wrap, 15)], statut='expiree')             # exclue : expirée
        commande([(frites, 20), (menu_wrap, 30)], il_y_a_jours=40)  # exclue : plus de 30 jours
        commande([(ancien.id, 50)])                                 # exclue : article inactif
        ok('statuts non vendus exclus : annulee, refusee, expiree',
           set(services_resto.STATUTS_NON_VENDUS) == {'annulee', 'refusee', 'expiree'}
           and set(services_resto.STATUTS_NON_VENDUS) <= {v for v, _ in Commande.Statut.choices})
        ok('articles_populaires : Burger 1 (5), Frites 2 (3), Coca 3 (2) ; refusee / expiree ignorees',
           services_resto.articles_populaires(ff.id) == {burger: 1, frites: 2, coca: 3},
           services_resto.articles_populaires(ff.id))
        with CaptureQueriesContext(connection) as ctx:
            p = produits(ff)
        nb_top = len([q for q in ctx.captured_queries if 'orders_lignecommande' in q['sql']])
        ok('produits : populaire + rang (Burger 1, Frites 2, Coca 3, Menu Burger non)', (
            p[burger]['populaire'], p[burger]['rang_populaire'], p[frites]['rang_populaire'],
            p[coca]['rang_populaire'], p[menu_burger]['populaire'], p[menu_burger]['rang_populaire']) == (
            True, 1, 2, 3, False, None), [(v['nom'], v['rang_populaire']) for v in p.values()])
        ok(f'une seule requete de classement par reponse ({nb_top})', nb_top == 1)
        with CaptureQueriesContext(connection) as ctx:
            d = req('get', f'/api/v1/restaurants/{ff.id}/').json()
        rangs = {pl['id']: pl['rang_populaire'] for s in d['carte'] for pl in s['plats']}
        ok('detail (carte) : memes rangs, une requete', rangs.get(burger) == 1 and rangs.get(coca) == 3 and len(
            [q for q in ctx.captured_queries if 'orders_lignecommande' in q['sql']]) == 1, rangs)
        ok('fiche produit : rang', req('get', f'/api/v1/restaurants/produits/{frites}/').json()['rang_populaire'] == 2)

        print('=== 7. RESTAURATION : CANAL ET FILTRE ===')
        ok('commande fast-food = restauration (canal restaurant)', commande_est_restaurant(c_ok) is True)
        r = req('get', f'/api/v1/orders/admin/commandes/?restauration=1&partenaire={ff.id}&page_size=100', superadmin)
        d = r.json()
        ok('admin ?restauration=1 : commande fast-food presente', c_ok.id in {
            x['id'] for x in (d['results'] if isinstance(d, dict) and 'results' in d else d)}, contenu(r))

        raise Rollback()
except Rollback:
    print('\nRollback effectue (rien persiste).')
except Exception:
    traceback.print_exc(file=sys.stdout)
    KO.append('exception inattendue (trace ci-dessus)')

print(f'\n=== TOTAL : {NB_OK} OK / {len(KO)} KO ===')
if KO:
    print('KO :', *KO, sep='\n - ')
    raise SystemExit(1)
