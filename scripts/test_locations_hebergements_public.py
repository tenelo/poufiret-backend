"""Tests : lecture publique des établissements et hébergements (Locations
Phase V2). Fiche établissement (champs partenaire + fiche, galerie et
panoramas agrégés des hébergements, cartes), fiche hébergement (dates
optionnelles), route disponibilite (unités par dates, pic par nuit),
nombre de requêtes constant (pas de N+1).

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_locations_hebergements_public.py
"""
import uuid
from datetime import time, timedelta
from django.contrib.gis.geos import Point
from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from apps.catalog.correspondances import categories_correspondantes
from apps.catalog.models import Article, ArticleImage, Hebergement, Panorama
from apps.geo.models import Departement, Localite, Quartier
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

def utilisateur(username, role='client'):
    return User.objects.create(telephone=telephone_libre(), username=username, role=role, est_verifie=True)

def get(url):
    return Client().get(url, secure=True, HTTP_HOST=HOST)

def j(n):
    return timezone.localdate() + timedelta(days=n)

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        ferke = Departement.objects.get(nom='Ferké')
        loc = Localite.objects.create(nom=f'HPub {uid}', departement=ferke)
        q = Quartier.objects.create(nom=f'HPub Q {uid}', localite=loc)
        hotel = ProfilPartenaire.objects.create(user=utilisateur('t_hpub_hotel', 'partenaire'), plan=plan,
            nom_commerce=f'Hôtel Pub {uid}', type_partenaire='hotelier', statut='actif', est_visible=True,
            departement=ferke, localite=loc, quartier_geo=q, secteur='Centre', description='Au calme.',
            telephone_pro='0700000000', whatsapp='0700000001', localisation=Point(-5.2, 9.6, srid=4326))
        ProfilEtablissement.objects.create(partenaire=hotel, type_etablissement='hotel', etoiles=3,
            heure_arrivee=time(14), heure_depart=time(11), equipements=['wifi', 'navette'],
            petit_dejeuner='en_option', prix_petit_dejeuner=2500, politique_annulation='48 h.',
            conditions='CNI exigée.')
        cat = categories_correspondantes('hotelier').first()

        def creer(nom, prix, type_h, actif=True, unites=3, **kw):
            a = Article.objects.create(partenaire=hotel, categorie=cat, nom=nom, slug=uuid.uuid4().hex[:8],
                                       type='hebergement', prix=prix, est_actif=actif)
            for i in range(2):
                ArticleImage.objects.create(article=a, image=f'articles/{nom}{i}.png', est_principale=(i == 0),
                                            est_active=True, ordre=i)
            Panorama.objects.create(article=a, image='panoramas/p.png', nom_piece=f'Vue {nom}', ordre=1)
            return Hebergement.objects.create(article=a, type_hebergement=type_h, nb_unites=unites,
                                              capacite_adultes=2, lits='1 lit double', **kw)

        h1 = creer(f'Double {uid}', 20000, 'chambre_double', prix_semaine=120000)
        h2 = creer(f'Suite {uid}', 50000, 'suite', unites=1)
        h3 = creer(f'Studio {uid}', 30000, 'studio', prix_mois=600000)
        h4 = creer(f'Inactif {uid}', 10000, 'chambre_simple', actif=False)
        h5 = creer(f'Indispo {uid}', 15000, 'chambre_simple', disponibilite='indisponible')

        print('=== 1. FICHE ETABLISSEMENT ===')
        URL = f'/api/v1/locations/partenaires/{hotel.id}/etablissement/'
        with CaptureQueriesContext(connection) as ctx:
            r = get(URL)
        ok('anonyme -> 200', r.status_code == 200, r.content)
        n_requetes = len(ctx.captured_queries)
        ok('requetes constantes (<= 5)', n_requetes <= 5, n_requetes)
        d = r.json()
        e = d['etablissement']
        attendus = {'id', 'nom', 'logo', 'couverture', 'galerie', 'panoramas', 'type_etablissement_libelle',
                    'etoiles', 'description', 'localisation_texte', 'latitude', 'longitude', 'telephone_pro',
                    'whatsapp', 'heure_arrivee', 'heure_depart', 'equipements_etablissement',
                    'equipements_etablissement_libelles', 'petit_dejeuner', 'prix_petit_dejeuner',
                    'politique_annulation', 'conditions'}
        ok('etablissement : champs du contrat', attendus <= set(e), attendus - set(e))
        ok('donnees partenaire reutilisees', e['id'] == hotel.id and e['description'] == 'Au calme.'
           and e['localisation_texte'] == f'{loc.nom} - {q.nom} - Centre'
           and abs(e['latitude'] - 9.6) < 1e-6 and e['telephone_pro'] == '0700000000', e)
        ok('fiche : libelles, heures, equipements', e['type_etablissement_libelle'] == 'Hôtel'
           and e['heure_arrivee'] == '14:00:00' and e['equipements_etablissement_libelles'] == ['Wifi', 'Navette']
           and int(e['prix_petit_dejeuner']) == 2500, e)
        ok('galerie = images des hebergements actifs (4 hebergements x 2)', len(e['galerie']) == 8, e['galerie'])
        ok('panoramas agreges (4)', len(e['panoramas']) == 4, e['panoramas'])
        titres = [x['titre'] for x in d['hebergements']]
        ok('hebergements actifs tries par prix (inactif exclu)',
           titres == [f'Indispo {uid}', f'Double {uid}', f'Studio {uid}', f'Suite {uid}'], titres)
        carte = d['hebergements'][1]
        ok('carte : champs du contrat', set(carte) >= {'id', 'titre', 'photo', 'type_hebergement_libelle',
           'capacite_adultes', 'capacite_enfants', 'lits', 'prix_nuit', 'prix_semaine', 'prix_mois',
           'disponibilite'} and carte['photo'] and 'Double' in carte['photo'], carte)
        for i in range(3):
            creer(f'Extra{i} {uid}', 40000 + i, 'chambre_twin')
        with CaptureQueriesContext(connection) as ctx:
            r = get(URL)
        ok('pas de N+1 : meme nombre de requetes avec 3 hebergements de plus',
           len(ctx.captured_queries) == n_requetes, (n_requetes, len(ctx.captured_queries)))
        ok('non-hotelier / inconnu -> 404', get('/api/v1/locations/partenaires/999999/etablissement/').status_code == 404)
        sans = ProfilPartenaire.objects.create(user=utilisateur('t_hpub_sans', 'partenaire'), plan=plan,
            nom_commerce=f'Sans fiche {uid}', type_partenaire='hotelier', statut='actif', est_visible=True)
        r = get(f'/api/v1/locations/partenaires/{sans.id}/etablissement/')
        ok('hotelier sans fiche -> 200 avec valeurs par defaut, aucune ecriture',
           r.status_code == 200 and r.json()['etablissement']['petit_dejeuner'] == 'non'
           and not ProfilEtablissement.objects.filter(partenaire=sans).exists(), r.content)

        print('=== 2. UNITES DISPONIBLES PAR DATES ===')
        client_user = utilisateur('t_hpub_client')
        # h1 : 3 unites. Confirmees : [j3,j5[ x2 ; [j5,j7[ x1 ; nouvelle [j3,j7[ x3 (ignoree) ; annulee.
        for n, (deb, fin, statut, u) in enumerate([(3, 5, 'confirmee', 2), (5, 7, 'confirmee', 1),
                                                  (3, 7, 'nouvelle', 3), (3, 7, 'annulee', 3)]):
            DemandeReservation.objects.create(numero=f'RSV-HP-{uid}-{n}', client=client_user, partenaire=hotel,
                objet=h1.article, nature='reservation', statut=statut, nb_unites=u,
                date_debut=j(deb), date_fin=j(fin))
        DISPO = f'/api/v1/locations/hebergements/{h1.article_id}/disponibilite/'

        def unites(deb, fin):
            r = get(f'{DISPO}?date_debut={j(deb)}&date_fin={j(fin)}')
            return r.json().get('unites_disponibles') if r.status_code == 200 else r.status_code

        ok('periode libre -> 3', unites(10, 12) == 3, unites(10, 12))
        ok('[j3,j5[ -> 1', unites(3, 5) == 1, unites(3, 5))
        ok('[j5,j7[ -> 2', unites(5, 7) == 2, unites(5, 7))
        ok('[j3,j7[ : pic par nuit (2), pas la somme (3) -> 1', unites(3, 7) == 1, unites(3, 7))
        ok('depart le jour d arrivee d une autre resa : [j1,j3[ -> 3', unites(1, 3) == 3, unites(1, 3))
        ok('hebergement indisponible -> 0', get(
            f'/api/v1/locations/hebergements/{h5.article_id}/disponibilite/?date_debut={j(1)}&date_fin={j(2)}'
        ).json()['unites_disponibles'] == 0)
        ok('dates manquantes -> 400', get(DISPO).status_code == 400)
        ok('date_fin <= date_debut -> 400', get(f'{DISPO}?date_debut={j(3)}&date_fin={j(3)}').status_code == 400)
        ok('date invalide -> 400', get(f'{DISPO}?date_debut=demain&date_fin={j(3)}').status_code == 400)

        print('=== 3. FICHE HEBERGEMENT ===')
        FICHE = f'/api/v1/locations/hebergements/{h1.article_id}/'
        with CaptureQueriesContext(connection) as ctx:
            r = get(f'{FICHE}?date_debut={j(3)}&date_fin={j(5)}')
        ok('fiche avec dates -> 200', r.status_code == 200, r.content)
        ok('requetes constantes (<= 6)', len(ctx.captured_queries) <= 6, len(ctx.captured_queries))
        f = r.json()
        attendus = {'id', 'titre', 'description', 'galerie', 'panoramas', 'type_hebergement',
                    'type_hebergement_libelle', 'capacite_adultes', 'capacite_enfants', 'lits', 'surface_m2',
                    'equipements_hebergement', 'equipements_hebergement_libelles', 'prix_nuit', 'prix_semaine',
                    'prix_mois', 'nb_unites', 'duree_min_nuits', 'disponibilite', 'disponibilite_libelle',
                    'etablissement', 'unites_disponibles'}
        ok('champs du contrat', attendus <= set(f), attendus - set(f))
        ok('etablissement resume', set(f['etablissement']) >= {'id', 'nom', 'heure_arrivee', 'heure_depart',
           'petit_dejeuner', 'politique_annulation'} and f['etablissement']['heure_depart'] == '11:00:00',
           f['etablissement'])
        ok('galerie (2) + panorama', len(f['galerie']) == 2 and len(f['panoramas']) == 1)
        ok('unites_disponibles pour les dates = 1', f['unites_disponibles'] == 1, f['unites_disponibles'])
        r = get(FICHE)
        ok('sans dates : unites_disponibles = null', r.status_code == 200 and r.json()['unites_disponibles'] is None)
        ok('dates invalides -> 400', get(f'{FICHE}?date_debut={j(3)}').status_code == 400)
        ok('inactif -> 404', get(f'/api/v1/locations/hebergements/{h4.article_id}/').status_code == 404)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
