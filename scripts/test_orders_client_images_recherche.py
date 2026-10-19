"""Tests : panier et commandes côté client — "image" des lignes (URL absolue
de l'image principale, ou null) sans requête par ligne ; recherche ?q= et
dates ?du=&au= sur GET /orders/commandes/, combinables avec ?statut=.

Autonome : crée ses partenaires, articles, images, client et commandes.
Affiche un extrait JSON réel d'une ligne de panier et d'une ligne de
commande. Transaction annulée (rien n'est persisté, aucune image écrite).

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_orders_client_images_recherche.py
"""
import json, uuid
from datetime import timedelta
from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken
from apps.catalog.models import Article, ArticleImage, Categorie
from apps.orders.models import Commande, LigneCommande
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

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

def req(method, url, user, corps=None):
    kw = {'secure': True, 'HTTP_HOST': HOST, 'HTTP_AUTHORIZATION': f'Bearer {AccessToken.for_user(user)}'}
    if corps is not None:
        return getattr(Client(), method)(url, json.dumps(corps), content_type='application/json', **kw)
    return getattr(Client(), method)(url, **kw)

def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel

def ids(r):
    return {c['id'] for c in r.json()}

def requetes(appel, motif):
    with CaptureQueriesContext(connection) as ctx:
        r = appel()
    return r, len(ctx.captured_queries), len([q for q in ctx.captured_queries if motif in q['sql']])

