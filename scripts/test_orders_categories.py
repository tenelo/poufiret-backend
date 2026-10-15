"""Tests : centre des commandes admin — regroupement par catégorie
(Commande.categorie, filtre ?categorie= sur commandes/, stats/, export/,
meta.categories ordonnées Restaurants d'abord puis Categorie.ordre).

Tout se déroule dans une transaction annulée (rien n'est persisté).

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_orders_categories.py
"""
import json

from django.db import transaction
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken

from apps.catalog.models import Article, Categorie
from apps.orders.models import Commande, LignePanier, Panier
from apps.orders.services import STATUTS_PAR_GROUPE
from apps.restaurants.services import TYPES_RESTAURATION
from apps.users.models import ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
# Limitation de débit DRF désactivée pour ce script : sinon tous les scripts partagent
# le compteur anonyme (60/min, client de test = 127.0.0.1) et la suite complète reçoit des 429.
from unittest import mock as _mock_debit
from rest_framework.views import APIView as _APIViewDebit
_mock_debit.patch.object(_APIViewDebit, 'get_throttles', return_value=[]).start()
BASE = '/api/v1/orders/admin'
NB = 0


class Rollback(Exception):
    pass


def ok(libelle, cond, detail=''):
    global NB
    print(('OK   ' if cond else 'FAIL '), libelle, '' if cond else detail)
    assert cond, f'{libelle} {detail}'
    NB += 1


def j(url, user, method='get', corps=None):
    kw = {'secure': True, 'HTTP_AUTHORIZATION': f'Bearer {AccessToken.for_user(user)}',
          'HTTP_HOST': HOST}
    fn = getattr(Client(), method)
    if corps is not None:
        return fn(url, json.dumps(corps), content_type='application/json', **kw)
    return fn(url, **kw)


def ids(r):
    d = r.json()
    return {x['id'] for x in (d['results'] if isinstance(d, dict) and 'results' in d else d)}


