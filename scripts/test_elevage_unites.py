"""Tests : unités de vente du gabarit « elevage ».

1. Porc au kilo : unite_prix kg, libellé « kg », affichage « f/kg »,
   quantité décimale au panier (quantite_kg).
2. Volailles, moutons, cabris, bœufs : prix par tête (« f/tête »), quantité entière.
3. Œufs : prix par plaquette (« f/plaquette »), variantes « Plaquette de 30 » /
   « Plaquette de 15 » avec leur propre prix.
4. Variantes de type à prix propre : poulet (Africain / Pondeuse / Chair),
   porc (Africain / De race) ; prix propre au kilo pour le porc.
+ méta du gabarit (choix tete / plaquette, unite / affichage), non-régression
  du prix_supplement (variante sans prix propre).

Données propres, rollback, limitation de débit désactivée, total OK / KO.
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_elevage_unites.py
"""
import json, uuid
from decimal import Decimal

from django.db import transaction
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken

from apps.catalog.models import Categorie, PartenaireCategorie, Variante
from apps.orders.models import LignePanier
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
# Limitation de débit DRF désactivée pour ce script : sinon tous les scripts partagent
# le compteur anonyme (60/min, client de test = 127.0.0.1) et la suite complète reçoit des 429.
from unittest import mock as _mock_debit
from rest_framework.views import APIView as _APIViewDebit
_mock_debit.patch.object(_APIViewDebit, 'get_throttles', return_value=[]).start()


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
        print('FAIL', libelle, detail)


def req(method, url, user=None, corps=None):
    kw = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    if corps is None:
        return getattr(Client(), method)(url, **kw)
    return getattr(Client(), method)(url, json.dumps(corps), content_type='application/json', **kw)


def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel


def utilisateur(role='client'):
    return User.objects.create(telephone=telephone_libre(), username=f't_elun_{uuid.uuid4().hex[:8]}',
                               role=role, est_verifie=True)


