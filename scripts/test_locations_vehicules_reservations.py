"""Tests : demandes de réservation de véhicules (Locations Phase V1,
apps.reservations réutilisé). Visite refusée, date passée, durée minimale,
chauffeur (imposé / indisponible), montant estimé, chevauchement avec une
réservation confirmée (à la création et à la confirmation), disponibilité
globale inchangée à la confirmation, champs ajoutés à l'objet demande
(client, loueur, admin), notification type "reservation". Non-régression
logement : règle M1 (réservé à la confirmation) inchangée.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_locations_vehicules_reservations.py
"""
import json, uuid
from datetime import timedelta
from unittest import mock
from django.db import transaction
from django.test import Client
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken
from apps.catalog.correspondances import categories_correspondantes
from apps.catalog.models import Article, Logement, Vehicule
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

def req(method, url, user=None, corps=None):
    kw = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    if corps is None:
        return getattr(Client(), method)(url, **kw)
    return getattr(Client(), method)(url, json.dumps(corps), content_type='application/json', **kw)

def j(n):
    return str(timezone.localdate() + timedelta(days=n))

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        loueur_user = utilisateur('t_vrsv_loueur', role='partenaire')
        loueur = ProfilPartenaire.objects.create(user=loueur_user, plan=plan, nom_commerce=f'Auto RSV QA {uid}',
            type_partenaire='loueur_voiture', statut='actif', est_visible=True)
        cat = categories_correspondantes('loueur_voiture').first()

        def vehicule(nom, prix, **kw):
            a = Article.objects.create(partenaire=loueur, categorie=cat, nom=nom, slug=uuid.uuid4().hex[:8],
                                       type='vehicule', prix=prix, est_actif=True)
            return Vehicule.objects.create(article=a, mode='location', marque='Toyota', modele=nom, **kw)

        sans = vehicule(f'Sans chauffeur {uid}', 20000, duree_min_jours=2)
        option = vehicule(f'Option chauffeur {uid}', 30000, chauffeur_disponible=True,
                          prix_jour_avec_chauffeur=45000)
        oblig = vehicule(f'Chauffeur obligatoire {uid}', 100000, chauffeur_disponible=True,
                         chauffeur_obligatoire=True, prix_jour_avec_chauffeur=120000)
        indispo = vehicule(f'Indispo {uid}', 10000, disponibilite='indisponible')

        client_user = utilisateur('t_vrsv_client')
        super_ = utilisateur('t_vrsv_super', role='admin', staff=True, superuser=True)
        CREER = '/api/v1/reservations/'

        def creer(objet, **corps):
            return req('post', CREER, client_user, {'objet_id': objet.article_id, 'nature': 'reservation', **corps})

        print('=== 1. REGLES DE VALIDATION ===')
        r = req('post', CREER, client_user, {'objet_id': sans.article_id, 'nature': 'visite',
                                             'date_souhaitee': '2030-01-01T10:00:00Z'})
        ok('visite sur vehicule -> 400 details.nature', r.status_code == 400 and 'nature' in r.json()['details'], r.content)
        r = creer(sans, date_debut=j(-1), date_fin=j(3))
        ok('date_debut passee -> 400', r.status_code == 400 and 'date_debut' in r.json()['details'], r.content)
        r = creer(sans, date_debut=j(1), date_fin=j(2))
        ok('duree < duree_min_jours (1 < 2) -> 400', r.status_code == 400 and 'date_fin' in r.json()['details'], r.content)
        r = creer(sans, date_debut=j(1), date_fin=j(3), avec_chauffeur=True)
        ok('avec_chauffeur sans chauffeur disponible -> 400',
           r.status_code == 400 and 'avec_chauffeur' in r.json()['details'], r.content)
        r = creer(oblig, date_debut=j(1), date_fin=j(3), avec_chauffeur=False)
        ok('sans chauffeur alors que chauffeur obligatoire -> 400',
           r.status_code == 400 and 'avec_chauffeur' in r.json()['details'], r.content)
        r = creer(indispo, date_debut=j(1), date_fin=j(3))
        ok('vehicule indisponible -> 400', r.status_code == 400, r.content)

        print('=== 2. MONTANT ESTIME ET CHAMPS AJOUTES ===')
        r = creer(sans, date_debut=j(0), date_fin=j(3), lieu_prise_en_charge='Gare routière')
        ok("aujourd'hui accepte, 3 jours sans chauffeur -> 201", r.status_code == 201, r.content)
        d = r.json()
        ok('montant = 3 x 20000', int(d['montant_estime']) == 60000, d['montant_estime'])
        ok('avec_chauffeur = false, lieu, objet_type vehicule', d['avec_chauffeur'] is False
           and d['lieu_prise_en_charge'] == 'Gare routière' and d['objet_type'] == 'vehicule', d)
        r = creer(option, date_debut=j(5), date_fin=j(9), avec_chauffeur=True)
        ok('option chauffeur : montant = 4 x 45000', r.status_code == 201 and int(r.json()['montant_estime']) == 180000, r.content)
        r = creer(option, date_debut=j(5), date_fin=j(9))
        ok('option non choisie : montant = 4 x 30000', r.status_code == 201
           and int(r.json()['montant_estime']) == 120000 and r.json()['avec_chauffeur'] is False, r.content)
        r = creer(oblig, date_debut=j(2), date_fin=j(4))
        ok('chauffeur obligatoire impose : avec_chauffeur=true, montant = 2 x 120000', r.status_code == 201
           and r.json()['avec_chauffeur'] is True and int(r.json()['montant_estime']) == 240000, r.content)

        print('=== 3. CONFIRMATION : disponibilite globale inchangee, notification ===')
        demande = DemandeReservation.objects.filter(objet=sans.article).first()
        with mock.patch('apps.reservations.services.notifier_utilisateur') as notif:
            r = req('post', f'/api/v1/reservations/{demande.id}/transition/', loueur_user, {'action': 'confirmee'})
        ok('loueur confirme -> 200', r.status_code == 200, r.content)
        ok('push client type "reservation"', any(c.kwargs.get('data', {}).get('type') == 'reservation'
                                               for c in notif.call_args_list), notif.call_args_list)
        sans.refresh_from_db()
        ok('disponibilite globale du vehicule inchangee', sans.disponibilite == 'disponible', sans.disponibilite)
        r = req('get', '/api/v1/reservations/mon-espace/', loueur_user)
        ligne = next(x for x in r.json()['results'] if x['id'] == demande.id)
        ok('objet demande (loueur) : champs V1', {'avec_chauffeur', 'lieu_prise_en_charge', 'montant_estime',
                                                 'objet_type'} <= set(ligne), ligne)
        r = req('get', f'/api/v1/reservations/admin/demandes/{demande.id}/', super_)
        ok('objet demande (admin) : champs V1', r.status_code == 200 and int(r.json()['montant_estime']) == 60000
           and r.json()['objet_type'] == 'vehicule', r.content)

        print('=== 4. CHEVAUCHEMENT ===')
        r = creer(sans, date_debut=j(2), date_fin=j(5))
        ok('chevauchement avec confirmee -> 400', r.status_code == 400, r.content)
        msg = r.json()['details']['date_debut'][0]
        deb = (timezone.localdate()).strftime('%d/%m/%Y')
        fin = (timezone.localdate() + timedelta(days=3)).strftime('%d/%m/%Y')
        ok('message clair avec la periode occupee', deb in msg and fin in msg, msg)
        r = creer(sans, date_debut=j(3), date_fin=j(5))
        ok('prise en charge le jour de restitution -> 201', r.status_code == 201, r.content)
        r = creer(sans, date_debut=j(1), date_fin=j(3))
        ok('periode incluse -> 400', r.status_code == 400, r.content)

        print('=== 5. DOUBLE CONFIRMATION SUR LES MEMES DATES ===')
        d1, d2 = DemandeReservation.objects.filter(objet=option.article).order_by('id')[:2]
        r = req('post', f'/api/v1/reservations/admin/demandes/{d1.id}/transition/', super_, {'action': 'confirmee'})
        ok('1re confirmation -> 200', r.status_code == 200, r.content)
        r = req('post', f'/api/v1/reservations/admin/demandes/{d2.id}/transition/', super_, {'action': 'confirmee'})
        ok('2e confirmation qui chevauche -> 400', r.status_code == 400 and 'déjà réservé' in r.json()['message'], r.content)
        d2.refresh_from_db()
        ok('2e demande reste nouvelle', d2.statut == 'nouvelle', d2.statut)

        print('=== 6. NON-REGRESSION LOGEMENT (regle M1) ===')
        maison = ProfilPartenaire.objects.create(user=utilisateur('t_vrsv_maison', 'partenaire'), plan=plan,
            nom_commerce=f'Maison RSV {uid}', type_partenaire='loueur_maison', statut='actif', est_visible=True)
        a = Article.objects.create(partenaire=maison, categorie=categories_correspondantes('loueur_maison').first(),
                                   nom=f'Villa {uid}', slug=uuid.uuid4().hex[:8], type='logement', prix=100000)
        log = Logement.objects.create(article=a, type_logement='villa')
        r = req('post', CREER, client_user, {'objet_id': a.id, 'nature': 'reservation',
                                             'date_debut': j(-30), 'date_fin': j(-20)})
        ok('logement : aucune regle vehicule (dates libres comme en M1), montant null',
           r.status_code == 201 and r.json()['montant_estime'] is None and r.json()['avec_chauffeur'] is None
           and r.json()['objet_type'] == 'logement', r.content)
        r = req('post', f'/api/v1/reservations/admin/demandes/{r.json()["id"]}/transition/', super_, {'action': 'confirmee'})
        log.refresh_from_db()
        ok('logement confirme -> reserve (M1 inchange)', r.status_code == 200 and log.disponibilite == 'reserve',
           log.disponibilite)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
