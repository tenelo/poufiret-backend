"""Tests : PUT des horaires restaurant (mon-restaurant/ et admin/<id>/).
Deux formes acceptées (liste brute comme le GET, ou {"horaires": [...]}),
corps invalide → 400 {"erreur", "details"} jamais 500, jours fermés avec
heures vides ("" / null), tout-ou-rien, journal admin.

Autonome : crée son propre restaurant et ses comptes. Transaction annulée.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_restaurants_horaires.py
"""
import json, uuid
from django.db import transaction
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken
from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.users.models import HoraireOuverture, PlanAbonnement, ProfilPartenaire, User

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

def put(url, user, corps, brut=False):
    """brut=True : corps envoyé tel quel (chaîne), pour tester un JSON non objet/liste."""
    return Client(raise_request_exception=False).put(
        url, corps if brut else json.dumps(corps), content_type='application/json', secure=True,
        HTTP_HOST=HOST, HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')

def get(url, user):
    return Client().get(url, secure=True, HTTP_HOST=HOST,
                        HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')

def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel

def utilisateur(username, role, staff=False):
    return User.objects.create(telephone=telephone_libre(), username=username, role=role,
                               est_verifie=True, is_staff=staff)

def semaine(pa):
    return {h.jour_semaine: h for h in HoraireOuverture.objects.filter(partenaire=pa)}

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        pa = ProfilPartenaire.objects.create(
            user=utilisateur(f't_hor_resto_{uid}', 'partenaire'), plan=plan,
            nom_commerce=f'Resto horaires QA {uid}', type_partenaire='restaurateur', statut='actif')
        admin_avec = utilisateur(f't_hor_admin_{uid}', 'admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin_avec, gerer_restaurants=True)
        admin_sans = utilisateur(f't_hor_sans_{uid}', 'admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans)
        MON = '/api/v1/restaurants/mon-restaurant/horaires/'
        ADM = f'/api/v1/restaurants/admin/{pa.id}/horaires/'

        print('=== 1. LISTE BRUTE (meme forme que le GET) ===')
        r = get(ADM, admin_avec)
        ok('GET initial -> liste brute vide', r.status_code == 200 and r.json() == [], r.content)
        liste = [
            {'jour_semaine': 0, 'ouvert': True, 'heure_ouverture': '08:00', 'heure_fermeture': '22:00',
             'pause_debut': '14:00', 'pause_fin': '15:00', 'note': 'Midi et soir'},
            {'jour_semaine': 1, 'ouvert': True, 'heure_ouverture': '08:00', 'heure_fermeture': '22:00'},
        ]
        avant_journal = JournalModeration.objects.filter(cible=pa.user, action='resto_fiche_modif').count()
        r = put(ADM, admin_avec, liste)
        ok('PUT admin liste brute -> 200 (etait 500)', r.status_code == 200, r.content)
        ok('reponse = liste brute des horaires (meme forme que le GET)',
           isinstance(r.json(), list) and [h['jour_semaine'] for h in r.json()] == [0, 1], r.json())
        lundi = semaine(pa)[0]
        ok('valeurs enregistrees', str(lundi.heure_ouverture) == '08:00:00'
           and str(lundi.pause_fin) == '15:00:00' and lundi.note == 'Midi et soir')
        ok('journal admin resto_fiche_modif', JournalModeration.objects.filter(
            cible=pa.user, action='resto_fiche_modif').count() == avant_journal + 1)
        r = put(ADM, admin_avec, get(ADM, admin_avec).json())
        ok('aller-retour : PUT du GET tel quel -> 200', r.status_code == 200, r.content)
        r = put(MON, pa.user, [{'jour_semaine': 2, 'ouvert': True,
                                'heure_ouverture': '09:00', 'heure_fermeture': '21:00'}])
        ok('PUT restaurateur liste brute -> 200', r.status_code == 200 and 2 in semaine(pa), r.content)

        print('=== 2. OBJET {"horaires": [...]} (forme historique) ===')
        r = put(MON, pa.user, {'horaires': [
            {'jour_semaine': 0, 'ouvert': True, 'heure_ouverture': '11:00', 'heure_fermeture': '23:00'}]})
        ok('PUT restaurateur objet -> 200', r.status_code == 200, r.content)
        ok('upsert : lundi mis a jour, mardi intact',
           str(semaine(pa)[0].heure_ouverture) == '11:00:00'
           and str(semaine(pa)[1].heure_ouverture) == '08:00:00')
        r = put(ADM, admin_avec, {'horaires': [{'jour_semaine': 3, 'ouvert': True,
                                                'heure_ouverture': '10:00', 'heure_fermeture': '20:00'}]})
        ok('PUT admin objet -> 200', r.status_code == 200 and 3 in semaine(pa), r.content)
        ok('liste vide -> 200, rien change', put(MON, pa.user, []).status_code == 200
           and len(semaine(pa)) == 4)

        print('=== 3. JOURS FERMES AVEC HEURES VIDES ===')
        r = put(ADM, admin_avec, [
            {'jour_semaine': 5, 'ouvert': False, 'heure_ouverture': '', 'heure_fermeture': '',
             'pause_debut': '', 'pause_fin': '', 'note': ''},
            {'jour_semaine': 6, 'ouvert': False, 'heure_ouverture': None, 'heure_fermeture': None,
             'pause_debut': None, 'pause_fin': None, 'note': None},
            {'jour_semaine': 4, 'ouvert': False},
        ])
        ok('jours fermes, heures "" / null / absentes -> 200', r.status_code == 200, r.content)
        s = semaine(pa)
        ok('heures enregistrees a null, ferme', all(
            not s[j].ouvert and s[j].heure_ouverture is None and s[j].heure_fermeture is None
            and s[j].pause_debut is None and s[j].note == '' for j in (4, 5, 6)))
        r = put(MON, pa.user, {'horaires': [{'jour_semaine': 1, 'ouvert': True, 'heure_ouverture': '08:00',
                                             'heure_fermeture': '22:00', 'pause_debut': '', 'pause_fin': ''}]})
        ok('jour ouvert sans pause ("" ) -> 200, pause effacee',
           r.status_code == 200 and semaine(pa)[1].pause_debut is None, r.content)

        print('=== 4. CORPS INVALIDES -> 400, jamais 500, rien ecrit ===')
        avant = {j: (h.ouvert, h.heure_ouverture) for j, h in semaine(pa).items()}
        cas = [
            ('objet sans "horaires"', {'autre': 1}, False),
            ('horaires non liste', {'horaires': 'lundi'}, False),
            ('nombre', 42, False),
            ('chaine JSON', '"texte"', True),
            ('element non objet', ['lundi'], False),
            ('jour_semaine absent', [{'ouvert': True}], False),
            ('jour_semaine 7', [{'jour_semaine': 7}], False),
            ('jour_semaine texte', [{'jour_semaine': 'lundi'}], False),
            ('heure invalide', [{'jour_semaine': 0, 'heure_ouverture': '25:99'}], False),
            ('ouvert invalide', [{'jour_semaine': 0, 'ouvert': 'peut-etre'}], False),
            ('jour en double', [{'jour_semaine': 0}, {'jour_semaine': 0}], False),
            ('note trop longue', [{'jour_semaine': 0, 'note': 'x' * 201}], False),
            ('JSON malforme', '[{"jour_semaine": 0,', True),
        ]
        for libelle, corps, brut in cas:
            for url, user in ((ADM, admin_avec), (MON, pa.user)):
                r = put(url, user, corps, brut=brut)
                corps_json = r.json() if r.status_code == 400 else {}
                ok(f'{libelle} ({"admin" if url == ADM else "restaurateur"}) -> 400 erreur/details',
                   r.status_code == 400 and corps_json.get('erreur') is True
                   and corps_json.get('details') is not None, (r.status_code, r.content[:200]))
        r = put(ADM, admin_avec, [{'jour_semaine': 2, 'ouvert': False},
                                  {'jour_semaine': 0, 'heure_ouverture': 'xx'}])
        ok('lot partiellement invalide -> 400', r.status_code == 400)
        ok('tout ou rien : aucun jour modifie', {j: (h.ouvert, h.heure_ouverture)
                                                 for j, h in semaine(pa).items()} == avant)

        print('=== 5. DROITS ===')
        ok('admin sans gerer_restaurants -> 403', put(ADM, admin_sans, liste).status_code == 403)
        ok('client -> 403 sur mon-restaurant', put(MON, utilisateur(f't_hor_cli_{uid}', 'client'),
                                                   liste).status_code == 403)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
