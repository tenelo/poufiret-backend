"""Tests : finitions Locations M1 — departement_id/departement_nom sur la
fiche logement (déduits de la localité), transitions_possibles dans le
détail admin et dans mon-espace/ (loueur), valeurs exactes des push.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_locations_reservations_finitions.py
"""
import json, uuid
from django.db import transaction
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken
from apps.administration.models import PermissionsAdmin
from apps.catalog.models import Article, Logement
from apps.catalog.correspondances import categories_correspondantes
from apps.geo.models import Departement, Localite
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
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        ferke = Departement.objects.get(nom='Ferké')
        loc_f = Localite.objects.create(nom=f'Fin Ferke {uid}', departement=ferke)

        loueur_user = utilisateur('t_fin_loueur', role='partenaire')
        loueur = ProfilPartenaire.objects.create(user=loueur_user, plan=plan, nom_commerce=f'Loueur Fin QA {uid}',
            type_partenaire='loueur_maison', statut='actif', est_visible=True, departement=ferke)
        super_ = utilisateur('t_fin_super', role='admin', staff=True, superuser=True)
        admin_avec = utilisateur('t_fin_avec', role='admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin_avec, gerer_reservations=True)
        client_user = utilisateur('t_fin_client', role='client')

        print('=== 1. FICHE LOGEMENT : departement_id / departement_nom ===')
        MON = '/api/v1/locations/mon-espace/logements/'
        r = req('post', MON, loueur_user, {'nom': f'Villa Fin {uid}', 'prix': 100000,
                                           'type_logement': 'villa', 'localite_id': loc_f.id})
        ok('creation avec localite -> 201', r.status_code == 201, r.content)
        v = r.json()
        ok('departement_id/departement_nom deduits de la localite',
           v['departement_id'] == ferke.id and v['departement_nom'] == ferke.nom, v)
        logement_id = v['id']
        r = req('post', MON, loueur_user, {'nom': f'Sans loc {uid}', 'prix': 50000, 'type_logement': 'studio'})
        ok('sans localite -> departement_id/nom = null', r.json()['departement_id'] is None
           and r.json()['departement_nom'] is None, r.json())
        r = req('get', f'{MON}{logement_id}/', loueur_user)
        ok('GET detail : memes champs', r.json()['departement_id'] == ferke.id)

        print('=== 2. TRANSITIONS_POSSIBLES : mon-espace (loueur) ===')
        cat = categories_correspondantes('loueur_maison').first()
        art = Article.objects.create(partenaire=loueur, categorie=cat, nom=f'Dispo Fin {uid}',
            slug=f'dispo-fin-{uid}', type='logement', prix=100000, est_actif=True)
        Logement.objects.create(article=art, type_logement='villa', disponibilite='disponible')
        demande = DemandeReservation.objects.create(
            numero=f'RSVFIN{uid}', client=client_user, partenaire=loueur, objet=art,
            nature='visite', statut='nouvelle', date_souhaitee='2026-11-01T10:00:00Z')

        r = req('get', '/api/v1/reservations/mon-espace/', loueur_user)
        ok('mon-espace -> 200', r.status_code == 200, r.content)
        ligne = next(x for x in r.json()['results'] if x['id'] == demande.id)
        ok('transitions_possibles present', 'transitions_possibles' in ligne, ligne.keys())
        ok('depuis nouvelle : 4 transitions (en_cours, confirmee, refusee, annulee)',
           {t['action'] for t in ligne['transitions_possibles']} == {'en_cours', 'confirmee', 'refusee', 'annulee'},
           ligne['transitions_possibles'])
        ok('commentaire_obligatoire=true seulement pour refusee (loueur)',
           {t['action'] for t in ligne['transitions_possibles'] if t['commentaire_obligatoire']} == {'refusee'},
           ligne['transitions_possibles'])
        ok("chaque transition a action/libelle/commentaire_obligatoire",
           all({'action', 'libelle', 'commentaire_obligatoire'} <= set(t) for t in ligne['transitions_possibles']))
        r = req('get', '/api/v1/reservations/mes-demandes/', client_user)
        ok('cote client (mes-demandes) : pas de transitions_possibles',
           'transitions_possibles' not in r.json()['results'][0], r.json()['results'][0].keys())

        print('=== 3. TRANSITIONS_POSSIBLES : detail admin ===')
        r = req('get', f'/api/v1/reservations/admin/demandes/{demande.id}/', admin_avec)
        ok('detail admin -> 200', r.status_code == 200, r.content)
        d = r.json()
        ok('transitions_possibles present', 'transitions_possibles' in d)
        ok('commentaire_obligatoire=true pour refusee ET annulee (admin)',
           {t['action'] for t in d['transitions_possibles'] if t['commentaire_obligatoire']} == {'refusee', 'annulee'},
           d['transitions_possibles'])
        req('post', f'/api/v1/reservations/{demande.id}/transition/', loueur_user, {'action': 'en_cours'})
        req('post', f'/api/v1/reservations/{demande.id}/transition/', loueur_user, {'action': 'confirmee'})
        r = req('get', f'/api/v1/reservations/admin/demandes/{demande.id}/', admin_avec)
        ok('depuis confirmee : transitions = terminee, annulee',
           {t['action'] for t in r.json()['transitions_possibles']} == {'terminee', 'annulee'}, r.json()['transitions_possibles'])
        req('post', f'/api/v1/reservations/admin/demandes/{demande.id}/transition/', admin_avec,
            {'action': 'terminee'})
        r = req('get', f'/api/v1/reservations/admin/demandes/{demande.id}/', admin_avec)
        ok('statut final (terminee) : aucune transition possible', r.json()['transitions_possibles'] == [],
           r.json()['transitions_possibles'])

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
