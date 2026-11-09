"""Tests : vente des véhicules et des maisons (additif aux locations).

Couvre : défaut location (et Vehicule.mode historique tenu en cohérence),
règle des prix selon le mode, champs propres (véhicule / maison vendus),
filtres publics ?mode= (location_vente dans les deux), demande « achat » sans
dates (et refus croisés), acceptation par le loueur sans effet de bord,
marquer vendu → retiré du public (visible loueur / admin), remettre en vente,
filtres et compteurs admin, méta (champs conditionnels, libellés).

Autonome : crée ses données (département, catégorie, loueurs, client, admin) ;
limitation de débit désactivée ; tout dans une transaction annulée.
Affiche un total OK / KO.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_vente_vehicules_maisons.py
"""
import json, uuid
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.test import Client
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.catalog.models import Categorie, Logement, Vehicule
from apps.geo.models import Departement, District, Region
from apps.reservations.models import DemandeReservation
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
    fn = getattr(Client(), method)
    if corps is not None:
        return fn(url, json.dumps(corps), content_type='application/json', **kw)
    return fn(url, **kw)


def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel


try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        district = District.objects.create(nom=f'District QA vente {uid}')
        region = Region.objects.create(nom=f'Region QA vente {uid}', district=district)
        dep = Departement.objects.create(nom=f'Dep QA vente {uid}', region=region)
        # Catégorie des annonces créées (correspondance type → catégorie, en tête).
        Categorie.objects.create(nom=f'Locations QA vente {uid}', slug=f'loc-qa-vente-{uid}', ordre=-100000,
                                 types_partenaire=['loueur_voiture', 'loueur_maison'])

        def utilisateur(role, staff=False):
            return User.objects.create(telephone=telephone_libre(), username=f't_vte_{uuid.uuid4().hex[:8]}',
                                       role=role, est_verifie=True, is_staff=staff, first_name='QA')

        def loueur(nom, type_partenaire):
            return ProfilPartenaire.objects.create(
                user=utilisateur('partenaire'), plan=plan, nom_commerce=f'{nom} {uid}',
                type_partenaire=type_partenaire, statut='actif', est_visible=True, departement=dep)

        garage = loueur('Garage QA vente', 'loueur_voiture')
        agence = loueur('Agence QA vente', 'loueur_maison')
        client = utilisateur('client')
        admin = utilisateur('admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin, gerer_locations=True, gerer_reservations=True)

        MON_V = '/api/v1/locations/mon-espace/vehicules/'
        MON_L = '/api/v1/locations/mon-espace/logements/'
        ADM_V = f'/api/v1/locations/admin/{garage.id}/vehicules/'
        PUB_V = f'/api/v1/locations/partenaires/{garage.id}/vehicules/'
        PUB_L = f'/api/v1/locations/partenaires/{agence.id}/logements/'
        base_v = {'categorie_vehicule': 'voiture', 'marque': 'Toyota', 'nb_places': 5}
        base_l = {'type_logement': 'villa', 'nb_chambres': 3}

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 1. DEFAUT LOCATION ET REGLE DES PRIX ===')
        r = req('post', MON_V, garage.user, {**base_v, 'nom': f'Yaris loc {uid}', 'modele': 'Yaris', 'prix': 20000})
        v_loc = r.json()
        ok('sans mode -> 201, mode location (defaut)', r.status_code == 201 and v_loc['mode'] == 'location'
           and v_loc['mode_libelle'] == 'Location' and v_loc['prix_vente'] is None and v_loc['vendu'] is False,
           r.content[:300])
        ok('Vehicule.mode historique = location',
           Vehicule.objects.get(article_id=v_loc['id']).mode == Vehicule.Mode.LOCATION)
        r = req('post', MON_V, garage.user, {**base_v, 'nom': 'x', 'modele': 'X'})
        ok('location sans prix -> 400 (prix)', r.status_code == 400 and 'prix' in r.json()['details'], r.content)
        r = req('post', MON_V, garage.user, {**base_v, 'nom': 'x', 'modele': 'X', 'mode': 'vente'})
        ok('vente sans prix_vente -> 400 (prix_vente)', r.status_code == 400
           and 'prix_vente' in r.json()['details'] and 'prix' not in r.json()['details'], r.content)
        r = req('post', MON_V, garage.user, {**base_v, 'nom': 'x', 'modele': 'X', 'mode': 'location_vente',
                                             'prix': 20000})
        ok('location_vente sans prix_vente -> 400', r.status_code == 400 and 'prix_vente' in r.json()['details'])
        r = req('post', MON_V, garage.user, {**base_v, 'nom': 'x', 'modele': 'X', 'mode': 'location_vente',
                                             'prix_vente': 5000000})
        ok('location_vente sans prix de location -> 400', r.status_code == 400 and 'prix' in r.json()['details'])
        ok('mode inconnu -> 400', req('post', MON_V, garage.user, {**base_v, 'nom': 'x', 'modele': 'X',
                                                                  'mode': 'troc', 'prix': 1}).status_code == 400)

        corps_vente = {**base_v, 'nom': f'Corolla vente {uid}', 'modele': 'Corolla', 'annee': 2016,
                       'mode': 'vente', 'prix_vente': 7500000, 'prix_negociable': False,
                       'kilometrage': 98000, 'etat': 'france_au_revoir', 'dedouane': True, 'carte_grise': True,
                       'visite_technique_valide_jusqu_au': '2027-03-31', 'assurance_valide_jusqu_au': '2027-01-15',
                       'nb_proprietaires': 2}
        r = req('post', MON_V, garage.user, corps_vente)
        v_vente = r.json()
        ok('vente sans prix de location -> 201', r.status_code == 201 and v_vente['prix'] is None, r.content[:300])
        ok('champs du vehicule vendu exposes', v_vente.get('etat') == 'france_au_revoir'
           and v_vente.get('etat_libelle') == 'France au revoir (occasion importée)'
           and v_vente['dedouane'] is True and v_vente['carte_grise'] is True and v_vente['nb_proprietaires'] == 2
           and str(v_vente['visite_technique_valide_jusqu_au']) == '2027-03-31' and v_vente['kilometrage'] == 98000
           and Decimal(str(v_vente['prix_vente'])) == Decimal('7500000') and v_vente['prix_negociable'] is False,
           v_vente)
        ok('Vehicule.mode historique = vente', Vehicule.objects.get(article_id=v_vente['id']).mode == 'vente')
        r = req('post', MON_V, garage.user, {**base_v, 'nom': f'Hilux mixte {uid}', 'modele': 'Hilux',
                                             'mode': 'location_vente', 'prix': 45000, 'prix_vente': 18000000})
        v_lv = r.json()
        ok('location_vente avec les deux prix -> 201', r.status_code == 201 and v_lv['mode'] == 'location_vente')
        ok('Vehicule.mode historique = les_deux', Vehicule.objects.get(article_id=v_lv['id']).mode == 'les_deux')
        r = req('patch', f"{MON_V}{v_loc['id']}/", garage.user, {'mode': 'vente'})
        ok('PATCH location -> vente sans prix_vente -> 400', r.status_code == 400 and 'prix_vente' in r.json()['details'])
        r = req('patch', f"{MON_V}{v_lv['id']}/", garage.user, {'prix': None})
        ok('PATCH location_vente : retirer le prix de location -> 400', r.status_code == 400)

        print('--- maisons ---')
        r = req('post', MON_L, agence.user, {**base_l, 'nom': f'Villa loc {uid}', 'prix': 150000})
        l_loc = r.json()
        ok('maison sans mode -> location', r.status_code == 201 and l_loc['mode'] == 'location', r.content[:300])
        r = req('post', MON_L, agence.user, {**base_l, 'nom': f'Villa vente {uid}', 'mode': 'vente',
                                             'prix_vente': 65000000, 'type_document': 'acd',
                                             'surface_terrain_m2': 600, 'est_lotie': True, 'surface_m2': 180})
        l_vente = r.json()
        ok('maison a vendre -> 201, champs propres', r.status_code == 201 and l_vente['type_document'] == 'acd'
           and l_vente['type_document_libelle'].startswith('ACD') and l_vente['surface_terrain_m2'] == 600
           and l_vente['est_lotie'] is True and l_vente['prix'] is None, r.content[:300])
        r = req('post', MON_L, agence.user, {**base_l, 'nom': f'Duplex mixte {uid}', 'mode': 'location_vente',
                                             'prix': 300000, 'prix_vente': 90000000})
        l_lv = r.json()
        ok('maison location_vente -> 201', r.status_code == 201)
        ok('maison vente sans prix_vente -> 400', req('post', MON_L, agence.user, {
            **base_l, 'nom': 'x', 'mode': 'vente'}).status_code == 400)
        ok('type_document inconnu -> 400', req('post', MON_L, agence.user, {
            **base_l, 'nom': 'x', 'mode': 'vente', 'prix_vente': 1, 'type_document': 'titre'}).status_code == 400)
        ok('existant (cree en base) : location par defaut',
           Logement._meta.get_field('mode_transaction').default == 'location'
           and Vehicule._meta.get_field('mode_transaction').default == 'location')

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 2. LISTES PUBLIQUES ?mode= ===')

        def ids(url):
            r = req('get', url)
            return r, {x['id'] for x in r.json()['resultats']}

        r, tous = ids(PUB_V)
        ok('vehicules sans filtre : les 3', tous == {v_loc['id'], v_vente['id'], v_lv['id']}, tous)
        carte = next(x for x in r.json()['resultats'] if x['id'] == v_vente['id'])
        ok('carte publique : mode, prix_vente, champs vente', carte['mode'] == 'vente'
           and carte['mode_libelle'] == 'Vente' and carte['etat'] == 'france_au_revoir' and carte['vendu'] is False,
           carte)
        ok('?mode=vente : vente + location_vente', ids(PUB_V + '?mode=vente')[1] == {v_vente['id'], v_lv['id']})
        ok('?mode=location : location + location_vente', ids(PUB_V + '?mode=location')[1] == {v_loc['id'], v_lv['id']})
        ok('?mode inconnu ignore', ids(PUB_V + '?mode=troc')[1] == tous)
        ok('maisons ?mode=vente', ids(PUB_L + '?mode=vente')[1] == {l_vente['id'], l_lv['id']})
        ok('maisons ?mode=location', ids(PUB_L + '?mode=location')[1] == {l_loc['id'], l_lv['id']})
        r = req('get', f"/api/v1/locations/logements/{l_vente['id']}/")
        ok('detail maison publique : champs vente', r.status_code == 200 and r.json()['mode'] == 'vente'
           and r.json()['type_document'] == 'acd' and r.json()['est_lotie'] is True, r.content[:200])
        r = req('get', f"/api/v1/locations/vehicules/{v_vente['id']}/")
        ok('detail vehicule public : champs vente', r.status_code == 200 and r.json()['dedouane'] is True
           and r.json()['nb_proprietaires'] == 2, r.content[:200])

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 3. DEMANDE « ACHAT » ===')
        D = '/api/v1/reservations/'
        r = req('post', D, client, {'objet_id': v_vente['id'], 'nature': 'achat', 'message': 'Toujours dispo ?'})
        achat = r.json()
        ok('achat sur vehicule a vendre, sans dates -> 201', r.status_code == 201 and achat['nature'] == 'achat'
           and achat['date_debut'] is None and achat['date_fin'] is None, r.content[:300])
        ok('montant_estime = prix de vente', Decimal(str(achat['montant_estime'])) == Decimal('7500000'))
        r = req('post', D, client, {'objet_id': v_vente['id'], 'nature': 'achat',
                                    'date_debut': '2027-01-01', 'date_fin': '2027-01-05'})
        ok('achat : dates envoyees ignorees', r.status_code == 201 and r.json()['date_debut'] is None, r.content[:200])
        r = req('post', D, client, {'objet_id': v_loc['id'], 'nature': 'achat'})
        ok('achat sur annonce en location seule -> 400', r.status_code == 400 and 'nature' in r.json()['details'])
        debut = timezone.localdate() + timedelta(days=10)
        r = req('post', D, client, {'objet_id': v_vente['id'], 'nature': 'reservation',
                                    'date_debut': str(debut), 'date_fin': str(debut + timedelta(days=2))})
        ok('reservation sur annonce a vendre seulement -> 400', r.status_code == 400
           and 'nature' in r.json()['details'], r.content)
        r = req('post', D, client, {'objet_id': v_lv['id'], 'nature': 'achat'})
        ok('achat sur location_vente -> 201', r.status_code == 201)
        r = req('post', D, client, {'objet_id': v_lv['id'], 'nature': 'reservation',
                                    'date_debut': str(debut), 'date_fin': str(debut + timedelta(days=2))})
        ok('reservation sur location_vente -> 201', r.status_code == 201, r.content[:200])
        r = req('post', D, client, {'objet_id': l_vente['id'], 'nature': 'achat', 'message': 'Visite samedi ?'})
        achat_maison = r.json()
        ok('achat sur maison a vendre -> 201', r.status_code == 201, r.content[:200])
        r = req('post', f"{D}{achat_maison['id']}/transition/", agence.user, {'action': 'confirmee'})
        ok('le loueur accepte la demande d achat -> 200', r.status_code == 200
           and r.json()['statut'] == 'confirmee', r.content[:200])
        ok('acceptation d un achat : disponibilite du logement inchangee',
           Logement.objects.get(article_id=l_vente['id']).disponibilite == 'disponible')
        r = req('post', f"{D}{achat['id']}/transition/", garage.user, {'action': 'refusee', 'commentaire': 'Vendu ailleurs'})
        ok('le loueur refuse une demande d achat -> 200', r.status_code == 200 and r.json()['statut'] == 'refusee')

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 4. MARQUER VENDU / REMETTRE EN VENTE ===')
        V = f"{MON_V}{v_vente['id']}/vendu/"
        ok('vendu non booleen -> 400', req('post', V, garage.user, {'vendu': 'oui'}).status_code == 400)
        ok('vendu sur annonce en location seule -> 400',
           req('post', f"{MON_V}{v_loc['id']}/vendu/", garage.user, {'vendu': True}).status_code == 400)
        r = req('post', V, garage.user, {'vendu': True})
        ok('marquer vendu -> 200, vendu_le pose', r.status_code == 200 and r.json()['vendu'] is True
           and r.json()['vendu_le'], r.content[:200])
        ok('vendu : absent des listes publiques', v_vente['id'] not in ids(PUB_V)[1]
           and v_vente['id'] not in ids(PUB_V + '?mode=vente')[1])
        ok('vendu : toujours visible du loueur', v_vente['id'] in {x['id'] for x in req(
            'get', MON_V, garage.user).json()['resultats']})
        ok('vendu : detail public accessible (vendu=true)',
           req('get', f"/api/v1/locations/vehicules/{v_vente['id']}/").json().get('vendu') is True)
        ok('achat sur annonce vendue -> 400', req('post', D, client, {
            'objet_id': v_vente['id'], 'nature': 'achat'}).status_code == 400)
        r = req('post', V, garage.user, {'vendu': False})
        ok('remettre en vente -> vendu false, vendu_le null, de nouveau public', r.status_code == 200
           and r.json()['vendu'] is False and r.json()['vendu_le'] is None and v_vente['id'] in ids(PUB_V)[1])

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 5. ADMIN ===')
        r = req('post', f"{ADM_V}{v_lv['id']}/vendu/", admin, {'vendu': True})
        ok('admin marque vendu -> 200 + journal', r.status_code == 200 and JournalModeration.objects.filter(
            acteur=admin, action='loc_vehicule_modif', motif__contains='marqué vendu').exists(), r.content[:200])
        r = req('get', ADM_V + '?mode=vente', admin)
        ok('admin ?mode=vente (vendus compris)', {x['id'] for x in r.json()['resultats']} == {v_vente['id'], v_lv['id']})
        r = req('get', ADM_V + '?vendu=1', admin)
        ok('admin ?vendu=1', [x['id'] for x in r.json()['resultats']] == [v_lv['id']], r.content[:200])
        ok('admin : colonnes mode + vendu', all({'mode', 'vendu'} <= set(x) for x in r.json()['resultats']))
        lignes = {x['id']: x for x in req('get', '/api/v1/locations/admin/', admin).json()['resultats']}
        ok('liste loueurs : nb_a_vendre / nb_vendus', lignes[garage.id]['nb_a_vendre'] == 1
           and lignes[garage.id]['nb_vendus'] == 1 and lignes[agence.id]['nb_a_vendre'] == 2, lignes.get(garage.id))
        r = req('get', f'/api/v1/reservations/admin/demandes/?partenaire={garage.id}', admin)
        cm = r.json()['compteurs_metier']
        # Garage : 3 achats (dont 1 refusé) + 1 réservation, tous véhicules.
        ok('compteurs_metier : achat (demandes d achat) + total inchange',
           cm['achat'] == 3 and cm['vehicule'] == 4 and cm['total'] == 4, cm)
        ok('annonces_a_vendre (non vendues, par metier)', r.json()['annonces_a_vendre']
           == {'maison': 0, 'vehicule': 1, 'total': 1}, r.json().get('annonces_a_vendre'))
        r = req('get', '/api/v1/reservations/admin/demandes/?nature=achat&metier=vehicule&partenaire='
                f'{garage.id}', admin)
        ok('admin demandes ?nature=achat', r.status_code == 200 and r.json()['count'] == 3, r.content[:200])

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 6. META ===')
        m = req('get', '/api/v1/locations/meta/').json()
        ok('meta : modes', [x['valeur'] for x in m['modes']] == ['location', 'vente', 'location_vente'])
        ok('meta : etat France au revoir',
           any(x['valeur'] == 'france_au_revoir' and 'France au revoir' in x['libelle'] for x in m['etats_vehicule']))
        ok('meta : types de document', {x['valeur'] for x in m['types_document']}
           == {'acd', 'certificat_foncier', 'lettre_attribution', 'attestation_villageoise', 'autre'})
        champs_v = {c['cle']: c for c in m['champs_vente']['vehicule']}
        ok('meta : champs vente conditionnels (visible si vente / location_vente)',
           champs_v['prix_vente']['visible_si'] == {'champ': 'mode', 'valeurs': ['vente', 'location_vente']}
           and champs_v['prix']['visible_si']['valeurs'] == ['location', 'location_vente']
           and champs_v['mode']['visible_si'] is None, champs_v.get('prix_vente'))
        ok('meta : champs maison', {'type_document', 'surface_terrain_m2', 'est_lotie'}
           <= {c['cle'] for c in m['champs_vente']['logement']})

        raise Rollback()
except Rollback:
    print('\nRollback effectue (rien persiste).')

print(f'\n=== TOTAL : {NB_OK} OK / {len(KO)} KO ===')
if KO:
    print('KO :', *KO, sep='\n - ')
    raise SystemExit(1)
