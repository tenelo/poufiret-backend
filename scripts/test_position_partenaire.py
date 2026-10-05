"""Tests : position GPS du partenaire, écrite par le partenaire (PATCH
mon-profil-partenaire) et par l'admin (création, route position). Validations
(paire, plages), avertissement hors Côte d'Ivoire sans refus, effacement par
null, droits (capacité creer_partenaire), journal des écritures admin,
lecture (profil, liste admin, fiche publique).

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_position_partenaire.py
"""
import json, uuid
from django.db import transaction
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken
from apps.administration.models import JournalModeration, PermissionsAdmin
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

try:
    with transaction.atomic():
        plan = PlanAbonnement.objects.get(libelle='Basique')
        part_user = utilisateur('t_pos_part', role='partenaire')
        part = ProfilPartenaire.objects.create(user=part_user, plan=plan, nom_commerce='Position QA',
                                               type_partenaire='commercant', statut='actif', est_visible=True)
        MON = '/api/v1/auth/mon-profil-partenaire/'

        print('=== 1. PARTENAIRE : ecriture ===')
        r = req('patch', MON, part_user, {'latitude': 9.4, 'longitude': -5.5})
        ok('PATCH lat/lng -> 200', r.status_code == 200, r.content)
        d = r.json()
        ok('lecture : latitude/longitude', abs(d['latitude'] - 9.4) < 1e-6 and abs(d['longitude'] + 5.5) < 1e-6, d)
        ok('traçabilité : position_modifiee_par_role = partenaire', d['position_modifiee_par_role'] == 'partenaire', d)
        ok('traçabilité : position_modifiee_le renseigné', d['position_modifiee_le'] is not None)
        ok('dans la CI : pas d avertissement', d['avertissement_position'] is None, d)

        print('=== 2. VALIDATIONS (partenaire) ===')
        r = req('patch', MON, part_user, {'latitude': 9.4})
        ok('une seule valeur -> 400 (latitude+longitude)', r.status_code == 400 and
           set(r.json()['details']) == {'latitude', 'longitude'}, r.content)
        r = req('patch', MON, part_user, {'latitude': 91, 'longitude': 0})
        ok('latitude > 90 -> 400', r.status_code == 400 and 'latitude' in r.json()['details'], r.content)
        r = req('patch', MON, part_user, {'latitude': 0, 'longitude': 181})
        ok('longitude > 180 -> 400', r.status_code == 400 and 'longitude' in r.json()['details'], r.content)
        r = req('patch', MON, part_user, {'latitude': 'abc', 'longitude': 0})
        ok('valeur non numerique -> 400', r.status_code == 400, r.content)
        part.refresh_from_db()
        ok('aucune ecriture apres les rejets', abs(part.localisation.y - 9.4) < 1e-6)

        print('=== 3. AVERTISSEMENT HORS COTE D IVOIRE (sans refus) ===')
        r = req('patch', MON, part_user, {'latitude': 48.8566, 'longitude': 2.3522})
        ok('Paris -> 200 (pas de refus)', r.status_code == 200, r.content)
        ok('Paris -> avertissement present', r.json()['avertissement_position'] is not None, r.json())

        print('=== 4. EFFACEMENT ===')
        r = req('patch', MON, part_user, {'latitude': None, 'longitude': None})
        ok('null/null -> 200', r.status_code == 200, r.content)
        ok('position effacee', r.json()['latitude'] is None and r.json()['longitude'] is None, r.json())
        part.refresh_from_db()
        ok('localisation nulle en base', part.localisation is None)
        ok('effacement trace : par role partenaire', part.position_modifiee_par_role == 'partenaire')

        print('=== 5. ROUTE ADMIN : position ===')
        admin_sans = utilisateur('t_pos_sans', role='admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans)
        admin_cap = utilisateur('t_pos_cap', role='admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin_cap, creer_partenaire=True)
        super_ = utilisateur('t_pos_super', role='admin', staff=True, superuser=True)
        URL = f'/api/v1/administration/partenaires/{part.id}/position/'
        r = req('patch', URL, admin_sans, {'latitude': 5.3, 'longitude': -4.0})
        ok('sans capacite -> 403', r.status_code == 403, r.content)
        ok('anonyme -> 401/403', req('patch', URL, None, {'latitude': 5.3, 'longitude': -4.0}).status_code in (401, 403))
        r = req('patch', URL, admin_cap, {'latitude': 5.3})
        ok('admin : une seule valeur -> 400', r.status_code == 400 and 'details' in r.json(), r.content)
        r = req('patch', URL, admin_cap, {})
        ok('admin : corps vide -> 400 (requis)', r.status_code == 400, r.content)
        r = req('patch', f'/api/v1/administration/partenaires/999999/position/', admin_cap, {'latitude': 5, 'longitude': -4})
        ok('partenaire inconnu -> 404', r.status_code == 404, r.content)
        r = req('patch', URL, admin_cap, {'latitude': 5.3, 'longitude': -4.0})
        ok('admin avec capacite -> 200', r.status_code == 200, r.content)
        ok('reponse : id, latitude, longitude, role admin, avertissement null',
           r.json()['id'] == part.id and r.json()['position_modifiee_par_role'] == 'admin'
           and r.json()['avertissement_position'] is None, r.json())
        r = req('patch', URL, super_, {'latitude': None, 'longitude': None})
        ok('super-admin : effacement -> 200', r.status_code == 200 and r.json()['latitude'] is None, r.content)
        ok('journal partenaire_position : acteur admin, motif avant → apres',
           JournalModeration.objects.filter(cible=part_user, acteur=super_,
               action=JournalModeration.Action.PARTENAIRE_POSITION, motif__contains=' → ').exists())
        ok('journal : une entree par ecriture admin',
           JournalModeration.objects.filter(cible=part_user, action=JournalModeration.Action.PARTENAIRE_POSITION).count() == 2)
        ok('pas de journal pour une ecriture partenaire',
           not JournalModeration.objects.filter(acteur=part_user, action=JournalModeration.Action.PARTENAIRE_POSITION).exists())

        print('=== 6. CREATION ADMIN AVEC POSITION ===')
        tel = telephone_libre()
        CREER = '/api/v1/auth/partenaires/creer/'
        r = req('post', CREER, admin_cap, {'telephone': tel, 'type_partenaire': 'commercant',
                                            'nom_commerce': 'Creation Pos QA', 'latitude': 5.3})
        ok('creation : une seule valeur -> 400', r.status_code == 400, r.content)
        r = req('post', CREER, admin_cap, {'telephone': tel, 'type_partenaire': 'commercant',
                                            'nom_commerce': 'Creation Pos QA',
                                            'latitude': 5.33, 'longitude': -4.02})
        ok('creation avec position -> 201', r.status_code == 201, r.content)
        ok('creation : avertissement_position present (null dans CI)', 'avertissement_position' in r.json()
           and r.json()['avertissement_position'] is None, r.json())
        cree = ProfilPartenaire.objects.get(user__telephone=tel)
        ok('creation : localisation ecrite', abs(cree.localisation.y - 5.33) < 1e-6)
        ok('creation : traçabilite role admin', cree.position_modifiee_par_role == 'admin')
        ok('creation : journal avec l acteur admin', JournalModeration.objects.filter(
            cible=cree.user, acteur=admin_cap, action=JournalModeration.Action.PARTENAIRE_POSITION).exists())
        tel2 = telephone_libre()
        r = req('post', CREER, admin_cap, {'telephone': tel2, 'type_partenaire': 'commercant',
                                            'nom_commerce': 'Creation sans pos QA'})
        ok('creation sans position -> 201, position null', r.status_code == 201 and
           ProfilPartenaire.objects.get(user__telephone=tel2).localisation is None, r.content)

        print('=== 7. LECTURE : profil, liste admin, fiche publique ===')
        r = req('get', MON, part_user)
        ok('profil : champs position presents', {'latitude', 'longitude', 'position_modifiee_le',
           'position_modifiee_par_role', 'avertissement_position'} <= set(r.json()), r.json().keys())
        r = req('get', '/api/v1/administration/partenaires/liste/', super_)
        lignes = r.json().get('resultats', r.json()) if r.status_code == 200 else []
        ligne = next((x for x in lignes if x['id'] == part.id), None)
        ok('liste admin : latitude/longitude/position_modifiee_*',
           ligne is not None and {'latitude', 'longitude', 'position_modifiee_le', 'position_modifiee_par_role'} <= set(ligne), ligne)
        r = Client().get('/api/v1/restaurants/54/', secure=True, HTTP_HOST=HOST)
        ok('fiche publique : position_modifiee_le et role presents',
           {'latitude', 'longitude', 'position_modifiee_le', 'position_modifiee_par_role'} <= set(r.json()), r.json().keys())

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
