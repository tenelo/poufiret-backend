"""Tests : centre admin des demandes de location — métier de chaque demande
(metier, metier_libelle), filtre ?metier= (liste et export CSV), compteurs_metier
calculés sans ?metier= mais avec les autres filtres, sans N+1. Affiche un extrait
JSON réel (une demande + compteurs_metier).

Autonome : crée ses loueurs, fiches établissement, articles, client et demandes.
Transaction annulée.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_reservations_metier.py
"""
import json, uuid
from datetime import timedelta
from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken
from apps.administration.models import PermissionsAdmin
from apps.catalog.models import Article, Categorie
from apps.locations.models import ProfilEtablissement
from apps.reservations.models import DemandeReservation
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

BASE = '/api/v1/reservations/admin/demandes/'

def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel

def utilisateur(role, staff=False):
    return User.objects.create(telephone=telephone_libre(), username=f't_rme_{uuid.uuid4().hex[:8]}',
                               role=role, est_verifie=True, is_staff=staff)

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        categorie = Categorie.objects.create(nom=f'Locations QA {uid}', slug=f'locations-qa-{uid}')
        admin = utilisateur('admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin, gerer_reservations=True)
        admin_sans = utilisateur('admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans)
        client = utilisateur('client')

        def get(params='', user=admin):
            return Client().get(BASE + params, secure=True, HTTP_HOST=HOST,
                                HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')

        def loueur(nom, type_partenaire, type_etab=None):
            p = ProfilPartenaire.objects.create(user=utilisateur('partenaire'), plan=plan,
                nom_commerce=f'{nom} RME {uid}', type_partenaire=type_partenaire, statut='actif')
            if type_etab:
                ProfilEtablissement.objects.create(partenaire=p, type_etablissement=type_etab)
            return p

        hotel = loueur('Hotel', 'hotelier', 'hotel')
        residence = loueur('Residence', 'hotelier', 'residence_meublee')
        auberge = loueur('Auberge', 'hotelier', 'auberge')
        sans_fiche = loueur('Hotel sans fiche', 'hotelier')
        maison = loueur('Maison', 'loueur_maison')
        auto = loueur('Auto', 'loueur_voiture')

        compteur = [0]
        def demande(partenaire, type_article, nature='reservation', statut='nouvelle'):
            compteur[0] += 1
            a = Article.objects.create(partenaire=partenaire, categorie=categorie, nom=f'Bien {compteur[0]} {uid}',
                                       slug=f'rme-{uuid.uuid4().hex[:8]}', type=type_article, prix=10000)
            return DemandeReservation.objects.create(
                numero=f'RES-RME-{uid}-{compteur[0]:03d}', client=client, partenaire=partenaire, objet=a,
                nature=nature, statut=statut,
                date_debut=timezone.localdate() + timedelta(days=3), date_fin=timezone.localdate() + timedelta(days=5))

        d_hotel = demande(hotel, 'hebergement')
        d_hotel2 = demande(hotel, 'hebergement', statut='confirmee')
        d_res = demande(residence, 'hebergement')
        d_aub = demande(auberge, 'hebergement')
        d_sf = demande(sans_fiche, 'hebergement')
        d_maison = demande(maison, 'logement', nature='visite')
        d_auto = demande(auto, 'vehicule')
        nos = {d.id for d in (d_hotel, d_hotel2, d_res, d_aub, d_sf, d_maison, d_auto)}
        q = f'&search=RES-RME-{uid}'  # limite aux demandes du test (search porte sur le numéro)

        def ids(r):
            return {x['id'] for x in r.json()['results']}

        print('=== 1. METIER DE CHAQUE DEMANDE ===')
        r = get(f'?page_size=100{q}')
        ok('liste -> 200, nos 7 demandes', r.status_code == 200 and ids(r) == nos, r.content[:200])
        par_id = {x['id']: x for x in r.json()['results']}
        print('Extrait JSON reel, une demande :')
        print(json.dumps(par_id[d_res.id], ensure_ascii=False, indent=2, default=str))
        print('Extrait JSON reel, compteurs_metier :', json.dumps(r.json()['compteurs_metier']))
        attendu = {d_hotel.id: 'hotel', d_hotel2.id: 'hotel', d_res.id: 'residence_meublee',
                   d_aub.id: 'hotel', d_sf.id: 'hotel', d_maison.id: 'maison', d_auto.id: 'vehicule'}
        ok('metier : hotel / residence_meublee / maison / vehicule (auberge et sans fiche -> hotel)',
           {i: par_id[i]['metier'] for i in nos} == attendu, {i: par_id[i]['metier'] for i in nos})
        ok('metier_libelle', par_id[d_res.id]['metier_libelle'] == 'Résidence meublée'
           and par_id[d_auto.id]['metier_libelle'] == 'Véhicule' and par_id[d_maison.id]['metier_libelle'] == 'Maison'
           and par_id[d_hotel.id]['metier_libelle'] == 'Hôtel')
        ok('compteurs_metier (tous les metiers + total)', r.json()['compteurs_metier']
           == {'hotel': 4, 'residence_meublee': 1, 'maison': 1, 'vehicule': 1, 'total': 7, 'achat': 0}, r.json()['compteurs_metier'])
        ok('compteurs_groupe toujours presents', 'compteurs_groupe' in r.json())

        print('=== 2. FILTRE ?metier= ===')
        for metier, attendus in (('hotel', {d_hotel.id, d_hotel2.id, d_aub.id, d_sf.id}),
                                 ('residence_meublee', {d_res.id}), ('maison', {d_maison.id}),
                                 ('vehicule', {d_auto.id})):
            r = get(f'?metier={metier}{q}')
            ok(f'?metier={metier}', ids(r) == attendus, ids(r))
        ok('compteurs_metier ignorent ?metier= (chaque pastille garde son total)',
           get(f'?metier=vehicule{q}').json()['compteurs_metier']['hotel'] == 4)
        ok('?metier inconnu -> 400', get(f'?metier=chateau{q}').status_code == 400)

        print('=== 3. COMBINAISONS ET COMPTEURS FILTRES ===')
        r = get(f'?metier=hotel&groupe=a_traiter{q}')
        ok('metier + groupe', ids(r) == {d_hotel.id, d_aub.id, d_sf.id}, ids(r))
        ok('compteurs_metier respectent groupe', r.json()['compteurs_metier']
           == {'hotel': 3, 'residence_meublee': 1, 'maison': 1, 'vehicule': 1, 'total': 6, 'achat': 0}, r.json()['compteurs_metier'])
        r = get(f'?nature=visite{q}')
        ok('compteurs_metier respectent nature', r.json()['compteurs_metier']
           == {'hotel': 0, 'residence_meublee': 0, 'maison': 1, 'vehicule': 0, 'total': 1, 'achat': 0}, r.json()['compteurs_metier'])
        r = get(f'?partenaire={hotel.id}&metier=hotel{q}')
        ok('metier + loueur', ids(r) == {d_hotel.id, d_hotel2.id}, ids(r))
        ok('compteurs_metier respectent loueur', r.json()['compteurs_metier']['total'] == 2)
        DemandeReservation.objects.filter(pk=d_auto.pk).update(created_at=timezone.now() - timedelta(days=20))
        avant = (timezone.localdate() - timedelta(days=10)).isoformat()
        r = get(f'?au={avant}{q}')
        ok('compteurs_metier respectent dates', ids(r) == {d_auto.id}
           and r.json()['compteurs_metier'] == {'hotel': 0, 'residence_meublee': 0, 'maison': 0, 'vehicule': 1,
                                                'total': 1, 'achat': 0}, r.json()['compteurs_metier'])
        ok('compteurs_groupe respectent metier', get(f'?metier=residence_meublee{q}').json()['compteurs_groupe']['total'] == 1)

        print('=== 4. DETAIL ET TRANSITION ===')
        r = get(f'{d_res.id}/')
        ok('detail : metier + libelle', r.status_code == 200 and r.json()['metier'] == 'residence_meublee'
           and r.json()['metier_libelle'] == 'Résidence meublée', r.content[:200])
        r = Client().post(f'{BASE}{d_sf.id}/transition/', json.dumps({'action': 'en_cours'}),
                          content_type='application/json', secure=True, HTTP_HOST=HOST,
                          HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(admin)}')
        ok('reponse de transition (sans annotation) : metier calcule (hotelier sans fiche -> hotel)',
           r.status_code == 200 and r.json()['metier'] == 'hotel', r.content[:200])

        print('=== 5. EXPORT CSV ===')
        r = get(f'export/?metier=residence_meublee{q}')
        lignes = r.content.decode('utf-8-sig').strip().splitlines()
        ok('export -> 200, colonne Metier', r.status_code == 200 and 'Metier' in lignes[0], lignes[:1])
        ok('export filtre par metier', len(lignes) == 2 and d_res.numero in lignes[1]
           and 'Résidence meublée' in lignes[1], lignes)
        ok('export ?metier inconnu -> 400', get(f'export/?metier=chateau{q}').status_code == 400)

        print('=== 6. SANS N+1 ===')
        def nb():
            with CaptureQueriesContext(connection) as ctx:
                assert get(f'?page_size=100{q}').status_code == 200
            return len(ctx.captured_queries)
        avant_n = nb()
        for _ in range(3):
            demande(residence, 'hebergement')
            demande(auto, 'vehicule')
        ok('requetes constantes avec 6 demandes de plus', nb() == avant_n, (avant_n, nb()))

        print('=== 7. DROITS ===')
        ok('admin sans gerer_reservations -> 403', get(user=admin_sans).status_code == 403)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
