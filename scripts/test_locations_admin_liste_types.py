"""Tests : GET /api/v1/locations/admin/ — champ type_etablissement (hôteliers ;
null sinon), filtres ?type_partenaire= et ?type_etablissement= (combinables),
sans N+1. Affiche une ligne JSON réelle.

Autonome : crée ses loueurs, comptes et fiches établissement. Transaction annulée.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_locations_admin_liste_types.py
"""
import json, uuid
from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from rest_framework_simplejwt.tokens import AccessToken
from apps.administration.models import PermissionsAdmin
from apps.locations.models import ProfilEtablissement
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

URL = '/api/v1/locations/admin/'

def get(user, params=''):
    return Client().get(URL + params, secure=True, HTTP_HOST=HOST,
                        HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')

def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel

def utilisateur(role, staff=False):
    return User.objects.create(telephone=telephone_libre(), username=f't_lat_{uuid.uuid4().hex[:8]}',
                               role=role, est_verifie=True, is_staff=staff)

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')

        def loueur(nom, type_partenaire, type_etab=None):
            p = ProfilPartenaire.objects.create(user=utilisateur('partenaire'), plan=plan,
                nom_commerce=f'{nom} QA {uid}', type_partenaire=type_partenaire, statut='actif')
            if type_etab:
                ProfilEtablissement.objects.create(partenaire=p, type_etablissement=type_etab)
            return p

        hotel = loueur('Hotel', 'hotelier', 'hotel')
        residence = loueur('Residence', 'hotelier', 'residence_meublee')
        hotel_sans_fiche = loueur('Hotel sans fiche', 'hotelier')
        maison = loueur('Maison', 'loueur_maison')
        voiture = loueur('Auto', 'loueur_voiture')
        nos_ids = {hotel.id, residence.id, hotel_sans_fiche.id, maison.id, voiture.id}

        admin_avec = utilisateur('admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin_avec, gerer_locations=True)
        admin_sans = utilisateur('admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans)

        def lignes(params=''):
            r = get(admin_avec, params)
            return r, {x['id']: x for x in r.json()['resultats'] if x['id'] in nos_ids} if r.status_code == 200 else {}

        print('=== 1. CHAMP type_etablissement ===')
        r, L = lignes()
        ok('liste -> 200, nos 5 loueurs presents', r.status_code == 200 and set(L) == nos_ids, r.content[:200])
        print('Extrait JSON reel, ligne hotelier :')
        print(json.dumps(L[residence.id], ensure_ascii=False, indent=2))
        ok('hotelier : type de sa fiche', L[hotel.id]['type_etablissement'] == 'hotel'
           and L[residence.id]['type_etablissement'] == 'residence_meublee', L[residence.id])
        ok('libelle', L[residence.id]['type_etablissement_libelle'] == 'Résidence meublée'
           and L[hotel.id]['type_etablissement_libelle'] == 'Hôtel')
        ok('hotelier sans fiche : valeur par defaut de la fiche (hotel)',
           L[hotel_sans_fiche.id]['type_etablissement'] == 'hotel')
        ok('non hotelier : null (champ et libelle)', all(
            L[i]['type_etablissement'] is None and L[i]['type_etablissement_libelle'] is None
            for i in (maison.id, voiture.id)))
        ok('champs historiques conserves', {'id', 'nom', 'type_partenaire', 'type_partenaire_libelle',
                                           'departement_nom', 'nb_biens', 'nb_disponibles', 'nb_indisponibles',
                                           'nb_reserves', 'nb_loues', 'demandes_en_attente'} <= set(L[hotel.id]))

        print('=== 2. FILTRES ===')
        _r, L = lignes('?type_etablissement=residence_meublee')
        ok('?type_etablissement=residence_meublee', set(L) == {residence.id}, set(L))
        _r, L = lignes('?type_etablissement=hotel')
        ok('?type_etablissement=hotel (avec et sans fiche)', set(L) == {hotel.id, hotel_sans_fiche.id}, set(L))
        _r, L = lignes('?type_etablissement=motel')
        ok('?type_etablissement sans correspondance -> aucun des notres', L == {})
        _r, L = lignes('?type_partenaire=loueur_voiture')
        ok('?type_partenaire=loueur_voiture', set(L) == {voiture.id}, set(L))
        _r, L = lignes('?type_partenaire=hotelier')
        ok('?type_partenaire=hotelier', set(L) == {hotel.id, residence.id, hotel_sans_fiche.id}, set(L))
        _r, L = lignes('?type_partenaire=hotelier&type_etablissement=hotel')
        ok('combinaison hotelier + hotel', set(L) == {hotel.id, hotel_sans_fiche.id}, set(L))
        _r, L = lignes('?type_partenaire=loueur_maison&type_etablissement=hotel')
        ok('combinaison incompatible -> vide', L == {})
        ok('?type_etablissement inconnu -> 400', get(admin_avec, '?type_etablissement=chateau').status_code == 400)
        ok('?type_partenaire non loueur -> 400', get(admin_avec, '?type_partenaire=restaurateur').status_code == 400)

        print('=== 3. SANS N+1 ===')
        def nb_requetes():
            with CaptureQueriesContext(connection) as ctx:
                assert get(admin_avec).status_code == 200
            return len(ctx.captured_queries)
        avant = nb_requetes()
        for n in range(4):
            loueur(f'Hotel plus {n}', 'hotelier', 'auberge')
        ok('requetes constantes avec 4 hoteliers de plus', nb_requetes() == avant, (avant, nb_requetes()))

        print('=== 4. DROITS ===')
        ok('admin sans gerer_locations -> 403', get(admin_sans).status_code == 403)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
