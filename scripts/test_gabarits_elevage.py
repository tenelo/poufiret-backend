"""Tests : métier « Éleveur » et gabarit « elevage » (vente à la ferme).
Type et correspondance, aucun rattachement automatique de catégorie,
moteur (fiche, sections, produits, variantes avec stock, mon-restaurant/
et admin/<id>/, liste admin), meta.elevage, validation de fiche_specifique,
quantité au panier (kilo par pas de 0,5 / pièce entière), prix de ligne
et commande, non-régression de la quantité des autres gabarits.

Données propres, rollback, limitation de débit désactivée.
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_gabarits_elevage.py
"""
import json, uuid
from decimal import Decimal
from django.db import transaction
from django.test import Client
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.tokens import AccessToken
from apps.catalog.correspondances import categories_correspondantes
from apps.catalog.models import Categorie, PartenaireCategorie
from apps.geo.models import Departement
from apps.orders.models import Commande, LignePanier
from apps.restaurants import gabarits, services
from apps.restaurants.models import ProfilRestaurant
from apps.users.models import HoraireOuverture, PlanAbonnement, ProfilPartenaire, User

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

def details(r):
    return set(r.json().get('details', {})) if r.status_code == 400 else r.status_code

FICHE_KG = {'espece': 'porc', 'etat_vente': 'decoupe', 'unite_prix': 'kg', 'poids_moyen_kg': '1,8 à 2,2',
            'quantite_disponible': 40, 'commande_avance_jours': 0, 'livraison_possible': True}

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        dep = Departement.objects.order_by('id').first()
        T = ProfilPartenaire.TypePartenaire
        declarees = set(categories_correspondantes('eleveur').values_list('id', flat=True))

        def partenaire(type_, nom):
            p = ProfilPartenaire.objects.create(user=utilisateur(f't_elev_{type_}', 'partenaire'), plan=plan,
                nom_commerce=f'{nom} {uid}', type_partenaire=type_, statut='actif', est_visible=True,
                departement=dep)
            # Ouvert tous les jours, toute la journée (validation de commande).
            for j in range(7):
                HoraireOuverture.objects.create(partenaire=p, jour_semaine=j, ouvert=True,
                    heure_ouverture='00:00', heure_fermeture='23:59')
            return p

        eleveur = partenaire('eleveur', 'Ferme Koné')
        resto = partenaire('restaurateur', 'Maquis')
        super_ = utilisateur('t_elev_super', 'admin', staff=True, superuser=True)
        client_user = utilisateur('t_elev_client')

        print('=== 1. TYPE ET GABARIT ===')
        ok('type eleveur « Éleveur / Vente à la ferme »', T('eleveur').label == 'Éleveur / Vente à la ferme')
        ok('eleveur -> elevage', gabarits.gabarit_de_type('eleveur') == 'elevage')
        ok('eleveur dans les types a catalogue, pas dans la restauration',
           'eleveur' in services.TYPES_MOTEUR and 'eleveur' not in services.TYPES_RESTAURATION)
        ok('aucun rattachement automatique de categorie (seulement celles qui declarent eleveur)',
           set(PartenaireCategorie.objects.filter(partenaire=eleveur).values_list('categorie_id', flat=True))
           == declarees, declarees)
        ok('fiche moteur creee', ProfilRestaurant.objects.filter(partenaire=eleveur).exists())
        # Rattachement à la main par l'admin (comme « Porc de ferme »).
        porc_ferme = Categorie.objects.create(nom=f'Porc de ferme {uid}', slug=f'porc-ferme-{uid}',
                                              types_articles=['produit'])
        PartenaireCategorie.objects.create(partenaire=eleveur, categorie=porc_ferme, est_principale=True)
        r = req('get', f'/api/v1/auth/partenaires/{eleveur.id}/')
        ok('vitrine : gabarit elevage', r.status_code == 200 and r.json()['gabarit'] == 'elevage', r.content)
        r = req('get', f'/api/v1/catalogue/categories/{porc_ferme.slug}/partenaires/')
        ok('annuaire : carte avec gabarit elevage',
           any(x['id'] == eleveur.id and x['gabarit'] == 'elevage' for x in r.json()), r.content)

        print('=== 2. META ===')
        d = req('get', '/api/v1/restaurants/meta/gabarits/').json()['elevage']
        ok('libelles', (d['libelle'], d['libelle_section'], d['libelle_produit'], d['libelle_variantes']) ==
           ('Élevage', 'Catégorie', 'Animal / Produit', 'Formats'), d)
        ok('menus/options/pagination desactives', (d['menus_actifs'], d['options_actives'],
                                                   d['pagination_publique']) == (False, False, False), d)
        ok('champs, types et obligation', [(c['cle'], c['type'], c['obligatoire']) for c in d['champs']] == [
            ('espece', 'choix', True), ('etat_vente', 'choix', True), ('unite_prix', 'choix', True),
            ('poids_moyen_kg', 'texte', False), ('age', 'texte', False), ('quantite_disponible', 'entier', False),
            ('commande_avance_jours', 'entier', False), ('livraison_possible', 'booleen', False)], d['champs'])
        choix = {c['cle']: [x['valeur'] for x in c['choix']] for c in d['champs']}
        ok('choix espece / etat_vente / unite_prix', choix['espece'] == [
            'porc', 'poulet', 'pintade', 'boeuf', 'mouton', 'chevre', 'lapin', 'autre']
           and choix['etat_vente'] == ['vivant', 'abattu_entier', 'decoupe'] and choix['unite_prix'] == ['piece', 'kg'])

        print('=== 3. MOTEUR : GESTION ===')
        MON = '/api/v1/restaurants/mon-restaurant'
        ok('mon-restaurant/fiche -> 200, gabarit elevage',
           req('get', f'{MON}/fiche/', eleveur.user).json().get('gabarit') == 'elevage')
        ok('admin/<id>/fiche -> 200', req('get', f'/api/v1/restaurants/admin/{eleveur.id}/fiche/', super_).status_code == 200)
        r = req('get', '/api/v1/restaurants/admin/?gabarit=elevage', super_)
        ok('liste admin des etablissements ?gabarit=elevage', [x['id'] for x in r.json()['resultats']
                                                              if x['id'] == eleveur.id] == [eleveur.id], r.content)
        section = req('post', f'{MON}/carte/sections/', eleveur.user, {'nom': 'Porcs', 'ordre': 1}).json()['id']
        menu = {'nature': 'date', 'date': '2030-01-01', 'service': 'midi', 'heure_debut': '11:00', 'heure_fin': '14:00'}
        ok('menus refuses (gabarit)', details(req('post', f'{MON}/menus/', eleveur.user, menu)) == {'gabarit'})

        print('=== 4. FICHE_SPECIFIQUE ===')
        def produit(corps):
            return req('post', f'{MON}/carte/plats/', eleveur.user, {'prix': 2500, 'section_menu': section, **corps})
        ok('sans fiche -> 400 sur les 3 obligatoires', details(produit({'nom': 'X'})) == {
            'fiche_specifique.espece', 'fiche_specifique.etat_vente', 'fiche_specifique.unite_prix'})
        r = produit({'nom': 'X', 'fiche_specifique': {**FICHE_KG, 'espece': 'canard', 'unite_prix': 'litre',
                     'quantite_disponible': '40', 'livraison_possible': 'oui', 'poids': 2}})
        ok('choix, entier, booleen, cle inconnue -> 400 par cle', details(r) == {
            'fiche_specifique.espece', 'fiche_specifique.unite_prix', 'fiche_specifique.quantite_disponible',
            'fiche_specifique.livraison_possible', 'fiche_specifique.poids'}, r.content)
        ok('commande_avance_jours negatif -> 400', details(produit({'nom': 'X', 'fiche_specifique': {
            **FICHE_KG, 'commande_avance_jours': -1}})) == {'fiche_specifique.commande_avance_jours'})
        r = produit({'nom': 'Porc découpé', 'prix': 2333, 'fiche_specifique': FICHE_KG})
        ok('porc au kilo -> 201 (categorie cochee a la main par defaut)', r.status_code == 201
           and r.json()['categorie'] == porc_ferme.id, r.content)
        porc = r.json()
        ok('fiche enregistree', porc['fiche_specifique'] == FICHE_KG, porc['fiche_specifique'])
        r = produit({'nom': 'Poulet bicyclette', 'prix': 4000, 'fiche_specifique': {
            'espece': 'poulet', 'etat_vente': 'vivant', 'unite_prix': 'piece', 'age': '45 jours'}})
        ok('poulet a la piece -> 201', r.status_code == 201, r.content)
        poulet = r.json()
        r = req('post', f'{MON}/carte/variantes/', eleveur.user, {'article': poulet['id'], 'nom': 'Gros', 'stock': 3,
                                                                  'prix_supplement': 1000})
        ok('variante avec stock -> 201', r.status_code == 201 and r.json()['stock'] == 3, r.content)
        gros = r.json()['id']
        r = req('post', f'{MON}/carte/groupes-options/', eleveur.user,
                {'article': poulet['id'], 'libelle': 'Plumage', 'min_choix': 0, 'max_choix': 1})
        ok('options refusees (gabarit)', details(r) == {'gabarit'}, r.content)
        d = req('get', f'/api/v1/restaurants/{eleveur.id}/').json()
        ok('detail public : gabarit elevage, carte complete (non paginee)', d['gabarit'] == 'elevage'
           and {p['nom'] for p in d['carte'][0]['plats']} == {'Porc découpé', 'Poulet bicyclette'}, d['carte'])

        print('=== 5. PANIER : QUANTITE AU KILO ===')
        PANIER = '/api/v1/orders/paniers/ajouter/'
        def ajouter(article, quantite, **kw):
            return req('post', PANIER, client_user, {'article': article, 'quantite': quantite, **kw})
        for q in (0, 0.3, 1.25, -1, 'abc', None):
            r = ajouter(porc['id'], q)
            ok(f'kg : quantite {q!r} -> 400', r.status_code == 400, r.content)
        r = ajouter(porc['id'], 1.5)
        ok('kg : 1,5 -> 201', r.status_code == 201, r.content)
        ligne = next(l for l in r.json()['lignes'] if l['article'] == porc['id'])
        ok('ligne : quantite 1.5, unite kg, prix_ligne = 2333 x 1,5 arrondi (3500)', ligne['quantite'] == 1.5
           and ligne['unite'] == 'kg' and Decimal(str(ligne['prix_ligne'])) == 3500, ligne)
        lp = LignePanier.objects.get(pk=ligne['id'])
        ok('stockage : quantite 1, quantite_kg 1.5', lp.quantite == 1 and lp.quantite_kg == Decimal('1.5'))
        r = req('patch', f'/api/v1/orders/lignes/{ligne["id"]}/', client_user, {'quantite': '2,5'})
        ok('PATCH kg « 2,5 » -> 200, prix 5833 (5832,5 arrondi)', r.status_code == 200 and any(
            l['quantite'] == 2.5 and Decimal(str(l['prix_ligne'])) == 5833 for l in r.json()['lignes']), r.content)
        ok('PATCH kg 2,3 -> 400', req('patch', f'/api/v1/orders/lignes/{ligne["id"]}/', client_user,
                                       {'quantite': 2.3}).status_code == 400)
        ok('kg : 0,5 (minimum) -> 201', ajouter(porc['id'], '0.5').status_code == 201)

        print('=== 6. PANIER : QUANTITE A LA PIECE ===')
        for q in (1.5, 0, '2.5'):
            ok(f'piece : quantite {q!r} -> 400', ajouter(poulet['id'], q).status_code == 400)
        r = ajouter(poulet['id'], 2)
        ligne_p = next(l for l in r.json()['lignes'] if l['article'] == poulet['id'])
        ok('piece : 2 -> 201, quantite entiere, unite piece, prix 8000', r.status_code == 201
           and ligne_p['quantite'] == 2 and isinstance(ligne_p['quantite'], int) and ligne_p['unite'] == 'piece'
           and Decimal(str(ligne_p['prix_ligne'])) == 8000, ligne_p)
        ok('piece « 2.0 » accepte (entier)', ajouter(poulet['id'], '2.0').status_code == 201)
        ok('variante : 4 > stock 3 -> 400', ajouter(poulet['id'], 4, variante_id=gros).status_code == 400)
        r = ajouter(poulet['id'], 3, variante_id=gros)
        ok('variante : 3 -> 201, prix (4000+1000) x 3', r.status_code == 201 and any(
            l['variante_id'] == gros and Decimal(str(l['prix_ligne'])) == 15000 for l in r.json()['lignes']), r.content)

        print('=== 7. COMMANDE ===')
        panier = r.json()
        total_panier = Decimal(str(panier['total']))
        ok('total panier = somme des lignes', total_panier == sum(Decimal(str(l['prix_ligne'])) for l in panier['lignes']),
           panier['total'])
        r = req('post', f'/api/v1/orders/paniers/{panier["id"]}/valider/', client_user, {'mode_livraison': 'emporter'})
        ok('validation -> 201', r.status_code == 201, r.content)
        cmd = r.json()
        kg = next(l for l in cmd['lignes'] if l['quantite'] == 2.5)
        ok('ligne de commande : 2.5 kg, prix 5833', kg['unite'] == 'kg' and Decimal(str(kg['prix_ligne'])) == 5833, kg)
        ok('sous_total commande = total panier', Decimal(str(cmd['sous_total'])) == total_panier,
           (cmd['sous_total'], total_panier))
        c = Commande.objects.get(pk=cmd['id'])
        ok('snapshot quantite_kg en base', c.lignes.filter(quantite_kg=Decimal('2.5')).exists())
        r = req('get', f'/api/v1/orders/admin/commandes/{cmd["id"]}/', super_)
        ok('detail admin : quantite 2.5 + unite', r.status_code == 200 and any(
            l['quantite'] == 2.5 and l['unite'] == 'kg' for l in r.json()['lignes']), r.content)

        print('=== 8. NON-REGRESSION : QUANTITE DES AUTRES GABARITS ===')
        plat = req('post', f'{MON}/carte/plats/', resto.user, {'nom': 'Garba', 'prix': 1000}).json()
        ok('restaurant : 1,5 refuse (entier attendu)', ajouter(plat['id'], 1.5).status_code == 400)
        r = ajouter(plat['id'], 3)
        l = next(l for l in r.json()['lignes'] if l['article'] == plat['id'])
        ok('restaurant : 3 -> 201, quantite 3 (int), prix 3000', r.status_code == 201 and l['quantite'] == 3
           and l['unite'] == 'piece' and Decimal(str(l['prix_ligne'])) == 3000, l)
        ok('quantite absente -> 1 par defaut', ajouter(plat['id'], None).status_code == 400
           and req('post', PANIER, client_user, {'article': plat['id']}).status_code == 201)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