avant_c = Commande.objects.count()
try:
    with transaction.atomic():
        superadmin = User.objects.filter(is_superuser=True).first()
        client = User.objects.get(id=144)
        pa = ProfilPartenaire.objects.get(id=1)
        article = Article.objects.filter(partenaire=pa, est_actif=True).first()
        restaurants = Categorie.objects.filter(
            types_partenaire__contains=[TYPES_RESTAURATION[0]]).order_by('ordre').first()
        ok('une catégorie de restauration existe', restaurants is not None)

        cat_tot = Categorie.objects.create(nom='T Cat Tot', slug='t-cat-tot', icone='🧪', ordre=-10000)
        cat_tard = Categorie.objects.create(nom='T Cat Tard', slug='t-cat-tard', icone='🧫', ordre=10000)
        cat_vide = Categorie.objects.create(nom='T Cat Vide', slug='t-cat-vide', ordre=-20000)

        def cmd(categorie, statut='nouvelle', total=1000):
            return Commande.objects.create(
                numero=f'PFR-TCAT-{Commande.objects.count()+1:05d}', user=client, partenaire=pa,
                categorie=categorie, statut=statut, sous_total=total, total=total)

        c_resto = cmd(restaurants)
        c_tot1 = cmd(cat_tot, 'nouvelle', 2000)
        c_tot2 = cmd(cat_tot, 'livree', 3000)
        c_tard = cmd(cat_tard, 'acceptee')

        print('\n=== 1. CREATION : categorie reprise du panier ===')
        if article:
            panier = Panier.objects.create(user=client, partenaire=pa, categorie_id=article.categorie_id)
            LignePanier.objects.create(panier=panier, article=article, quantite=1, prix_unitaire=2500)
            r = j(f'/api/v1/orders/paniers/{panier.id}/valider/', client, 'post', {})
            ok('validation panier -> 201', r.status_code == 201, r.content)
            c_val = Commande.objects.get(id=r.json()['id'])
            ok('Commande.categorie = categorie du panier', c_val.categorie_id == article.categorie_id,
               (c_val.categorie_id, article.categorie_id))

        print('\n=== 2. FILTRE ?categorie= SUR commandes/ ===')
        r = j(f'{BASE}/commandes/?categorie={cat_tot.id}', superadmin)
        ok('?categorie= -> 200, uniquement la categorie', r.status_code == 200
           and ids(r) == {c_tot1.id, c_tot2.id}, r.content[:300])
        ok('compteurs_groupe respectent ?categorie=',
           r.json()['compteurs_groupe']['total'] == 2, r.json()['compteurs_groupe'])
        r = j(f'{BASE}/commandes/?categorie={cat_tot.id}&groupe=a_traiter', superadmin)
        ok('combinable avec ?groupe=', ids(r) == {c_tot1.id}, ids(r))
        r = j(f'{BASE}/commandes/?categorie={cat_tot.id}&statut=livree&partenaire={pa.id}', superadmin)
        ok('combinable avec ?statut= et ?partenaire=', ids(r) == {c_tot2.id}, ids(r))
        r = j(f'{BASE}/commandes/?categorie={cat_tot.id}&search={c_tot1.numero}', superadmin)
        ok('combinable avec ?search=', ids(r) == {c_tot1.id}, ids(r))
        r = j(f'{BASE}/commandes/?categorie={cat_vide.id}', superadmin)
        ok('categorie sans commande -> liste vide', r.status_code == 200 and ids(r) == set())
        r = j(f'{BASE}/commandes/?categorie=abc', superadmin)
        ok('?categorie=abc -> 400', r.status_code == 400, r.content)
        r = j(f'{BASE}/commandes/', superadmin)
        ok('sans filtre : compteurs inchanges (toutes categories)',
           r.json()['compteurs_groupe']['total'] == Commande.objects.count(), r.json()['compteurs_groupe'])

        print('\n=== 3. FILTRE ?categorie= SUR stats/ ===')
        r = j(f'{BASE}/stats/?categorie={cat_tot.id}', superadmin)
        k = r.json()['kpis']
        ok('stats ?categorie= -> 200, total=2, a_traiter=1, terminees=1, montant=5000',
           r.status_code == 200 and k['total'] == 2 and k['a_traiter'] == 1
           and k['terminees'] == 1 and float(k['montant_total']) == 5000, k)
        r = j(f'{BASE}/stats/?categorie={cat_tot.id}&partenaire={pa.id}', superadmin)
        ok('stats combinable avec ?partenaire=', r.json()['kpis']['total'] == 2)
        r = j(f'{BASE}/stats/?categorie=x', superadmin)
        ok('stats ?categorie=x -> 400', r.status_code == 400, r.content)

        print('\n=== 4. FILTRE ?categorie= SUR commandes/export/ ===')
        r = j(f'{BASE}/commandes/export/?categorie={cat_tot.id}', superadmin)
        csv = r.content.decode('utf-8-sig')
        ok('export -> 200, 2 lignes de la categorie',
           r.status_code == 200 and c_tot1.numero in csv and c_tot2.numero in csv
           and c_tard.numero not in csv and c_resto.numero not in csv, csv[:300])
        r = j(f'{BASE}/commandes/export/?categorie={cat_tot.id}&statut=livree', superadmin)
        csv = r.content.decode('utf-8-sig')
        ok('export combinable avec ?statut=', c_tot2.numero in csv and c_tot1.numero not in csv)
        r = j(f'{BASE}/commandes/export/?categorie=x', superadmin)
        ok('export ?categorie=x -> 400', r.status_code == 400, r.content)

        print('\n=== 5. META.categories ===')
        r = j(f'{BASE}/meta/', superadmin)
        d = r.json()
        cats = d['categories']
        ok('meta -> 200, cles existantes conservees', r.status_code == 200
           and {'statuts', 'groupes', 'modes_livraison', 'types_partenaire'} <= set(d), d.keys())
        ok('chaque entree a id/nom/icone/nb_commandes/nb_a_traiter',
           all(set(c) == {'id', 'nom', 'icone', 'nb_commandes', 'nb_a_traiter'} for c in cats), cats[:2])
        ok('uniquement les categories avec >= 1 commande',
           all(c['nb_commandes'] >= 1 for c in cats) and cat_vide.id not in {c['id'] for c in cats})
        ok('Restaurants en premier', cats[0]['id'] == restaurants.id, cats[:3])
        pos = {c['id']: i for i, c in enumerate(cats)}
        ok('puis ordre de la grille (T Cat Tot avant T Cat Tard)', pos[cat_tot.id] < pos[cat_tard.id])
        autres = [Categorie.objects.get(id=c['id']) for c in cats
                  if not set(TYPES_RESTAURATION) & set(Categorie.objects.get(id=c['id']).types_partenaire or [])]
        ok('non-restauration triees par (ordre, nom)',
           [(c.ordre, c.nom) for c in autres] == sorted((c.ordre, c.nom) for c in autres))
        e = next(c for c in cats if c['id'] == cat_tot.id)
        ok('T Cat Tot : nb_commandes=2, nb_a_traiter=1, icone', e['nb_commandes'] == 2
           and e['nb_a_traiter'] == 1 and e['icone'] == '🧪', e)
        e = next(c for c in cats if c['id'] == restaurants.id)
        ok('Restaurants : compteurs = base', e['nb_commandes'] == restaurants.commandes.count()
           and e['nb_a_traiter'] == restaurants.commandes.filter(
               statut__in=STATUTS_PAR_GROUPE['a_traiter']).count(), e)
        print('Extrait meta.categories :', json.dumps(cats[:4], ensure_ascii=False))

        print('\n=== 6. SUPPRESSION D\'UNE CATEGORIE : commandes conservees ===')
        cat_tard_id = cat_tard.id
        cat_tard.delete()
        c_tard.refresh_from_db()
        ok('commande conservee, categorie=None (SET_NULL)', c_tard.categorie_id is None)
        ok('ligne absente de meta.categories',
           cat_tard_id not in {c['id'] for c in j(f'{BASE}/meta/', superadmin).json()['categories']})

        raise Rollback('annulation volontaire')
except Rollback as e:
    print('\nRollback effectue :', e)

assert Commande.objects.count() == avant_c, 'commandes de test persistees !'
print('\nRien persiste.')
print('\nEtat reel : commandes sans categorie =',
      Commande.objects.filter(categorie__isnull=True).count(), '/', Commande.objects.count())
print(f'\n=== TOTAL : {NB} verifications reussies ===')
