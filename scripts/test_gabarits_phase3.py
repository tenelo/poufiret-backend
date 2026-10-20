"""Tests : gabarits — phase 3 (lecture publique) : détail restaurant
(gabarit, carte complète ou sections + nb_produits selon pagination),
GET /restaurants/<id>/produits/ (pagination, section, recherche q sur nom,
description et fiche_specifique), GET /restaurants/produits/<id>/
(images principale en premier, autres_produits), requêtes constantes.

Données propres, rollback, limitation de débit désactivée.
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_gabarits_phase3.py
"""
import uuid
from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from rest_framework.throttling import SimpleRateThrottle
from apps.catalog.models import Article, ArticleImage, Categorie, GroupeOption, OptionGroupe, SectionMenu, Variante
from apps.geo.models import Departement
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

def get(url):
    return Client().get(url, secure=True, HTTP_HOST=HOST)

def requetes(url):
    with CaptureQueriesContext(connection) as ctx:
        r = get(url)
    return r, len(ctx.captured_queries)

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        dep = Departement.objects.order_by('id').first()
        cat = Categorie.objects.create(nom=f'QA Gab3 {uid}', slug=f'qa-gab3-{uid}',
            types_partenaire=['restaurateur', 'libraire', 'pharmacien'], types_articles=['plat', 'produit'])

        def partenaire(type_):
            u = User.objects.create(telephone=telephone_libre(), username=f't_gab3_{type_}_{uid}', role='partenaire')
            return ProfilPartenaire.objects.create(user=u, plan=plan, nom_commerce=f'{type_} {uid}',
                type_partenaire=type_, statut='actif', est_visible=True, departement=dep)

        libr, pharma, resto = partenaire('libraire'), partenaire('pharmacien'), partenaire('restaurateur')
        n = [0]

        def produit(p, nom, section, fiche=None, description='', actif=True, reserve=False, images=1, variantes=1,
                    type_='produit'):
            n[0] += 1
            a = Article.objects.create(partenaire=p, categorie=cat, nom=nom, slug=f'p{n[0]}-{uid}', type=type_,
                prix=1000 + n[0], description=description, section_menu=section, est_actif=actif,
                est_reserve_aux_menus=reserve, fiche_specifique=fiche or {}, ordre=n[0])
            for i in range(images):
                ArticleImage.objects.create(article=a, image=f'articles/{a.slug}-{i}.png', ordre=i,
                                            est_principale=(i == images - 1), est_active=True)
            for i in range(variantes):
                Variante.objects.create(article=a, nom=f'F{i}', ordre=i, stock=i)
            return a

        scol = SectionMenu.objects.create(partenaire=libr, nom='Scolaire', ordre=1)
        roman = SectionMenu.objects.create(partenaire=libr, nom='Romans', ordre=2)
        cachee = SectionMenu.objects.create(partenaire=libr, nom='Cachee', ordre=3, est_active=False)
        livres = [produit(libr, f'Maths {i}', scol, {'auteur': f'Auteur {i}', 'isbn': f'978-{i}'}, images=3)
                  for i in range(25)]
        l_roman = produit(libr, "L'enfant noir", roman, {'auteur': 'Camara Laye', 'isbn': '978-2266'},
                          description='Récit autobiographique')
        produit(libr, 'Inactif', scol, {'auteur': 'X'}, actif=False)
        produit(libr, 'Reserve', scol, {'auteur': 'X'}, reserve=True)
        produit(libr, 'Section cachee', cachee, {'auteur': 'X'})

        print('=== 1. DETAIL : GABARIT PAGINE (librairie) ===')
        r, nq = requetes(f'/api/v1/restaurants/{libr.id}/')
        ok('detail -> 200, gabarit librairie', r.status_code == 200 and r.json()['gabarit'] == 'librairie', r.content[:300])
        carte = r.json()['carte']
        ok('carte : sections actives sans produits, avec nb_produits', [(s['nom'], s['nb_produits']) for s in carte]
           == [('Scolaire', 25), ('Romans', 1)] and all('plats' not in s for s in carte), carte)

        print('=== 2. GET /<id>/produits/ ===')
        URL = f'/api/v1/restaurants/{libr.id}/produits/'
        r, nq1 = requetes(URL)
        d = r.json()
        ok('-> 200 {count,next,previous,results}', r.status_code == 200
           and set(d) == {'count', 'next', 'previous', 'results'}, d.keys() if r.status_code == 200 else r.content)
        ok('count = 26 visibles (inactif, reserve, section inactive exclus)', d['count'] == 26, d['count'])
        ok('page_size par defaut 20, next renseigne', len(d['results']) == 20 and d['next'] and d['previous'] is None)
        x = d['results'][0]
        ok('produit : fiche_specifique, commandable, section, variantes stock/est_epuise',
           {'fiche_specifique', 'commandable', 'section_id', 'section_nom', 'variantes', 'image'} <= set(x)
           and set(x['variantes'][0]) >= {'stock', 'est_epuise'}, x)
        ok('tri : section puis ordre', [p['nom'] for p in d['results'][:2]] == ['Maths 0', 'Maths 1'])
        r2 = get(URL + '?page=2')
        ok('page 2 : 6 resultats, previous', len(r2.json()['results']) == 6 and r2.json()['previous'])
        ok('page_size=5', len(get(URL + '?page_size=5').json()['results']) == 5)
        ok('section=Romans', [p['nom'] for p in get(f'{URL}?section={roman.id}').json()['results']] == ["L'enfant noir"])
        ok('section invalide -> 400', get(URL + '?section=abc').status_code == 400)
        for q, attendu in [('enfant', "L'enfant noir"), ('autobiograph', "L'enfant noir"),
                           ('camara', "L'enfant noir"), ('978-2266', "L'enfant noir")]:
            noms = [p['nom'] for p in get(f'{URL}?q={q}').json()['results']]
            ok(f'q={q} (nom/description/auteur/isbn)', noms == [attendu], noms)
        ok('q=Auteur 1 -> Maths 1 et 10-19', get(URL + '?q=Auteur 1').json()['count'] == 11)
        for i in range(10):
            produit(libr, f'Extra {i}', scol, {'auteur': 'Z'}, images=4, variantes=3)
        r, nq2 = requetes(URL)
        ok(f'pas de N+1 : requetes constantes ({nq1} -> {nq2})', nq1 == nq2 and nq1 <= 8, (nq1, nq2))
        coiffeur = partenaire('coiffeur')
        ok('partenaire hors moteur -> 404', get(f'/api/v1/restaurants/{coiffeur.id}/produits/').status_code == 404)
        print(f'   (requetes liste produits : {nq1})')

        print('=== 3. RECHERCHE SUR LES CHAMPS DES AUTRES GABARITS ===')
        rayon = SectionMenu.objects.create(partenaire=pharma, nom='Douleur', ordre=1)
        produit(pharma, 'Efferalgan', rayon, {'laboratoire': 'UPSA', 'dosage': '1 g', 'forme': 'comprime'})
        produit(pharma, 'Ibuprofene', rayon, {'laboratoire': 'Biogaran', 'dosage': '400 mg'})
        P = f'/api/v1/restaurants/{pharma.id}/produits/'
        ok('q=upsa (laboratoire)', [p['nom'] for p in get(P + '?q=upsa').json()['results']] == ['Efferalgan'])
        ok('q=400 mg (dosage)', [p['nom'] for p in get(P + '?q=400 mg').json()['results']] == ['Ibuprofene'])
        ok('q ne deborde pas sur un autre partenaire', get(P + '?q=Maths').json()['count'] == 0)

        print('=== 4. GET /produits/<id>/ ===')
        cible = livres[3]
        r, nq = requetes(f'/api/v1/restaurants/produits/{cible.id}/')
        ok('-> 200', r.status_code == 200, r.content)
        d = r.json()
        ok('images : principale en premier (3 images)', len(d['images']) == 3 and d['images'][0]['est_principale']
           and d['images'][0]['url'].endswith(f'{cible.slug}-2.png'), d['images'])
        ok('autres_produits : 6 au plus, meme section, sans lui-meme', len(d['autres_produits']) == 6
           and all(p['section_id'] == scol.id and p['id'] != cible.id for p in d['autres_produits']), d['autres_produits'])
        ok('partenaire resume + fiche_specifique', d['partenaire'] == {'id': libr.id, 'nom': libr.nom_commerce,
           'gabarit': 'librairie'} and d['fiche_specifique']['auteur'] == 'Auteur 3', d)
        ok(f'requetes constantes ({nq} <= 10)', nq <= 10, nq)
        print(f'   (requetes fiche produit : {nq})')
        d = get(f'/api/v1/restaurants/produits/{l_roman.id}/').json()
        ok('section a un seul produit -> autres_produits vide', d['autres_produits'] == [])
        inactif = Article.objects.get(nom='Inactif', partenaire=libr)
        ok('produit inactif -> 404', get(f'/api/v1/restaurants/produits/{inactif.id}/').status_code == 404)
        ok('produit inexistant -> 404', get('/api/v1/restaurants/produits/99999999/').status_code == 404)

        print('=== 5. RESTAURANT (non pagine) : carte complete enrichie, sans N+1 ===')
        entrees = SectionMenu.objects.create(partenaire=resto, nom='Plats', ordre=1)
        garba = produit(resto, 'Garba', entrees, type_='plat', variantes=2)
        g = GroupeOption.objects.create(article=garba, libelle='Piment', min_choix=0, max_choix=1)
        OptionGroupe.objects.create(groupe=g, nom='Fort', prix_supplement=0)
        r, nq1 = requetes(f'/api/v1/restaurants/{resto.id}/')
        d = r.json()
        ok('gabarit restaurant, carte avec plats', d['gabarit'] == 'restaurant' and d['carte'][0]['plats'], d['carte'])
        plat = d['carte'][0]['plats'][0]
        ok('plat : cles historiques conservees + fiche_specifique/commandable + images', {
            'id', 'nom', 'slug', 'description', 'prix', 'prix_promotion', 'image', 'images', 'est_disponible',
            'est_epuise', 'variantes', 'groupes_options', 'fiche_specifique', 'commandable'} == set(plat), set(plat))
        ok('variantes : stock / est_epuise', set(plat['variantes'][0]) == {
            'id', 'nom', 'prix_supplement', 'est_par_defaut', 'stock', 'est_epuise'}, plat['variantes'])
        ok('options toujours servies', plat['groupes_options'][0]['options'][0]['nom'] == 'Fort')
        for i in range(5):
            produit(resto, f'Plat {i}', entrees, type_='plat', images=2, variantes=2)
        r, nq2 = requetes(f'/api/v1/restaurants/{resto.id}/')
        ok(f'detail restaurant : requetes constantes ({nq1} -> {nq2})', nq1 == nq2, (nq1, nq2))
        ok('detail : de_garde false / jusqu_au null hors pharmacie', r.json()['de_garde'] is False
           and r.json()['de_garde_jusqu_au'] is None)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