MEDIA = f'https://{HOST}/media/articles/'

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        categorie = Categorie.objects.create(nom=f'Epicerie QA {uid}', slug=f'epicerie-qa-{uid}')

        def partenaire(nom):
            u = User.objects.create(telephone=telephone_libre(), username=f't_oci_{uuid.uuid4().hex[:8]}',
                                    role='partenaire', est_verifie=True)
            return ProfilPartenaire.objects.create(user=u, plan=plan, nom_commerce=f'{nom} {uid}',
                                                   type_partenaire='commercant', statut='actif', est_visible=True)

        def article(pa, nom, *images):
            a = Article.objects.create(partenaire=pa, categorie=categorie, nom=f'{nom} {uid}',
                                       slug=f'oci-{uuid.uuid4().hex[:8]}', type='produit', prix=1000, est_actif=True)
            for nom_img, ordre, principale in images:
                ArticleImage.objects.create(article=a, image=f'articles/{nom_img}.png', ordre=ordre,
                                            est_principale=principale, est_active=True)
            return a

        boutique = partenaire('Boutique Soleil QA')
        librairie = partenaire('Librairie Lune QA')
        riz = article(boutique, 'Riz parfume', ('oci_riz_2', 2, False), ('oci_riz_p', 5, True))
        huile = article(boutique, 'Huile rouge', ('oci_huile_3', 3, False), ('oci_huile_1', 1, False))
        sel = article(boutique, 'Sel fin')  # sans image
        cahier = article(librairie, 'Cahier 200 pages', ('oci_cahier', 1, True))
        client = User.objects.create(telephone=telephone_libre(), username=f't_oci_client_{uid}',
                                     role='client', est_verifie=True)
        autre_client = User.objects.create(telephone=telephone_libre(), username=f't_oci_autre_{uid}',
                                           role='client', est_verifie=True)

        print('=== 1. PANIER : image des lignes ===')
        r = req('post', '/api/v1/orders/paniers/ajouter/', client, {'article': riz.id, 'quantite': 2})
        ok('ajout riz -> 201, reponse panier avec image', r.status_code == 201
           and r.json()['lignes'][0]['image'] == MEDIA + 'oci_riz_p.png', r.content)
        r, total_1, images_1 = requetes(lambda: req('get', '/api/v1/orders/paniers/', client),
                                        'catalog_articleimage')
        panier = next(p for p in r.json() if p['partenaire'] == boutique.id)
        ligne = panier['lignes'][0]
        print('Extrait JSON reel, ligne de panier :')
        print(json.dumps(ligne, ensure_ascii=False, indent=2))
        ok('ligne panier : image principale, URL absolue', ligne['image'] == MEDIA + 'oci_riz_p.png', ligne)
        for a in (huile, sel):
            req('post', '/api/v1/orders/paniers/ajouter/', client, {'article': a.id, 'quantite': 1})
        r, total_3, images_3 = requetes(lambda: req('get', '/api/v1/orders/paniers/', client),
                                        'catalog_articleimage')
        lignes = {l['article']: l for l in next(p for p in r.json() if p['partenaire'] == boutique.id)['lignes']}
        ok('sans principale : 1re image active par ordre', lignes[huile.id]['image'] == MEDIA + 'oci_huile_1.png',
           lignes[huile.id])
        ok('article sans image -> null', lignes[sel.id]['image'] is None)
        ok('panier : 1 requete images quel que soit le nombre de lignes (prefetch)',
           images_1 == images_3 == 1, (images_1, images_3))
        ok('panier : nombre total de requetes constant (1 vs 3 lignes)', total_1 == total_3, (total_1, total_3))
        ligne_sel = lignes[sel.id]['id']
        r = req('patch', f'/api/v1/orders/lignes/{ligne_sel}/', client, {'quantite': 3})
        ok('PATCH ligne -> 200, images presentes', r.status_code == 200
           and all('image' in l for l in r.json()['lignes']), r.content)

        print('=== 2. COMMANDE : image des lignes ===')
        r = req('post', f'/api/v1/orders/paniers/{panier["id"]}/valider/', client, {})
        ok('validation -> 201, lignes avec image', r.status_code == 201
           and {l['image'] for l in r.json()['lignes']} == {MEDIA + 'oci_riz_p.png', MEDIA + 'oci_huile_1.png', None},
           r.content)
        c1 = Commande.objects.get(id=r.json()['id'])
        r2 = req('post', '/api/v1/orders/paniers/ajouter/', client, {'article': cahier.id, 'quantite': 1})
        r2 = req('post', f'/api/v1/orders/paniers/{r2.json()["id"]}/valider/', client, {})
        ok('2e commande (librairie) -> 201', r2.status_code == 201, r2.content)
        c2 = Commande.objects.get(id=r2.json()['id'])
        r = req('get', f'/api/v1/orders/commandes/{c1.id}/', client)
        ligne_cmd = next(l for l in r.json()['lignes'] if l['article'] == riz.id)
        print('Extrait JSON reel, ligne de commande :')
        print(json.dumps(ligne_cmd, ensure_ascii=False, indent=2))
        ok('detail : ligne de commande avec image', ligne_cmd['image'] == MEDIA + 'oci_riz_p.png', ligne_cmd)
        r, total_a, images_a = requetes(lambda: req('get', '/api/v1/orders/commandes/', client),
                                        'catalog_articleimage')
        ok('liste : 1 requete images pour toutes les commandes et lignes', images_a == 1, images_a)
        r3 = req('post', '/api/v1/orders/paniers/ajouter/', client, {'article': huile.id, 'quantite': 4})
        r3 = req('post', f'/api/v1/orders/paniers/{r3.json()["id"]}/valider/', client, {})
        c3 = Commande.objects.get(id=r3.json()['id'])
        r, total_b, images_b = requetes(lambda: req('get', '/api/v1/orders/commandes/', client),
                                        'catalog_articleimage')
        ok('liste : requetes constantes avec une commande de plus', total_a == total_b and images_b == 1,
           (total_a, total_b))
        LigneCommande.objects.filter(commande=c3).update(article=None)  # article supprime apres commande
        r = req('get', f'/api/v1/orders/commandes/{c3.id}/', client)
        ok('article supprime apres commande -> image null, nom conserve',
           r.json()['lignes'][0]['image'] is None and r.json()['lignes'][0]['nom_article'], r.json()['lignes'])
        r = req('get', '/api/v1/orders/commandes/partenaire/', boutique.user)
        ok('vue partenaire : lignes avec image (meme serializer)',
           r.status_code == 200 and all('image' in l for c in r.json() for l in c['lignes']))

        print('=== 3. RECHERCHE ?q= ===')
        URL = '/api/v1/orders/commandes/'
        ok('sans filtre : mes 3 commandes', ids(req('get', URL, client)) == {c1.id, c2.id, c3.id})
        ok('q = reference', ids(req('get', f'{URL}?q={c2.numero}', client)) == {c2.id})
        ok('q = reference partielle (insensible casse)',
           c1.id in ids(req('get', f'{URL}?q={c1.numero[-5:].lower()}', client)))
        ok('q = nom de produit (snapshot)', ids(req('get', f'{URL}?q=riz PARFUME', client)) == {c1.id})
        ok('q = produit present dans 2 commandes -> pas de doublon',
           [c['id'] for c in req('get', f'{URL}?q=huile', client).json()].count(c1.id) == 1
           and ids(req('get', f'{URL}?q=huile', client)) == {c1.id, c3.id})
        ok('q = nom du partenaire', ids(req('get', f'{URL}?q=librairie lune', client)) == {c2.id})
        ok('q sans correspondance -> []', req('get', f'{URL}?q=introuvable-{uid}', client).json() == [])
        ok('q ne sort pas des commandes du client', req('get', f'{URL}?q={c1.numero}', autre_client).json() == [])

        print('=== 4. DATES ?du=&au= ===')
        aujourdhui = timezone.localdate()
        Commande.objects.filter(pk=c2.pk).update(created_at=timezone.now() - timedelta(days=10))
        il_y_a_10 = (aujourdhui - timedelta(days=10)).isoformat()
        il_y_a_5 = (aujourdhui - timedelta(days=5)).isoformat()
        ok('du = aujourd hui', ids(req('get', f'{URL}?du={aujourdhui}', client)) == {c1.id, c3.id})
        ok('au = il y a 5 j', ids(req('get', f'{URL}?au={il_y_a_5}', client)) == {c2.id})
        ok('du + au (bornes incluses)', ids(req('get', f'{URL}?du={il_y_a_10}&au={il_y_a_10}', client)) == {c2.id})
        ok('date mal formee ignoree', ids(req('get', f'{URL}?du=hier&au=2026-13-45', client)) == {c1.id, c2.id, c3.id})

        print('=== 5. COMBINAISONS ===')
        ok('q + du', ids(req('get', f'{URL}?q=huile&du={aujourdhui}', client)) == {c1.id, c3.id})
        ok('q + au exclut', req('get', f'{URL}?q=huile&au={il_y_a_5}', client).json() == [])
        Commande.objects.filter(pk=c3.pk).update(statut='annulee')
        ok('q + statut', ids(req('get', f'{URL}?q=huile&statut=annulee', client)) == {c3.id})
        ok('statut + du + au', ids(req('get', f'{URL}?statut=nouvelle&du={il_y_a_10}&au={aujourdhui}', client))
           == {c1.id, c2.id})

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
