"""Tests : bouton WhatsApp externe du partenaire (whatsapp_externe_actif).

Couvre : défaut null ; activé + numéro → numéro normalisé (international sans
« + » ni espaces) ; activé sans numéro → 400 sur « whatsapp » ; présent dans
la vitrine, l'annuaire, la fiche article, les restaurants (liste, détail,
fiche produit) et les locations (liste et détail véhicules / logements,
établissement) ; modifiable par le partenaire et par l'admin.

Autonome : données propres, limitation de débit désactivée, transaction
annulée. Affiche un total OK / KO.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_whatsapp_externe.py
"""
import json, uuid

from django.db import transaction
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import PermissionsAdmin
from apps.catalog.models import Article, Categorie, Logement, PartenaireCategorie, Vehicule
from apps.users.models import PlanAbonnement, ProfilPartenaire, User
from apps.users.whatsapp import normaliser_whatsapp

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
    fn = getattr(Client(), method)
    if corps is not None:
        return fn(url, json.dumps(corps), content_type='application/json', **kw)
    return fn(url, **kw)


def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel


ATTENDU = '2250707070707'

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        cat = Categorie.objects.create(nom=f'WA QA {uid}', slug=f'wa-qa-{uid}', est_active=True,
                                       types_partenaire=['restaurateur'], types_articles=['plat'])

        def utilisateur(role, **kw):
            return User.objects.create(telephone=telephone_libre(), username=f't_wa_{uuid.uuid4().hex[:8]}',
                                       role=role, est_verifie=True, **kw)

        def partenaire(nom, type_partenaire, whatsapp='07 07 07 07 07', actif=False):
            p = ProfilPartenaire.objects.create(
                user=utilisateur('partenaire'), plan=plan, nom_commerce=f'{nom} {uid}',
                type_partenaire=type_partenaire, statut='actif', est_visible=True,
                whatsapp=whatsapp, whatsapp_externe_actif=actif)
            PartenaireCategorie.objects.create(partenaire=p, categorie=cat, est_principale=True)
            return p

        def article(p, type_article):
            return Article.objects.create(partenaire=p, categorie=cat, nom=f'{type_article} {uid}',
                                          slug=f'wa-{uuid.uuid4().hex[:10]}', type=type_article, prix=1000,
                                          est_actif=True)

        boutique = partenaire('Boutique WA', 'commercant')
        resto = partenaire('Resto WA', 'restaurateur', actif=True)
        garage = partenaire('Garage WA', 'loueur_voiture', whatsapp='+225 05 05 05 05 05', actif=True)
        agence = partenaire('Agence WA', 'loueur_maison', actif=True)
        art_boutique = article(boutique, 'produit')
        plat = article(resto, 'plat')
        Vehicule.objects.create(article=(a_v := article(garage, 'vehicule')), marque='Toyota', modele='Yaris',
                                mode='location')
        Logement.objects.create(article=(a_l := article(agence, 'logement')), type_logement='villa')
        admin = utilisateur('admin', is_staff=True)
        PermissionsAdmin.objects.create(admin=admin, creer_partenaire=True)

        print('\n=== 1. NORMALISATION ===')
        for brut, attendu in (('07 07 07 07 07', ATTENDU), ('0707070707', ATTENDU), ('+225 0707070707', ATTENDU),
                              ('00225 07-07-07-07-07', ATTENDU), ('2250707070707', ATTENDU),
                              ('+33 6 12 34 56 78', '33612345678'), ('', None), ('12345', None)):
            ok(f'normaliser « {brut} » -> {attendu}', normaliser_whatsapp(brut) == attendu, normaliser_whatsapp(brut))

        print('\n=== 2. VITRINE : DEFAUT NULL, ACTIVE -> NUMERO NORMALISE ===')
        v = req('get', f'/api/v1/auth/partenaires/{boutique.id}/').json()
        ok('defaut (non active) -> whatsapp_externe null, whatsapp inchange',
           v.get('whatsapp_externe', 'absent') is None and v['whatsapp'] == '07 07 07 07 07', v.get('whatsapp_externe'))
        ok('active + numero -> normalise', req('get', f'/api/v1/auth/partenaires/{resto.id}/').json()
           .get('whatsapp_externe') == ATTENDU)
        ok('autre format (+225 05…) -> normalise',
           req('get', f'/api/v1/auth/partenaires/{garage.id}/').json().get('whatsapp_externe') == '2250505050505')

        print('\n=== 3. AUTRES LECTURES PUBLIQUES ===')
        r = req('get', f'/api/v1/catalogue/categories/{cat.slug}/partenaires/')
        cartes = {c['id']: c for c in r.json()}
        ok('annuaire : cle presente, valeur selon activation', cartes[resto.id]['whatsapp_externe'] == ATTENDU
           and cartes[boutique.id]['whatsapp_externe'] is None, r.content[:200])
        ok('fiche article (boutique non active) -> null',
           req('get', f'/api/v1/catalogue/articles/{art_boutique.slug}/').json().get('whatsapp_externe', 'absent') is None)
        ok('fiche article (plat, resto actif) -> numero',
           req('get', f'/api/v1/catalogue/articles/{plat.slug}/').json().get('whatsapp_externe') == ATTENDU)
        lignes = {x['id']: x for x in req('get', '/api/v1/restaurants/').json()['resultats']}
        ok('liste restaurants', lignes.get(resto.id, {}).get('whatsapp_externe') == ATTENDU, lignes.get(resto.id))
        ok('detail restaurant', req('get', f'/api/v1/restaurants/{resto.id}/').json().get('whatsapp_externe') == ATTENDU)
        r = req('get', f'/api/v1/restaurants/produits/{plat.id}/')
        ok('fiche produit : partenaire.whatsapp_externe',
           r.status_code == 200 and r.json()['partenaire'].get('whatsapp_externe') == ATTENDU, r.content[:200])
        r = req('get', f'/api/v1/locations/partenaires/{garage.id}/vehicules/')
        ok('locations : liste vehicules (loueur)', r.json()['loueur'].get('whatsapp_externe') == '2250505050505')
        r = req('get', f'/api/v1/locations/vehicules/{a_v.id}/')
        ok('locations : detail vehicule (loueur)', r.json()['loueur'].get('whatsapp_externe') == '2250505050505')
        r = req('get', f'/api/v1/locations/partenaires/{agence.id}/logements/')
        ok('locations : liste logements (loueur)', r.json()['loueur'].get('whatsapp_externe') == ATTENDU)
        r = req('get', f'/api/v1/locations/logements/{a_l.id}/')
        ok('locations : detail logement (loueur)', r.json()['loueur'].get('whatsapp_externe') == ATTENDU)

        print('\n=== 4. ECRITURE PAR LE PARTENAIRE ===')
        URL_P = '/api/v1/auth/mon-profil-partenaire/'
        r = req('patch', URL_P, boutique.user, {'whatsapp_externe_actif': True})
        ok('activer (numero deja present) -> 200, numero public', r.status_code == 200
           and r.json().get('whatsapp_externe_actif') is True and r.json().get('whatsapp_externe') == ATTENDU,
           r.content[:300])
        ok('vitrine suit', req('get', f'/api/v1/auth/partenaires/{boutique.id}/').json()['whatsapp_externe'] == ATTENDU)
        r = req('patch', URL_P, boutique.user, {'whatsapp': ''})
        ok('vider le numero alors que le bouton est actif -> 400 sur whatsapp', r.status_code == 400
           and 'whatsapp' in r.json().get('details', r.json()), r.content[:300])
        r = req('patch', URL_P, boutique.user, {'whatsapp_externe_actif': False, 'whatsapp': ''})
        ok('desactiver et vider en meme temps -> 200, null', r.status_code == 200
           and r.json().get('whatsapp_externe') is None, r.content[:200])
        r = req('patch', URL_P, boutique.user, {'whatsapp_externe_actif': True})
        ok('activer sans numero -> 400 clair sur whatsapp', r.status_code == 400
           and 'whatsapp' in r.json().get('details', r.json()), r.content[:300])
        r = req('patch', URL_P, boutique.user, {'whatsapp_externe_actif': True, 'whatsapp': '12'})
        ok('activer avec un numero inexploitable -> 400', r.status_code == 400)
        r = req('patch', URL_P, boutique.user, {'whatsapp_externe_actif': True, 'whatsapp': '0101010101'})
        ok('activer en fournissant le numero -> 200', r.status_code == 200
           and r.json().get('whatsapp_externe') == '2250101010101', r.content[:200])

        print('\n=== 5. ECRITURE PAR L ADMIN ===')
        URL_A = f'/api/v1/administration/partenaires/{agence.id}/edition/'
        r = req('get', URL_A, admin)
        ok('fiche edition : whatsapp_externe_actif + whatsapp_externe', r.status_code == 200
           and r.json().get('whatsapp_externe_actif') is True and r.json().get('whatsapp_externe') == ATTENDU,
           r.content[:200])
        r = req('patch', URL_A, admin, {'whatsapp_externe_actif': False})
        ok('admin desactive -> 200, public null', r.status_code == 200
           and req('get', f'/api/v1/auth/partenaires/{agence.id}/').json()['whatsapp_externe'] is None, r.content[:200])
        r = req('patch', URL_A, admin, {'whatsapp_externe_actif': True, 'whatsapp': ''})
        ok('admin active sans numero -> 400 sur whatsapp', r.status_code == 400
           and 'whatsapp' in r.json().get('details', r.json()), r.content[:300])
        r = req('patch', URL_A, admin, {'whatsapp_externe_actif': True})
        ok('admin reactive (numero present) -> 200', r.status_code == 200
           and r.json().get('whatsapp_externe') == ATTENDU, r.content[:200])

        raise Rollback()
except Rollback:
    print('\nRollback effectue (rien persiste).')

print(f'\n=== TOTAL : {NB_OK} OK / {len(KO)} KO ===')
if KO:
    print('KO :', *KO, sep='\n - ')
    raise SystemExit(1)
