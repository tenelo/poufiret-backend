"""Tests : espace loueur/admin des logements (Locations Phase M1).
Droits (403, super-admin, gerer_locations), CRUD logement (Article+Logement
en une ressource), cohérence géographique (400), images, panoramas
(type_vue/titre), disponibilité, traçabilité, journal, suppression protégée.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_locations_gestion.py
"""
import io, json, uuid
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client
from PIL import Image
from rest_framework_simplejwt.tokens import AccessToken
from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.catalog.models import Article, Logement, Panorama
from apps.geo.models import Departement, Localite, Quartier
from apps.reservations.models import DemandeReservation, HistoriqueDemande
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

def req(method, url, user=None, corps=None):
    kw = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    c = Client()
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
        loc_f = Localite.objects.create(nom=f'Loc Ferke {uid}', departement=ferke)
        loc_k = Localite.objects.create(nom=f'Loc Kong {uid}', departement=kong)
        q_f = Quartier.objects.create(nom=f'Q Ferke {uid}', localite=loc_f)
        q_k = Quartier.objects.create(nom=f'Q Kong {uid}', localite=loc_k)

        loueur_user = utilisateur('t_loc_loueur', role='partenaire')
        loueur = ProfilPartenaire.objects.create(user=loueur_user, plan=plan, nom_commerce=f'Loueur QA {uid}',
            type_partenaire='loueur_maison', statut='actif', est_visible=True, departement=ferke)
        super_ = utilisateur('t_loc_super', role='admin', staff=True, superuser=True)
        admin_sans = utilisateur('t_loc_sans', role='admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans)
        admin_avec = utilisateur('t_loc_avec', role='admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin_avec, gerer_locations=True)

        MON = '/api/v1/locations/mon-espace/logements/'
        ADM = f'/api/v1/locations/admin/{loueur.id}/logements/'

        print('=== 1. DROITS ===')
        ok('loueur : GET mon-espace -> 200', req('get', MON, loueur_user).status_code == 200)
        ok('admin sans capacite -> 403', req('get', ADM, admin_sans).status_code == 403)
        ok('anonyme -> 401/403', req('get', ADM).status_code in (401, 403))
        ok('super-admin -> 200', req('get', ADM, super_).status_code == 200)
        ok('admin avec capacite -> 200', req('get', ADM, admin_avec).status_code == 200)
        autre_user = utilisateur('t_loc_autre', role='partenaire')
        autre = ProfilPartenaire.objects.create(user=autre_user, plan=plan, nom_commerce=f'Autre type {uid}',
            type_partenaire='commercant', statut='actif', est_visible=True, departement=ferke)
        ok('type de partenaire incorrect -> 403 (mon-espace)',
           req('get', MON, autre_user).status_code == 403)

        print('=== 2. CREATION (loueur) ===')
        corps = {'nom': f'Villa QA {uid}', 'description': 'Belle villa', 'prix': 150000,
                 'type_logement': 'villa', 'nb_chambres': 3, 'nb_salons': 1, 'nb_salles_de_bain': 2,
                 'meuble': True, 'caution_mois': 2, 'avance_mois': 1, 'frais_agence': 50000,
                 'compteur_eau_individuel': True, 'equipements': ['climatisation', 'parking'],
                 'localite_id': loc_f.id, 'quartier_id': q_f.id, 'secteur': 'Centre'}
        r = req('post', MON, loueur_user, corps)
        ok('POST logement -> 201', r.status_code == 201, r.content)
        v = r.json()
        ok('champs ecrits corrects', v['nom'] == f'Villa QA {uid}' and v['nb_salles_de_bain'] == 2
           and v['nb_salons'] == 1 and v['equipements'] == ['climatisation', 'parking'], v)
        ok('disponibilite par defaut = disponible', v['disponibilite'] == 'disponible', v)
        ok('traçabilite : modifie_par_role = loueur', v['modifie_par_role'] == 'loueur', v)
        ok('localite_nom / quartier_nom', v['localite_nom'] == loc_f.nom and v['quartier_nom'] == q_f.nom, v)
        logement_id = v['id']
        ok('Article.type = logement', Article.objects.get(pk=logement_id).type == 'logement')

        print('=== 3. VALIDATIONS ===')
        r = req('post', MON, loueur_user, {'nom': 'x', 'prix': 1000, 'type_logement': 'zzz'})
        ok('type_logement invalide -> 400', r.status_code == 400, r.content)
        r = req('post', MON, loueur_user, {'nom': 'x', 'prix': 1000, 'type_logement': 'studio',
                                           'equipements': ['piscine', 'inconnu']})
        ok('equipement hors referentiel -> 400', r.status_code == 400, r.content)
        r = req('post', MON, loueur_user, {'prix': 1000, 'type_logement': 'studio'})
        ok('nom manquant -> 400', r.status_code == 400, r.content)

        print('=== 4. COHERENCE GEOGRAPHIQUE ===')
        r = req('patch', f'{MON}{logement_id}/', loueur_user, {'localite_id': loc_k.id})
        ok('localite hors departement du loueur -> 400 details.localite_id',
           r.status_code == 400 and 'localite_id' in r.json()['details'], r.content)
        r = req('patch', f'{MON}{logement_id}/', loueur_user, {'quartier_id': q_k.id})
        ok('quartier hors localite -> 400 details.quartier_id',
           r.status_code == 400 and 'quartier_id' in r.json()['details'], r.content)
        r = req('patch', f'{MON}{logement_id}/', loueur_user, {'latitude': 9.4})
        ok('latitude sans longitude -> 400', r.status_code == 400, r.content)
        r = req('patch', f'{MON}{logement_id}/', loueur_user, {'latitude': 9.4, 'longitude': -5.5})
        ok('lat/lng coherents -> 200', r.status_code == 200 and abs(r.json()['latitude'] - 9.4) < 1e-6, r.content)

        print('=== 5. PATCH PARTIEL ET DISPONIBILITE ===')
        r = req('patch', f'{MON}{logement_id}/', loueur_user, {'prix': 160000, 'meuble': False})
        ok('PATCH article+logement combines -> 200', r.status_code == 200 and float(r.json()['prix']) == 160000
           and r.json()['meuble'] is False, r.content)
        r = req('post', f'{MON}{logement_id}/disponibilite/', loueur_user, {'disponibilite': 'loue'})
        ok('disponibilite -> loue', r.status_code == 200 and r.json()['disponibilite'] == 'loue', r.content)
        r = req('post', f'{MON}{logement_id}/disponibilite/', loueur_user, {'disponibilite': 'zzz'})
        ok('disponibilite invalide -> 400', r.status_code == 400, r.content)
        req('post', f'{MON}{logement_id}/disponibilite/', loueur_user, {'disponibilite': 'disponible'})

        print('=== 6. ADMIN : edition a la place du loueur, traçabilite et journal ===')
        r = req('patch', f'{ADM}{logement_id}/', admin_avec, {'description': 'Modifie par admin'})
        ok('admin PATCH -> 200', r.status_code == 200, r.content)
        ok('traçabilite : modifie_par_role = admin', r.json()['modifie_par_role'] == 'admin', r.json())
        ok('journal : loc_logement_modif', JournalModeration.objects.filter(
            cible=loueur_user, action=JournalModeration.Action.LOC_LOGEMENT_MODIF).exists())
        req('post', f'{ADM}{logement_id}/disponibilite/', admin_avec, {'disponibilite': 'reserve'})
        ok('journal : loc_dispo_modif', JournalModeration.objects.filter(
            cible=loueur_user, action=JournalModeration.Action.LOC_DISPO_MODIF).exists())
        req('post', f'{ADM}{logement_id}/disponibilite/', admin_avec, {'disponibilite': 'disponible'})

        print('=== 7. IMAGES ===')
        c = Client()
        r = c.post(f'{MON}{logement_id}/images/',
                   {'article': logement_id, 'image': png('img1.png'), 'est_principale': 'true'},
                   secure=True, HTTP_HOST=HOST, HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(loueur_user)}')
        ok('POST image -> 201', r.status_code == 201, r.content)
        r = req('get', f'{MON}{logement_id}/', loueur_user)
        ok('image presente dans la fiche', len(r.json()['images']) == 1, r.json()['images'])

        print('=== 8. PANORAMAS (visite immersive) ===')
        c = Client()
        r = c.post(f'{MON}{logement_id}/panoramas/',
                   {'article': logement_id, 'image': png('pano1.png'), 'titre': 'Salon', 'type_vue': 'photo_360'},
                   secure=True, HTTP_HOST=HOST, HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(loueur_user)}')
        ok('POST panorama -> 201', r.status_code == 201, r.content)
        pano = r.json()
        ok('titre et type_vue restitues', pano['titre'] == 'Salon' and pano['type_vue'] == 'photo_360', pano)
        ok('stocke sur nom_piece (pas de duplication)', Panorama.objects.get(pk=pano['id']).nom_piece == 'Salon')
        r = req('get', f'{MON}{logement_id}/', loueur_user)
        ok('panorama present dans la fiche', len(r.json()['panoramas']) == 1 and r.json()['panoramas'][0]['titre'] == 'Salon')

        print('=== 9. SUPPRESSION : protegee si demandes, sinon 204 ===')
        plat2 = req('post', MON, loueur_user, {'nom': f'Studio QA {uid}', 'prix': 50000, 'type_logement': 'studio'}).json()
        client_user = utilisateur('t_loc_client', role='client')
        DemandeReservation.objects.create(
            numero=f'RSVTEST{uid}', client=client_user, partenaire=loueur,
            objet_id=plat2['id'], nature='visite', statut='nouvelle')
        r = req('delete', f'{MON}{plat2["id"]}/', loueur_user)
        ok('suppression protegee (demande liee) -> 409', r.status_code == 409, r.content)
        r = req('delete', f'{MON}{logement_id}/', loueur_user)
        ok('suppression sans demande -> 204', r.status_code == 204, r.content)
        ok('logement et article supprimes', not Article.objects.filter(pk=logement_id).exists())

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
