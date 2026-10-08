"""Tests : demandes de réservation d'hébergements (Locations Phase V2,
apps.reservations réutilisé). Visite refusée, arrivée passée, durée
minimale, capacité (adultes/enfants × unités), unités disponibles
(chevauchements avec les confirmées, pic par nuit), contrôle à la
confirmation, montant estimé (nuit / semaine / mois × unités),
disponibilité globale inchangée, champs ajoutés à l'objet demande,
notification type "reservation". Non-régression véhicule/logement.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_locations_hebergements_reservations.py
"""
import json, uuid
from datetime import timedelta
from unittest import mock
from django.db import transaction
from django.test import Client
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken
from apps.catalog.correspondances import categories_correspondantes
from apps.catalog.models import Article, Hebergement, Logement
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
        hotel_user = utilisateur('t_hrsv_hotel', role='partenaire')
        hotel = ProfilPartenaire.objects.create(user=hotel_user, plan=plan, nom_commerce=f'Hôtel RSV {uid}',
            type_partenaire='hotelier', statut='actif', est_visible=True)
        cat = categories_correspondantes('hotelier').first()

        def hebergement(nom, prix, **kw):
            a = Article.objects.create(partenaire=hotel, categorie=cat, nom=nom, slug=uuid.uuid4().hex[:8],
                                       type='hebergement', prix=prix, est_actif=True)
            return Hebergement.objects.create(article=a, type_hebergement='chambre_double', **kw)

        chambre = hebergement(f'Double {uid}', 20000, nb_unites=3, capacite_adultes=2, capacite_enfants=1,
                              duree_min_nuits=2, prix_semaine=100000)
        residence = hebergement(f'Studio {uid}', 25000, nb_unites=1, capacite_adultes=2,
                                prix_semaine=150000, prix_mois=500000)
        nuit_seule = hebergement(f'Simple {uid}', 10000, nb_unites=1)
        indispo = hebergement(f'Indispo {uid}', 10000, disponibilite='indisponible')

        client_user = utilisateur('t_hrsv_client')
        super_ = utilisateur('t_hrsv_super', role='admin', staff=True, superuser=True)
        CREER = '/api/v1/reservations/'

        def creer(h, **corps):
            return req('post', CREER, client_user, {'objet_id': h.article_id, 'nature': 'reservation', **corps})

        def erreur(r):
            return set(r.json().get('details', {})) if r.status_code == 400 else r.status_code

        print('=== 1. REGLES DE VALIDATION ===')
        r = req('post', CREER, client_user, {'objet_id': chambre.article_id, 'nature': 'visite',
                                             'date_souhaitee': '2030-01-01T10:00:00Z'})
        ok('visite -> 400 details.nature', erreur(r) == {'nature'}, r.content)
        ok('arrivee passee -> 400', erreur(creer(chambre, date_debut=j(-1), date_fin=j(2))) == {'date_debut'})
        ok('depart = arrivee (0 nuit) -> 400', erreur(creer(chambre, date_debut=j(1), date_fin=j(1))) == {'date_fin'})
        ok('1 nuit < duree_min_nuits (2) -> 400',
           erreur(creer(chambre, date_debut=j(1), date_fin=j(2))) == {'date_fin'})
        ok('3 adultes pour 1 unite (capacite 2) -> 400',
           erreur(creer(chambre, date_debut=j(1), date_fin=j(3), nb_adultes=3)) == {'nb_adultes'})
        ok('2 enfants pour 1 unite (capacite 1) -> 400',
           erreur(creer(chambre, date_debut=j(1), date_fin=j(3), nb_enfants=2)) == {'nb_enfants'})
        ok('4 unites > 3 -> 400 details.nb_unites',
           erreur(creer(chambre, date_debut=j(1), date_fin=j(3), nb_unites=4)) == {'nb_unites'})
        ok('hebergement indisponible -> 400', erreur(creer(indispo, date_debut=j(1), date_fin=j(2))) == {'objet_id'})

        print('=== 2. CREATION, CAPACITE x UNITES, MONTANT ===')
        r = creer(chambre, date_debut=j(0), date_fin=j(3), nb_adultes=4, nb_enfants=2, nb_unites=2)
        ok("arrivee aujourd'hui, 4 adultes + 2 enfants sur 2 unites -> 201", r.status_code == 201, r.content)
        d = r.json()
        ok('champs V2 + objet_type', d['nb_adultes'] == 4 and d['nb_enfants'] == 2 and d['nb_unites'] == 2
           and d['objet_type'] == 'hebergement', d)
        ok('montant = 3 nuits x 20000 x 2 unites', int(d['montant_estime']) == 120000, d['montant_estime'])
        r = creer(chambre, date_debut=j(10), date_fin=j(19))
        ok('9 nuits = 1 semaine + 2 nuits : 100000 + 2 x 20000, defauts adultes=1 enfants=0 unites=1',
           r.status_code == 201 and int(r.json()['montant_estime']) == 140000 and r.json()['nb_adultes'] == 1
           and r.json()['nb_enfants'] == 0 and r.json()['nb_unites'] == 1, r.content)
        r = creer(residence, date_debut=j(1), date_fin=j(40))
        ok('39 nuits = 1 mois + 1 semaine + 2 nuits : 500000 + 150000 + 50000',
           r.status_code == 201 and int(r.json()['montant_estime']) == 700000, r.content)
        r = creer(nuit_seule, date_debut=j(1), date_fin=j(9))
        ok('sans tarif semaine : 8 nuits x 10000', r.status_code == 201
           and int(r.json()['montant_estime']) == 80000, r.content)

        print('=== 3. CONFIRMATION : disponibilite globale inchangee, notification ===')
        d1 = DemandeReservation.objects.get(pk=d['id'])
        with mock.patch('apps.reservations.services.notifier_utilisateur') as notif:
            r = req('post', f'/api/v1/reservations/{d1.id}/transition/', hotel_user, {'action': 'confirmee'})
        ok('hotelier confirme -> 200', r.status_code == 200, r.content)
        ok('push type "reservation"', any(c.kwargs.get('data', {}).get('type') == 'reservation'
                                        for c in notif.call_args_list))
        chambre.refresh_from_db()
        ok('disponibilite globale inchangee', chambre.disponibilite == 'disponible')
        r = req('get', f'/api/v1/reservations/admin/demandes/{d1.id}/', super_)
        ok('objet demande (admin) : nb_adultes/nb_enfants/nb_unites', r.status_code == 200
           and {'nb_adultes', 'nb_enfants', 'nb_unites'} <= set(r.json()), r.content)
        r = req('get', '/api/v1/reservations/mes-demandes/', client_user)
        ok('objet demande (client) : champs V2', {'nb_adultes', 'nb_enfants', 'nb_unites'} <= set(r.json()['results'][0]))

        print('=== 4. UNITES ET CHEVAUCHEMENTS (2 unites confirmees sur [j0,j3[) ===')
        ok('2 unites sur [j1,j3[ -> 400 (1 seule restante)',
           erreur(creer(chambre, date_debut=j(1), date_fin=j(3), nb_unites=2)) == {'nb_unites'})
        r = creer(chambre, date_debut=j(1), date_fin=j(3), nb_unites=1)
        ok('1 unite sur [j1,j3[ -> 201', r.status_code == 201, r.content)
        d_a = r.json()['id']
        r = creer(chambre, date_debut=j(2), date_fin=j(5), nb_unites=1)
        ok('1 unite sur [j2,j5[ -> 201 (encore 1 unite tant que la precedente n est pas confirmee)',
           r.status_code == 201, r.content)
        d_b = r.json()['id']
        r = creer(chambre, date_debut=j(3), date_fin=j(5), nb_unites=3)
        ok('3 unites a partir du jour de depart -> 201', r.status_code == 201, r.content)
        d_c = r.json()['id']
        r = req('post', f'/api/v1/reservations/admin/demandes/{d_a}/transition/', super_, {'action': 'confirmee'})
        ok('confirmation de la 1re (derniere unite) -> 200', r.status_code == 200, r.content)
        ok('complet sur [j1,j3[ -> 400 message clair',
           'Complet' in creer(chambre, date_debut=j(1), date_fin=j(3)).json()['details']['nb_unites'][0])
        r = req('post', f'/api/v1/reservations/admin/demandes/{d_b}/transition/', super_, {'action': 'confirmee'})
        ok('confirmation qui depasse les unites -> 400', r.status_code == 400
           and 'unité' in r.json()['message'], r.content)
        ok('demande restee nouvelle', DemandeReservation.objects.get(pk=d_b).statut == 'nouvelle')
        r = req('post', f'/api/v1/reservations/admin/demandes/{d_c}/transition/', super_, {'action': 'confirmee'})
        ok('3 unites a partir du depart des autres -> confirmable', r.status_code == 200, r.content)
        dispo = req('get', f'/api/v1/locations/hebergements/{chambre.article_id}/disponibilite/'
                           f'?date_debut={j(0)}&date_fin={j(5)}').json()['unites_disponibles']
        ok('disponibilite publique coherente sur [j0,j5[ -> 0', dispo == 0, dispo)

        print('=== 5. NON-REGRESSION AUTRES BIENS ===')
        maison = ProfilPartenaire.objects.create(user=utilisateur('t_hrsv_maison', 'partenaire'), plan=plan,
            nom_commerce=f'Maison {uid}', type_partenaire='loueur_maison', statut='actif', est_visible=True)
        a = Article.objects.create(partenaire=maison, categorie=categories_correspondantes('loueur_maison').first(),
                                   nom=f'Villa {uid}', slug=uuid.uuid4().hex[:8], type='logement', prix=100000)
        log = Logement.objects.create(article=a, type_logement='villa')
        r = req('post', CREER, client_user, {'objet_id': a.id, 'nature': 'reservation', 'date_debut': j(1),
                                             'date_fin': j(5), 'nb_unites': 4, 'nb_adultes': 9})
        ok('logement : champs hebergement ignores (nb_unites=1, adultes null)', r.status_code == 201
           and r.json()['nb_unites'] == 1 and r.json()['nb_adultes'] is None, r.content)
        req('post', f'/api/v1/reservations/admin/demandes/{r.json()["id"]}/transition/', super_, {'action': 'confirmee'})
        log.refresh_from_db()
        ok('logement confirme -> reserve (M1 inchange)', log.disponibilite == 'reserve', log.disponibilite)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
