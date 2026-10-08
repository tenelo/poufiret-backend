"""Tests : espace loueur/admin des véhicules (Locations Phase V1).
Droits (403, super-admin, gerer_locations, cloisonnement maison/véhicule),
CRUD véhicule (Article+Vehicule en une ressource), règles chauffeur,
cohérence géographique (400), images, panoramas, disponibilité,
traçabilité, journal, suppression protégée (409), reservations_confirmees,
liste admin (type_partenaire + compteurs génériques).

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_locations_vehicules_gestion.py
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
from apps.catalog.models import Article, Vehicule
from apps.geo.models import Departement, Localite, Quartier
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
    u = User.objects.create(telephone=telephone_libre(), username=username, role=role,
                            est_verifie=True, is_staff=staff, is_superuser=superuser)
    u.set_password('1234'); u.save()
    return u

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
        kong = Departement.objects.get(nom='Kong')
        loc_f = Localite.objects.create(nom=f'VLoc Ferke {uid}', departement=ferke)
        loc_k = Localite.objects.create(nom=f'VLoc Kong {uid}', departement=kong)
        q_f = Quartier.objects.create(nom=f'VQ Ferke {uid}', localite=loc_f)
        q_k = Quartier.objects.create(nom=f'VQ Kong {uid}', localite=loc_k)

        loueur_user = utilisateur('t_veh_loueur', role='partenaire')
        loueur = ProfilPartenaire.objects.create(user=loueur_user, plan=plan, nom_commerce=f'Loueur Auto QA {uid}',
            type_partenaire='loueur_voiture', statut='actif', est_visible=True, departement=ferke)
        maison_user = utilisateur('t_veh_maison', role='partenaire')
        maison = ProfilPartenaire.objects.create(user=maison_user, plan=plan, nom_commerce=f'Loueur Maison QA {uid}',
            type_partenaire='loueur_maison', statut='actif', est_visible=True, departement=ferke)
        super_ = utilisateur('t_veh_super', role='admin', staff=True, superuser=True)
        admin_sans = utilisateur('t_veh_sans', role='admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans)
        admin_avec = utilisateur('t_veh_avec', role='admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin_avec, gerer_locations=True)
        client_user = utilisateur('t_veh_client', role='client')

        MON = '/api/v1/locations/mon-espace/vehicules/'
        ADM = f'/api/v1/locations/admin/{loueur.id}/vehicules/'

        print('=== 1. DROITS ===')
        ok('loueur voiture : GET mon-espace -> 200', req('get', MON, loueur_user).status_code == 200)
        ok('client -> 403', req('get', MON, client_user).status_code == 403)
        ok('loueur maison -> 403 sur vehicules', req('get', MON, maison_user).status_code == 403)
        ok('loueur voiture -> 403 sur logements',
           req('get', '/api/v1/locations/mon-espace/logements/', loueur_user).status_code == 403)
        ok('admin sans capacite -> 403', req('get', ADM, admin_sans).status_code == 403)
        ok('admin avec gerer_locations -> 200', req('get', ADM, admin_avec).status_code == 200)
        ok('super-admin -> 200', req('get', ADM, super_).status_code == 200)
        ok('admin : loueur maison via /vehicules/ -> 404',
           req('get', f'/api/v1/locations/admin/{maison.id}/vehicules/', super_).status_code == 404)

        print('=== 2. CREATION (loueur) ===')
        corps = {'nom': f'Corolla {uid}', 'description': 'Berline propre', 'prix': 25000,
                 'categorie_vehicule': 'voiture', 'marque': 'Toyota', 'modele': 'Corolla', 'annee': 2018,
                 'couleur': 'Gris', 'nb_places': 5, 'boite': 'automatique', 'carburant': 'essence',
                 'climatisation': True, 'equipements': ['gps', 'bluetooth', 'gps'],
                 'chauffeur_disponible': True, 'prix_jour_avec_chauffeur': 35000, 'caution': 100000,
                 'km_inclus_par_jour': 200, 'prix_km_supplementaire': 150, 'carburant_inclus': False,
                 'duree_min_jours': 2, 'zone_circulation': 'Ferké et environs',
                 'localite_id': loc_f.id, 'quartier_id': q_f.id, 'secteur': 'Gare',
                 'adresse_reperes': 'Face à la gare routière', 'latitude': 9.59, 'longitude': -5.19}
        r = req('post', MON, loueur_user, corps)
        ok('POST -> 201', r.status_code == 201, r.content)
        v = r.json()
        vid = v['id']
        attendus = {'id', 'nom', 'prix', 'categorie_vehicule', 'categorie_libelle', 'marque', 'modele', 'annee',
                    'couleur', 'nb_places', 'boite', 'boite_libelle', 'carburant', 'carburant_libelle',
                    'climatisation', 'equipements', 'chauffeur_disponible', 'chauffeur_obligatoire',
                    'prix_jour_avec_chauffeur', 'caution', 'km_inclus_par_jour', 'prix_km_supplementaire',
                    'carburant_inclus', 'duree_min_jours', 'zone_circulation', 'disponibilite',
                    'disponibilite_libelle', 'departement_id', 'departement_nom', 'localite_id', 'localite_nom',
                    'quartier_id', 'quartier_nom', 'secteur', 'adresse_reperes', 'latitude', 'longitude',
                    'images', 'panoramas', 'reservations_confirmees', 'modifie_par_role', 'modifie_par_nom',
                    'modifie_le', 'cree_le'}
        ok('fiche gestion : tous les champs', attendus <= set(v), attendus - set(v))
        ok('libelles', v['categorie_libelle'] == 'Voiture' and v['boite_libelle'] == 'Automatique'
           and v['carburant_libelle'] == 'Essence', v)
        ok('equipements dedoublonnes', v['equipements'] == ['gps', 'bluetooth'], v['equipements'])
        ok('geo : departement/localite/quartier', v['departement_id'] == ferke.id and v['localite_nom'] == loc_f.nom
           and v['quartier_nom'] == q_f.nom, v)
        ok('GPS', abs(v['latitude'] - 9.59) < 1e-6 and abs(v['longitude'] + 5.19) < 1e-6, v)
        ok('tracabilite loueur', v['modifie_par_role'] == 'loueur', v['modifie_par_role'])
        art = Article.objects.get(pk=vid)
        ok('Article type vehicule + mode location', art.type == 'vehicule' and art.vehicule.mode == 'location')
        ok('reservations_confirmees vide', v['reservations_confirmees'] == [])

        print('=== 3. VALIDATIONS ===')
        r = req('post', MON, loueur_user, {**corps, 'equipements': ['jacuzzi']})
        ok('equipement inconnu -> 400', r.status_code == 400 and 'equipements' in r.json()['details'], r.content)
        r = req('post', MON, loueur_user, {**corps, 'categorie_vehicule': 'avion'})
        ok('categorie inconnue -> 400', r.status_code == 400, r.content)
        r = req('post', MON, loueur_user, {**corps, 'chauffeur_disponible': False, 'chauffeur_obligatoire': True})
        ok('chauffeur obligatoire sans chauffeur disponible -> 400',
           r.status_code == 400 and 'chauffeur_obligatoire' in r.json()['details'], r.content)
        r = req('post', MON, loueur_user, {**corps, 'prix_jour_avec_chauffeur': None})
        ok('chauffeur disponible sans prix avec chauffeur -> 400',
           r.status_code == 400 and 'prix_jour_avec_chauffeur' in r.json()['details'], r.content)
        r = req('post', MON, loueur_user, {**corps, 'localite_id': loc_k.id, 'quartier_id': q_k.id})
        ok('incoherence geo (localite hors departement) -> 400', r.status_code == 400, r.content)
        r = req('post', MON, loueur_user, {**corps, 'quartier_id': q_k.id})
        ok('incoherence geo (quartier hors localite) -> 400', r.status_code == 400, r.content)
        r = req('post', MON, loueur_user, {**corps, 'latitude': 9.5, 'longitude': None})
        ok('latitude sans longitude -> 400', r.status_code == 400, r.content)
        r = req('post', MON, loueur_user, {**corps, 'duree_min_jours': 0})
        ok('duree_min_jours 0 -> 400', r.status_code == 400, r.content)

        print('=== 4. MODIFICATION PAR L ADMIN : tracabilite + journal ===')
        avant = JournalModeration.objects.filter(action='loc_vehicule_modif').count()
        r = req('patch', f'{ADM}{vid}/', admin_avec, {'prix': 27000, 'chauffeur_obligatoire': True})
        ok('PATCH admin -> 200', r.status_code == 200, r.content)
        d = r.json()
        ok('prix et chauffeur_obligatoire modifies', int(d['prix']) == 27000 and d['chauffeur_obligatoire'] is True, d)
        ok('tracabilite admin', d['modifie_par_role'] == 'admin', d['modifie_par_role'])
        ok('journal loc_vehicule_modif', JournalModeration.objects.filter(action='loc_vehicule_modif').count() == avant + 1)
        r = req('patch', f'{MON}{vid}/', loueur_user, {'chauffeur_disponible': False})
        ok('PATCH incoherent (obligatoire sans disponible) -> 400', r.status_code == 400, r.content)
        r = req('patch', f'{MON}{vid}/', loueur_user, {'quartier_id': q_k.id})
        ok('PATCH geo incoherent -> 400', r.status_code == 400, r.content)
        ok('autre loueur maison : detail -> 403', req('get', f'{MON}{vid}/', maison_user).status_code == 403)

        print('=== 5. DISPONIBILITE ===')
        r = req('post', f'{MON}{vid}/disponibilite/', loueur_user, {'disponibilite': 'loue'})
        ok('valeur logement (loue) refusee -> 400', r.status_code == 400, r.content)
        avant = JournalModeration.objects.filter(action='loc_vehicule_dispo').count()
        r = req('post', f'{ADM}{vid}/disponibilite/', admin_avec, {'disponibilite': 'indisponible'})
        ok('indisponible (admin) -> 200', r.status_code == 200 and r.json()['disponibilite'] == 'indisponible', r.content)
        ok('journal loc_vehicule_dispo', JournalModeration.objects.filter(action='loc_vehicule_dispo').count() == avant + 1)
        r = req('post', f'{MON}{vid}/disponibilite/', loueur_user, {'disponibilite': 'disponible'})
        ok('disponible (loueur) -> 200, tracabilite loueur', r.status_code == 200
           and r.json()['modifie_par_role'] == 'loueur', r.content)
        r = req('get', MON + '?disponibilite=indisponible', loueur_user)
        ok('filtre liste ?disponibilite=indisponible -> 0', r.json()['resultats'] == [], r.content)

        print('=== 6. IMAGES ET PANORAMAS ===')
        r = req('post', f'{MON}{vid}/images/', loueur_user, multipart={'article': vid, 'image': png('a.png'), 'ordre': 1})
        ok('image loueur -> 201', r.status_code == 201, r.content)
        img_id = r.json()['id']
        r = req('get', f'{ADM}{vid}/images/', admin_avec)
        ok('images listees cote admin', r.status_code == 200 and len(r.json()['results'] if isinstance(r.json(), dict) else r.json()) == 1, r.content)
        ok('image : delete -> 204', req('delete', f'{MON}{vid}/images/{img_id}/', loueur_user).status_code == 204)
        r = req('post', f'{ADM}{vid}/panoramas/', admin_avec,
                multipart={'article': vid, 'image': png('p.png'), 'titre': 'Intérieur', 'type_vue': 'photo_360', 'ordre': 1})
        ok('panorama admin -> 201 (titre/type_vue)', r.status_code == 201 and r.json()['titre'] == 'Intérieur'
           and r.json()['type_vue'] == 'photo_360', r.content)
        pano_id = r.json()['id']
        r = req('get', f'{MON}{vid}/', loueur_user)
        ok('panorama visible dans la fiche', len(r.json()['panoramas']) == 1, r.json()['panoramas'])
        r = req('patch', f'{MON}{vid}/panoramas/{pano_id}/', loueur_user, {'titre': 'Habitacle'})
        ok('panorama PATCH -> 200', r.status_code == 200 and r.json()['titre'] == 'Habitacle', r.content)
        ok('panorama d un vehicule via route logement -> 403',
           req('get', f'/api/v1/locations/mon-espace/logements/{vid}/panoramas/', loueur_user).status_code == 403)

        print('=== 7. RESERVATIONS CONFIRMEES (fiche gestion) + 409 ===')
        auj = timezone.localdate()
        DemandeReservation.objects.create(numero=f'RSV-T-{uid}-1', client=client_user, partenaire=loueur,
            objet=art, nature='reservation', statut='confirmee',
            date_debut=auj + timedelta(days=5), date_fin=auj + timedelta(days=8))
        DemandeReservation.objects.create(numero=f'RSV-T-{uid}-2', client=client_user, partenaire=loueur,
            objet=art, nature='reservation', statut='confirmee',
            date_debut=auj - timedelta(days=10), date_fin=auj - timedelta(days=7))
        DemandeReservation.objects.create(numero=f'RSV-T-{uid}-3', client=client_user, partenaire=loueur,
            objet=art, nature='reservation', statut='nouvelle',
            date_debut=auj + timedelta(days=20), date_fin=auj + timedelta(days=22))
        r = req('get', f'{MON}{vid}/', loueur_user)
        rc = r.json()['reservations_confirmees']
        ok('reservations_confirmees : seule la confirmee a venir', len(rc) == 1
           and rc[0]['date_debut'] == str(auj + timedelta(days=5)) and set(rc[0]) == {'demande_id', 'date_debut', 'date_fin'}, rc)
        r = req('delete', f'{MON}{vid}/', loueur_user)
        ok('DELETE avec demandes -> 409', r.status_code == 409, r.content)

        print('=== 8. SUPPRESSION SANS DEMANDE (admin) ===')
        r = req('post', ADM, super_, {**corps, 'nom': f'Moto {uid}', 'categorie_vehicule': 'moto',
                                       'chauffeur_disponible': False, 'prix_jour_avec_chauffeur': None})
        ok('creation admin -> 201', r.status_code == 201, r.content)
        moto_id = r.json()['id']
        r = req('delete', f'{ADM}{moto_id}/', super_)
        ok('DELETE sans demande -> 204', r.status_code == 204, r.content)
        ok('Article supprime', not Article.objects.filter(pk=moto_id).exists())

        print('=== 9. LISTE ADMIN : type_partenaire + compteurs generiques ===')
        r = req('get', '/api/v1/locations/admin/', admin_avec)
        ok('liste admin -> 200', r.status_code == 200, r.content)
        lignes = {x['id']: x for x in r.json()['resultats']}
        ok('loueur voiture et loueur maison presents', loueur.id in lignes and maison.id in lignes)
        lv = lignes[loueur.id]
        ok('type_partenaire', lv['type_partenaire'] == 'loueur_voiture'
           and lignes[maison.id]['type_partenaire'] == 'loueur_maison', lv)
        ok('compteurs vehicules (1 bien, 1 disponible, 1 demande en attente)',
           lv['nb_biens'] == 1 and lv['nb_disponibles'] == 1 and lv['nb_indisponibles'] == 0
           and lv['demandes_en_attente'] == 1, lv)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