try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        eleveur = ProfilPartenaire.objects.create(
            user=utilisateur('partenaire'), plan=plan, nom_commerce=f'Ferme QA {uid}',
            type_partenaire='eleveur', statut='actif', est_visible=True)
        cat = Categorie.objects.create(nom=f'Ferme QA {uid}', slug=f'ferme-qa-{uid}', types_articles=['produit'])
        # Le signal peut déjà avoir rattaché l'éleveur à une catégorie déclarée : get_or_create.
        PartenaireCategorie.objects.filter(partenaire=eleveur).update(est_principale=False)
        PartenaireCategorie.objects.get_or_create(partenaire=eleveur, categorie=cat,
                                                  defaults={'est_principale': True})
        PartenaireCategorie.objects.filter(partenaire=eleveur, categorie=cat).update(est_principale=True)
        client = utilisateur()
        MON = '/api/v1/restaurants/mon-restaurant'
        PANIER = '/api/v1/orders/paniers/ajouter/'

        print('=== META DU GABARIT ===')
        d = req('get', '/api/v1/restaurants/meta/gabarits/').json()['elevage']
        champs = {c['cle']: c for c in d['champs']}
        unites = {c['valeur']: c for c in champs['unite_prix']['choix']}
        ok('unite_prix : piece, kg, tete, plaquette', list(unites) == ['piece', 'kg', 'tete', 'plaquette'], list(unites))
        ok('kg : unite « kg », affichage « f/kg »', (unites['kg']['unite'], unites['kg']['affichage']) == ('kg', 'f/kg'),
           unites['kg'])
        ok('tete : « tête » / « f/tête »', (unites['tete']['unite'], unites['tete']['affichage']) == ('tête', 'f/tête'))
        ok('plaquette : « plaquette » / « f/plaquette »',
           (unites['plaquette']['unite'], unites['plaquette']['affichage']) == ('plaquette', 'f/plaquette'))
        especes = [c['valeur'] for c in champs['espece']['choix']]
        ok('especes : volailles, mouton, cabri, boeuf, porc, oeuf', {'poulet', 'pintade', 'mouton', 'cabri', 'boeuf',
                                                                     'porc', 'oeuf'} <= set(especes), especes)
        ok('etat_vente « produit » (oeufs)', 'produit' in [c['valeur'] for c in champs['etat_vente']['choix']])

        section = req('post', f'{MON}/carte/sections/', eleveur.user, {'nom': 'Animaux', 'ordre': 1}).json()['id']

        def produit(nom, prix, espece, unite, etat='vivant'):
            r = req('post', f'{MON}/carte/plats/', eleveur.user, {
                'nom': nom, 'prix': prix, 'section_menu': section,
                'fiche_specifique': {'espece': espece, 'etat_vente': etat, 'unite_prix': unite}})
            ok(f'creation {nom} ({unite}) -> 201', r.status_code == 201, r.content[:300])
            return r.json()

        def variante(article, nom, prix=None, **kw):
            corps = {'article': article['id'], 'nom': nom, **kw}
            if prix is not None:
                corps['prix'] = prix
            r = req('post', f'{MON}/carte/variantes/', eleveur.user, corps)
            ok(f'variante {nom} -> 201', r.status_code == 201, r.content[:300])
            return r.json()

        print('=== CREATION ===')
        porc = produit('Porc', 2500, 'porc', 'kg', etat='decoupe')
        poulet = produit('Poulet', 3500, 'poulet', 'tete')
        pintade = produit('Pintade', 5000, 'pintade', 'tete')
        mouton = produit('Mouton', 60000, 'mouton', 'tete')
        cabri = produit('Cabri', 35000, 'cabri', 'tete')
        boeuf = produit('Boeuf', 400000, 'boeuf', 'tete')
        oeufs = produit('Oeufs', 1500, 'oeuf', 'plaquette', etat='produit')
        ok('unite inconnue -> 400', req('post', f'{MON}/carte/plats/', eleveur.user, {
            'nom': 'X', 'prix': 1, 'section_menu': section,
            'fiche_specifique': {'espece': 'porc', 'etat_vente': 'vivant', 'unite_prix': 'litre'}}).status_code == 400)

        p30 = variante(oeufs, 'Plaquette de 30', 2800, est_par_defaut=True)
        p15 = variante(oeufs, 'Plaquette de 15', 1500)
        africain = variante(poulet, 'Africain', 5000)
        pondeuse = variante(poulet, 'Pondeuse', 3000)
        chair = variante(poulet, 'Chair', 3500)
        porc_afr = variante(porc, 'Africain', 3000)
        porc_race = variante(porc, 'De race', 2200)
        gros = variante(mouton, 'Gros', prix_supplement=10000)  # sans prix propre : supplément
        ok('variante : prix propre enregistre', Variante.objects.get(pk=p30['id']).prix == 2800)
        ok('variante : prix negatif -> 400', req('post', f'{MON}/carte/variantes/', eleveur.user, {
            'article': oeufs['id'], 'nom': 'Neg', 'prix': -1}).status_code == 400)

        print('=== AFFICHAGE PUBLIC ===')
        carte = req('get', f'/api/v1/restaurants/{eleveur.id}/').json()['carte']
        plats = {p['id']: p for s in carte for p in s['plats']}
        attendu = {porc['id']: ('kg', 'kg', 'f/kg', 'kg'), poulet['id']: ('tete', 'tête', 'f/tête', 'piece'),
                   pintade['id']: ('tete', 'tête', 'f/tête', 'piece'), mouton['id']: ('tete', 'tête', 'f/tête', 'piece'),
                   cabri['id']: ('tete', 'tête', 'f/tête', 'piece'), boeuf['id']: ('tete', 'tête', 'f/tête', 'piece'),
                   oeufs['id']: ('plaquette', 'plaquette', 'f/plaquette', 'piece')}
        faux = {i: (plats.get(i, {}).get('unite_prix'), plats.get(i, {}).get('unite_prix_libelle'),
                    plats.get(i, {}).get('suffixe_prix'), plats.get(i, {}).get('unite_vente'))
                for i in attendu}
        ok('carte : unite_prix / libelle / suffixe / unite_vente par produit', faux == attendu, faux)
        v_oeufs = {v['nom']: v for v in plats[oeufs['id']]['variantes']}
        ok('oeufs : 2 plaquettes avec leur prix (prix + prix_effectif)',
           (Decimal(str(v_oeufs['Plaquette de 30']['prix_effectif'])), Decimal(str(v_oeufs['Plaquette de 15']['prix_effectif'])))
           == (2800, 1500) and Decimal(str(v_oeufs['Plaquette de 30']['prix'])) == 2800, v_oeufs)
        v_poulet = {v['nom']: Decimal(str(v['prix_effectif'])) for v in plats[poulet['id']]['variantes']}
        ok('poulet : Africain / Pondeuse / Chair a prix propre', v_poulet == {'Africain': 5000, 'Pondeuse': 3000,
                                                                              'Chair': 3500}, v_poulet)
        v_porc = {v['nom']: Decimal(str(v['prix_effectif'])) for v in plats[porc['id']]['variantes']}
        ok('porc : Africain / De race a prix propre (au kilo)', v_porc == {'Africain': 3000, 'De race': 2200}, v_porc)
        v_gros = plats[mouton['id']]['variantes'][0]
        ok('sans prix propre : prix null, prix_effectif = base + supplement',
           v_gros['prix'] is None and Decimal(str(v_gros['prix_effectif'])) == 70000, v_gros)
        fiche = req('get', f'/api/v1/restaurants/produits/{oeufs["id"]}/').json()
        ok('fiche produit : suffixe f/plaquette', fiche.get('suffixe_prix') == 'f/plaquette', fiche.get('suffixe_prix'))

        print('=== PANIER ===')

        def ajouter(article, quantite, variante_id=None):
            corps = {'article': article['id'], 'quantite': quantite}
            if variante_id:
                corps['variante_id'] = variante_id
            return req('post', PANIER, client, corps)

        def ligne_de(r, article, variante_id=None):
            return next((l for l in r.json().get('lignes', []) if l['article'] == article['id']
                         and l.get('variante_id') == variante_id), None)

        r = ajouter(porc, '1,5', porc_afr['id'])
        l = ligne_de(r, porc, porc_afr['id'])
        ok('porc Africain 1,5 kg -> 201, unite kg, prix 3000 x 1,5 = 4500', r.status_code == 201 and l
           and l['quantite'] == 1.5 and l['unite'] == 'kg' and Decimal(str(l['prix_ligne'])) == 4500, l or r.content)
        ok('porc : quantite_kg en base', LignePanier.objects.get(pk=l['id']).quantite_kg == Decimal('1.5'))
        ok('porc : 1,2 kg refuse (pas de 0,5)', ajouter(porc, 1.2).status_code == 400)
        r = ajouter(porc, 2)
        l = ligne_de(r, porc)
        ok('porc sans variante 2 kg : prix 2500 x 2', l and Decimal(str(l['prix_ligne'])) == 5000, l)
        for animal, prix in ((pintade, 5000), (mouton, 60000), (cabri, 35000), (boeuf, 400000)):
            r = ajouter(animal, 2)
            l = ligne_de(r, animal)
            ok(f'{animal["nom"]} : 2 tetes, entier, unite piece, prix {prix} x 2', r.status_code == 201 and l
               and l['quantite'] == 2 and isinstance(l['quantite'], int) and l['unite'] == 'piece'
               and Decimal(str(l['prix_ligne'])) == 2 * prix, l or r.content)
            ok(f'{animal["nom"]} : 1,5 tete refuse', ajouter(animal, 1.5).status_code == 400)
        r = ajouter(poulet, 3, pondeuse['id'])
        l = ligne_de(r, poulet, pondeuse['id'])
        ok('poulet Pondeuse x3 : prix propre 3000 x 3', l and Decimal(str(l['prix_ligne'])) == 9000, l)
        r = ajouter(poulet, 1, africain['id'])
        l = ligne_de(r, poulet, africain['id'])
        ok('poulet Africain x1 : 5000', l and Decimal(str(l['prix_ligne'])) == 5000, l)
        r = ajouter(oeufs, 2, p30['id'])
        l = ligne_de(r, oeufs, p30['id'])
        ok('oeufs Plaquette de 30 x2 : 2800 x 2', l and l['quantite'] == 2 and Decimal(str(l['prix_ligne'])) == 5600, l)
        r = ajouter(oeufs, 1, p15['id'])
        l = ligne_de(r, oeufs, p15['id'])
        ok('oeufs Plaquette de 15 x1 : 1500', l and Decimal(str(l['prix_ligne'])) == 1500, l)
        ok('oeufs : 1,5 plaquette refuse', ajouter(oeufs, 1.5, p15['id']).status_code == 400)
        r = ajouter(mouton, 1, gros['id'])
        l = ligne_de(r, mouton, gros['id'])
        ok('non-regression : variante a supplement (60000 + 10000)', l and Decimal(str(l['prix_ligne'])) == 70000, l)

        raise Rollback()
except Rollback:
    print('\nRollback effectue (rien persiste).')

print(f'\n=== TOTAL : {NB_OK} OK / {len(KO)} KO ===')
if KO:
    print('KO :', *KO, sep='\n - ')
    raise SystemExit(1)
