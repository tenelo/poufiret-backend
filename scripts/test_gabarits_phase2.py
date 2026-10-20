"""Tests : gabarits — phase 2 (données) : fiche_specifique validée selon
le gabarit sur les routes de gestion (400 details["fiche_specifique.<cle>"]),
variantes stock / est_epuise (gestion et public), pharmacie de garde
(fiche + public), médicament sur ordonnance (panier refusé, commandable
false), format épuisé / stock insuffisant refusés au panier.

Données propres, rollback, limitation de débit désactivée.
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_gabarits_phase2.py
"""
import json, uuid
from datetime import timedelta
from django.db import transaction
from django.test import Client
from django.utils import timezone
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.tokens import AccessToken
from apps.catalog.models import Article, Categorie, Variante
from apps.geo.models import Departement
from apps.orders.models import LignePanier
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

def details(r):
    return set(r.json().get('details', {})) if r.status_code == 400 else r.status_code

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        dep = Departement.objects.order_by('id').first()
        Categorie.objects.create(nom=f'QA Gab2 {uid}', slug=f'qa-gab2-{uid}',
            types_partenaire=['restaurateur', 'boulanger', 'pharmacien', 'boutique_mode', 'libraire'],
            types_articles=['plat', 'produit'])

        def partenaire(type_):
            return ProfilPartenaire.objects.create(user=utilisateur(f't_gab2_{type_}', 'partenaire'), plan=plan,
                nom_commerce=f'{type_} {uid}', type_partenaire=type_, statut='actif', est_visible=True, departement=dep)

        P = {t: partenaire(t) for t in ('restaurateur', 'boulanger', 'pharmacien', 'boutique_mode', 'libraire')}
        super_ = utilisateur('t_gab2_super', 'admin', staff=True, superuser=True)
        client_user = utilisateur('t_gab2_client')
        MON = '/api/v1/restaurants/mon-restaurant/carte/plats/'

        def creer(type_, corps, user=None):
            return req('post', MON, user or P[type_].user, {'prix': 1000, **corps})

        print('=== 1. FICHE_SPECIFIQUE : VALIDATION PAR GABARIT ===')
        r = creer('libraire', {'nom': 'Sans auteur'})
        ok('librairie : auteur obligatoire (creation sans fiche) -> 400', details(r) == {'fiche_specifique.auteur'},
           r.content)
        r = creer('libraire', {'nom': 'Auteur vide', 'fiche_specifique': {'auteur': '  '}})
        ok('librairie : auteur vide -> 400', details(r) == {'fiche_specifique.auteur'}, r.content)
        r = creer('libraire', {'nom': 'Mauvais', 'fiche_specifique': {
            'auteur': 'X', 'annee': '2001', 'niveau': 'maternelle', 'etat': 'neuf', 'inconnu': 1}})
        ok('librairie : entier, choix, cle inconnue -> 400 par cle',
           details(r) == {'fiche_specifique.annee', 'fiche_specifique.niveau', 'fiche_specifique.inconnu'}, r.content)
        r = creer('libraire', {'nom': 'Annee booleen', 'fiche_specifique': {'auteur': 'X', 'annee': True}})
        ok('entier : booleen refuse', details(r) == {'fiche_specifique.annee'}, r.content)
        r = creer('libraire', {'nom': 'Livre QA', 'fiche_specifique': {
            'auteur': ' Amadou Kourouma ', 'isbn': '978-2-02', 'annee': 1968, 'genre_livre': 'roman',
            'niveau': 'lycee', 'etat': 'occasion', 'editeur': None}})
        ok('librairie : fiche valide -> 201', r.status_code == 201, r.content)
        livre = r.json()
        ok('fiche normalisee (texte nettoye, null retire)', livre['fiche_specifique'] == {
            'auteur': 'Amadou Kourouma', 'isbn': '978-2-02', 'annee': 1968, 'genre_livre': 'roman',
            'niveau': 'lycee', 'etat': 'occasion'}, livre['fiche_specifique'])
        r = req('patch', f'{MON}{livre["id"]}/', P['libraire'].user, {'fiche_specifique': {'isbn': 'x'}})
        ok('PATCH fiche sans auteur -> 400 (remplacement complet)', details(r) == {'fiche_specifique.auteur'}, r.content)
        r = req('patch', f'{MON}{livre["id"]}/', P['libraire'].user, {'prix': 3500})
        ok('PATCH sans fiche_specifique -> 200, fiche conservee', r.status_code == 200
           and r.json()['fiche_specifique']['auteur'] == 'Amadou Kourouma', r.content)
        r = req('patch', f'/api/v1/restaurants/admin/{P["libraire"].id}/carte/plats/{livre["id"]}/', super_,
                {'fiche_specifique': {'auteur': 'Kourouma', 'langue': 'Français'}})
        ok('PATCH admin -> 200 (lecture/ecriture sur la route admin)', r.status_code == 200
           and r.json()['fiche_specifique'] == {'auteur': 'Kourouma', 'langue': 'Français'}, r.content)
        r = req('get', f'{MON}{livre["id"]}/', P['libraire'].user)
        ok('GET gestion : fiche_specifique lue', r.json()['fiche_specifique']['langue'] == 'Français')
        r = creer('boulanger', {'nom': 'Gateau', 'fiche_specifique': {'sur_commande': 'oui', 'delai_heures': -2}})
        ok('boulangerie : booleen et entier >= 0', details(r) == {'fiche_specifique.sur_commande',
                                                                 'fiche_specifique.delai_heures'}, r.content)
        r = creer('boutique_mode', {'nom': 'Basket', 'fiche_specifique': {'marque': 'Nike', 'genre': 'unisexe'}})
        ok('mode : genre hors choix -> 400', details(r) == {'fiche_specifique.genre'}, r.content)
        r = creer('restaurateur', {'nom': 'Garba', 'fiche_specifique': {'auteur': 'X'}})
        ok('restaurant : aucun champ specifique -> 400', details(r) == {'fiche_specifique.auteur'}, r.content)
        r = creer('restaurateur', {'nom': 'Attieke'})
        ok('restaurant : sans fiche -> 201, fiche {}', r.status_code == 201 and r.json()['fiche_specifique'] == {},
           r.content)
        r = creer('pharmacien', {'nom': 'X', 'fiche_specifique': {'dosage': 'a' * 301}})
        ok('texte trop long -> 400', details(r) == {'fiche_specifique.dosage'}, r.content)

        print('=== 2. VARIANTES : stock / est_epuise ===')
        basket = creer('boutique_mode', {'nom': 'Basket QA', 'fiche_specifique': {'marque': 'Nike', 'genre': 'mixte'}}).json()
        V = '/api/v1/restaurants/mon-restaurant/carte/variantes/'
        r = req('post', V, P['boutique_mode'].user, {'article': basket['id'], 'nom': '42', 'stock': 3})
        ok('POST variante avec stock -> 201', r.status_code == 201 and r.json()['stock'] == 3
           and r.json()['est_epuise'] is False, r.content)
        p42 = r.json()['id']
        p43 = req('post', V, P['boutique_mode'].user, {'article': basket['id'], 'nom': '43', 'stock': 0}).json()['id']
        p44 = req('post', V, P['boutique_mode'].user, {'article': basket['id'], 'nom': '44'}).json()
        ok('stock null = illimite par defaut', p44['stock'] is None)
        r = req('patch', f'{V}{p44["id"]}/', P['boutique_mode'].user, {'est_epuise': True})
        ok('PATCH est_epuise -> 200', r.status_code == 200 and r.json()['est_epuise'] is True, r.content)
        ok('stock negatif -> 400', req('post', V, P['boutique_mode'].user,
                                       {'article': basket['id'], 'nom': '45', 'stock': -1}).status_code == 400)
        r = req('get', f'{MON}{basket["id"]}/', P['boutique_mode'].user)
        ok('fiche gestion : variantes avec stock/est_epuise',
           {(v['nom'], v['stock'], v['est_epuise']) for v in r.json()['variantes']} == {
               ('42', 3, False), ('43', 0, False), ('44', None, True)}, r.json()['variantes'])

        print('=== 3. PHARMACIE DE GARDE ===')
        FICHE = '/api/v1/restaurants/mon-restaurant/fiche/'
        fin = timezone.now() + timedelta(hours=10)
        r = req('patch', FICHE, P['pharmacien'].user, {'de_garde_jusqu_au': fin.isoformat()})
        ok('PATCH de_garde_jusqu_au -> 200, de_garde true', r.status_code == 200 and r.json()['de_garde'] is True,
           r.content)
        d = req('get', f'/api/v1/restaurants/{P["pharmacien"].id}/').json()
        ok('public : de_garde true + de_garde_jusqu_au', d['de_garde'] is True and d['de_garde_jusqu_au'], d)
        req('patch', FICHE, P['pharmacien'].user, {'de_garde_jusqu_au': (timezone.now() - timedelta(hours=1)).isoformat()})
        ok('date passee -> de_garde false', req('get', f'/api/v1/restaurants/{P["pharmacien"].id}/').json()['de_garde'] is False)
        req('patch', FICHE, P['pharmacien'].user, {'de_garde_jusqu_au': None})
        d = req('get', f'/api/v1/restaurants/{P["pharmacien"].id}/').json()
        ok('null -> de_garde false, jusqu_au null', d['de_garde'] is False and d['de_garde_jusqu_au'] is None)

        print('=== 4. SUR ORDONNANCE ET PANIER ===')
        rayon = req('post', '/api/v1/restaurants/mon-restaurant/carte/sections/', P['pharmacien'].user,
                    {'nom': 'Antibiotiques'}).json()['id']
        amox = creer('pharmacien', {'nom': 'Amoxicilline', 'section_menu': rayon, 'fiche_specifique': {
            'forme': 'gelule', 'dosage': '500 mg', 'sur_ordonnance': True}}).json()
        doli = creer('pharmacien', {'nom': 'Doliprane', 'section_menu': rayon, 'fiche_specifique': {
            'forme': 'comprime', 'sur_ordonnance': False}}).json()
        PANIER = '/api/v1/orders/paniers/ajouter/'
        avant = LignePanier.objects.count()
        r = req('post', PANIER, client_user, {'article': amox['id'], 'quantite': 1})
        ok('sur ordonnance -> 400 message exact', r.status_code == 400
           and r.json()['message'] == 'Médicament sur ordonnance : contactez la pharmacie.', r.content)
        ok('aucune ligne creee', LignePanier.objects.count() == avant)
        r = req('post', PANIER, client_user, {'article': doli['id'], 'quantite': 2})
        ok('sans ordonnance -> 201', r.status_code == 201, r.content)
        r = req('get', f'/api/v1/restaurants/produits/{amox["id"]}/')
        ok('public : commandable false (ordonnance)', r.json()['commandable'] is False, r.content)
        ok('public : commandable true sinon', req('get', f'/api/v1/restaurants/produits/{doli["id"]}/').json()['commandable'] is True)
        req('post', f'{MON}{doli["id"]}/epuise/', P['pharmacien'].user, {'epuise': True})
        ok('produit epuise -> commandable false',
           req('get', f'/api/v1/restaurants/produits/{doli["id"]}/').json()['commandable'] is False)

        print('=== 5. VARIANTES AU PANIER ET EN PUBLIC ===')
        r = req('post', PANIER, client_user, {'article': basket['id'], 'variante_id': p43, 'quantite': 1})
        ok('variante a stock 0 -> 400', r.status_code == 400 and 'épuisé' in r.json()['message'], r.content)
        r = req('post', PANIER, client_user, {'article': basket['id'], 'variante_id': p44['id'], 'quantite': 1})
        ok('variante marquee epuisee -> 400', r.status_code == 400, r.content)
        r = req('post', PANIER, client_user, {'article': basket['id'], 'variante_id': p42, 'quantite': 4})
        ok('quantite > stock -> 400 stock insuffisant', r.status_code == 400 and 'Stock insuffisant' in r.json()['message'],
           r.content)
        r = req('post', PANIER, client_user, {'article': basket['id'], 'variante_id': p42, 'quantite': 3})
        ok('quantite <= stock -> 201', r.status_code == 201, r.content)
        r = req('get', f'/api/v1/restaurants/produits/{basket["id"]}/')
        ok('public : variantes stock + est_epuise (calcule)',
           {(v['nom'], v['stock'], v['est_epuise']) for v in r.json()['variantes']} == {
               ('42', 3, False), ('43', 0, True), ('44', None, True)}, r.json()['variantes'])

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
