"""Tests : espace hôtelier/admin (Locations Phase V2) — fiche établissement
et hébergements. Droits (403, gerer_locations, cloisonnement par type de
loueur), fiche établissement (création à la lecture, validations,
traçabilité, journal), CRUD hébergement (Article+Hebergement), images,
panoramas, disponibilité, 409, reservations_confirmees (avec nb_unites),
liste admin (hôtelier + compteurs).

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_locations_hebergements_gestion.py
"""
import io, json, uuid
from datetime import timedelta
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client
from django.utils import timezone
from PIL import Image
from rest_framework_simplejwt.tokens import AccessToken
from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.catalog.models import Article
from apps.geo.models import Departement
from apps.locations.models import ProfilEtablissement
from apps.reservations.models import DemandeReservation
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

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
    return User.objects.create(telephone=telephone_libre(), username=username, role=role,
                               est_verifie=True, is_staff=staff, is_superuser=superuser)

def req(method, url, user=None, corps=None, multipart=None):
    kw = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    c = Client()
    if multipart is not None:
        return getattr(c, method)(url, multipart, **kw)
    if corps is None:
        return getattr(c, method)(url, **kw)
    return getattr(c, method)(url, json.dumps(corps), content_type='application/json', **kw)

def png(nom):
    buf = io.BytesIO(); Image.new('RGB', (2, 2)).save(buf, format='PNG')
    return SimpleUploadedFile(nom, buf.getvalue(), content_type='image/png')

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        ferke = Departement.objects.get(nom='Ferké')
        hotel_user = utilisateur('t_hot_hotelier', role='partenaire')
        hotel = ProfilPartenaire.objects.create(user=hotel_user, plan=plan, nom_commerce=f'Hôtel QA {uid}',
            type_partenaire='hotelier', statut='actif', est_visible=True, departement=ferke)
        auto_user = utilisateur('t_hot_auto', role='partenaire')
        auto = ProfilPartenaire.objects.create(user=auto_user, plan=plan, nom_commerce=f'Auto QA {uid}',
            type_partenaire='loueur_voiture', statut='actif', est_visible=True, departement=ferke)
        super_ = utilisateur('t_hot_super', role='admin', staff=True, superuser=True)
        admin_sans = utilisateur('t_hot_sans', role='admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans)
        admin_avec = utilisateur('t_hot_avec', role='admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin_avec, gerer_locations=True)
        client_user = utilisateur('t_hot_client')

        MON_E = '/api/v1/locations/mon-espace/etablissement/'
        ADM_E = f'/api/v1/locations/admin/{hotel.id}/etablissement/'
        MON = '/api/v1/locations/mon-espace/hebergements/'
        ADM = f'/api/v1/locations/admin/{hotel.id}/hebergements/'

        print('=== 1. DROITS ===')
        ok('hotelier : GET etablissement -> 200', req('get', MON_E, hotel_user).status_code == 200)
        ok('hotelier : GET hebergements -> 200', req('get', MON, hotel_user).status_code == 200)
        ok('client -> 403', req('get', MON_E, client_user).status_code == 403)
        ok('loueur voiture -> 403 sur etablissement/hebergements',
           req('get', MON_E, auto_user).status_code == 403 and req('get', MON, auto_user).status_code == 403)
        ok('hotelier -> 403 sur vehicules et logements',
           req('get', '/api/v1/locations/mon-espace/vehicules/', hotel_user).status_code == 403
           and req('get', '/api/v1/locations/mon-espace/logements/', hotel_user).status_code == 403)
        ok('admin sans capacite -> 403', req('get', ADM_E, admin_sans).status_code == 403)
        ok('admin avec gerer_locations -> 200', req('get', ADM, admin_avec).status_code == 200)
        ok('admin : loueur voiture via /etablissement/ -> 404',
           req('get', f'/api/v1/locations/admin/{auto.id}/etablissement/', super_).status_code == 404)

        print('=== 2. FICHE ETABLISSEMENT ===')
        r = req('get', MON_E, hotel_user)
        e = r.json()
        attendus = {'partenaire_id', 'nom', 'type_etablissement', 'type_etablissement_libelle', 'etoiles',
                    'heure_arrivee', 'heure_depart', 'equipements_etablissement',
                    'equipements_etablissement_libelles', 'petit_dejeuner', 'petit_dejeuner_libelle',
                    'prix_petit_dejeuner', 'politique_annulation', 'conditions', 'modifie_par_role',
                    'modifie_par_nom', 'modifie_le', 'cree_le'}
        ok('fiche creee a la premiere lecture, champs attendus', attendus <= set(e)
           and ProfilEtablissement.objects.filter(partenaire=hotel).count() == 1, attendus - set(e))
        corps = {'type_etablissement': 'residence_meublee', 'etoiles': 3, 'heure_arrivee': '14:00',
                 'heure_depart': '11:00', 'equipements_etablissement': ['wifi', 'piscine', 'wifi'],
                 'petit_dejeuner': 'en_option', 'prix_petit_dejeuner': 3000,
                 'politique_annulation': 'Gratuite 48 h avant.', 'conditions': 'Caution 20 000 F, CNI.'}
        r = req('patch', MON_E, hotel_user, corps)
        ok('PATCH hotelier -> 200', r.status_code == 200, r.content)
        e = r.json()
        ok('valeurs + libelles', e['type_etablissement_libelle'] == 'Résidence meublée' and e['etoiles'] == 3
           and e['heure_arrivee'] == '14:00:00' and e['equipements_etablissement'] == ['wifi', 'piscine']
           and e['equipements_etablissement_libelles'] == ['Wifi', 'Piscine']
           and e['petit_dejeuner_libelle'] == 'En option', e)
        ok('tracabilite hotelier', e['modifie_par_role'] == 'loueur', e['modifie_par_role'])
        ok('etoiles 6 -> 400', req('patch', MON_E, hotel_user, {'etoiles': 6}).status_code == 400)
        ok('equipement inconnu -> 400',
           req('patch', MON_E, hotel_user, {'equipements_etablissement': ['spa']}).status_code == 400)
        ok('type inconnu -> 400', req('patch', MON_E, hotel_user, {'type_etablissement': 'camping'}).status_code == 400)
        ok('en_option sans prix -> 400',
           req('patch', MON_E, hotel_user, {'prix_petit_dejeuner': None}).status_code == 400)
        avant = JournalModeration.objects.filter(action='loc_etablissement_modif').count()
        r = req('patch', ADM_E, admin_avec, {'petit_dejeuner': 'inclus'})
        ok('PATCH admin -> 200, tracabilite admin', r.status_code == 200
           and r.json()['modifie_par_role'] == 'admin' and r.json()['petit_dejeuner'] == 'inclus', r.content)
        ok('journal loc_etablissement_modif',
           JournalModeration.objects.filter(action='loc_etablissement_modif').count() == avant + 1)

        print('=== 3. HEBERGEMENTS : CREATION ET VALIDATIONS ===')
        corps = {'nom': f'Chambre double {uid}', 'description': 'Vue jardin', 'prix': 25000,
                 'type_hebergement': 'chambre_double', 'capacite_adultes': 2, 'capacite_enfants': 1,
                 'lits': '1 lit double', 'surface_m2': 22,
                 'equipements_hebergement': ['climatisation', 'tv', 'tv'],
                 'prix_semaine': 150000, 'prix_mois': 500000, 'nb_unites': 5, 'duree_min_nuits': 1}
        r = req('post', MON, hotel_user, corps)
        ok('POST -> 201', r.status_code == 201, r.content)
        h = r.json()
        hid = h['id']
        attendus = {'id', 'nom', 'description', 'prix_nuit', 'est_actif', 'type_hebergement',
                    'type_hebergement_libelle', 'capacite_adultes', 'capacite_enfants', 'lits', 'surface_m2',
                    'equipements_hebergement', 'equipements_hebergement_libelles', 'prix_semaine', 'prix_mois',
                    'nb_unites', 'duree_min_nuits', 'disponibilite', 'disponibilite_libelle', 'images',
                    'panoramas', 'reservations_confirmees', 'modifie_par_role', 'modifie_par_nom',
                    'modifie_le', 'cree_le'}
        ok('fiche gestion : tous les champs', attendus <= set(h), attendus - set(h))
        ok('libelles + equipements dedoublonnes', h['type_hebergement_libelle'] == 'Chambre double'
           and h['equipements_hebergement'] == ['climatisation', 'tv']
           and h['equipements_hebergement_libelles'] == ['Climatisation', 'Télévision'], h)
        ok('Article type hebergement', Article.objects.get(pk=hid).type == 'hebergement')
        ok('tracabilite loueur', h['modifie_par_role'] == 'loueur')
        ok('type inconnu -> 400', req('post', MON, hotel_user, {**corps, 'type_hebergement': 'tente'}).status_code == 400)
        ok('equipement inconnu -> 400',
           req('post', MON, hotel_user, {**corps, 'equipements_hebergement': ['jacuzzi']}).status_code == 400)
        ok('nb_unites 0 -> 400', req('post', MON, hotel_user, {**corps, 'nb_unites': 0}).status_code == 400)
        ok('capacite_adultes 0 -> 400', req('post', MON, hotel_user, {**corps, 'capacite_adultes': 0}).status_code == 400)
        ok('prix manquant -> 400', req('post', MON, hotel_user, {k: v for k, v in corps.items() if k != 'prix'}).status_code == 400)

        print('=== 4. MODIFICATION ADMIN + DISPONIBILITE ===')
        avant = JournalModeration.objects.filter(action='loc_hebergement_modif').count()
        r = req('patch', f'{ADM}{hid}/', admin_avec, {'prix': 27000, 'nb_unites': 6})
        ok('PATCH admin -> 200', r.status_code == 200 and int(r.json()['prix_nuit']) == 27000
           and r.json()['nb_unites'] == 6 and r.json()['modifie_par_role'] == 'admin', r.content)
        ok('journal loc_hebergement_modif',
           JournalModeration.objects.filter(action='loc_hebergement_modif').count() == avant + 1)
        ok('valeur logement (reserve) refusee -> 400',
           req('post', f'{MON}{hid}/disponibilite/', hotel_user, {'disponibilite': 'reserve'}).status_code == 400)
        avant = JournalModeration.objects.filter(action='loc_hebergement_dispo').count()
        r = req('post', f'{ADM}{hid}/disponibilite/', admin_avec, {'disponibilite': 'indisponible'})
        ok('indisponible (admin) -> 200', r.status_code == 200 and r.json()['disponibilite'] == 'indisponible')
        ok('journal loc_hebergement_dispo',
           JournalModeration.objects.filter(action='loc_hebergement_dispo').count() == avant + 1)
        r = req('post', f'{MON}{hid}/disponibilite/', hotel_user, {'disponibilite': 'disponible'})
        ok('disponible (hotelier) -> 200', r.status_code == 200 and r.json()['disponibilite'] == 'disponible')
        ok('autre loueur : detail -> 403', req('get', f'{MON}{hid}/', auto_user).status_code == 403)

        print('=== 5. IMAGES ET PANORAMAS ===')
        r = req('post', f'{MON}{hid}/images/', hotel_user, multipart={'article': hid, 'image': png('a.png'), 'ordre': 1})
        ok('image hotelier -> 201', r.status_code == 201, r.content)
        img_id = r.json()['id']
        ok('image dans la fiche', len(req('get', f'{MON}{hid}/', hotel_user).json()['images']) == 1)
        ok('image : delete admin -> 204', req('delete', f'{ADM}{hid}/images/{img_id}/', admin_avec).status_code == 204)
        r = req('post', f'{ADM}{hid}/panoramas/', admin_avec,
                multipart={'article': hid, 'image': png('p.png'), 'titre': 'Chambre', 'type_vue': 'photo_360'})
        ok('panorama admin -> 201', r.status_code == 201 and r.json()['titre'] == 'Chambre', r.content)
        pano_id = r.json()['id']
        ok('panorama PATCH hotelier -> 200',
           req('patch', f'{MON}{hid}/panoramas/{pano_id}/', hotel_user, {'titre': 'Suite'}).json()['titre'] == 'Suite')
        ok('panorama via route vehicule -> 403',
           req('get', f'/api/v1/locations/mon-espace/vehicules/{hid}/panoramas/', hotel_user).status_code == 403)

        print('=== 6. RESERVATIONS CONFIRMEES (avec nb_unites) + 409 ===')
        auj = timezone.localdate()
        art = Article.objects.get(pk=hid)
        for n, (deb, fin, statut, unites) in enumerate([(3, 5, 'confirmee', 2), (-6, -2, 'confirmee', 1),
                                                       (8, 9, 'nouvelle', 1)]):
            DemandeReservation.objects.create(numero=f'RSV-H-{uid}-{n}', client=client_user, partenaire=hotel,
                objet=art, nature='reservation', statut=statut, nb_unites=unites,
                date_debut=auj + timedelta(days=deb), date_fin=auj + timedelta(days=fin))
        rc = req('get', f'{MON}{hid}/', hotel_user).json()['reservations_confirmees']
        ok('reservations_confirmees : confirmee a venir, avec nb_unites', len(rc) == 1
           and set(rc[0]) == {'demande_id', 'date_debut', 'date_fin', 'nb_unites'} and rc[0]['nb_unites'] == 2, rc)
        ok('DELETE avec demandes -> 409', req('delete', f'{MON}{hid}/', hotel_user).status_code == 409)
        r = req('post', ADM, super_, {**corps, 'nom': f'Suite {uid}', 'type_hebergement': 'suite'})
        ok('creation admin -> 201', r.status_code == 201, r.content)
        ok('DELETE sans demande -> 204', req('delete', f'{ADM}{r.json()["id"]}/', super_).status_code == 204)

        print('=== 7. LISTE ADMIN ===')
        lignes = {x['id']: x for x in req('get', '/api/v1/locations/admin/', admin_avec).json()['resultats']}
        l = lignes.get(hotel.id)
        ok('hotelier present avec type_partenaire', l and l['type_partenaire'] == 'hotelier', l)
        ok('compteurs (1 hebergement disponible, 1 demande en attente)', l['nb_biens'] == 1
           and l['nb_disponibles'] == 1 and l['demandes_en_attente'] == 1, l)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
