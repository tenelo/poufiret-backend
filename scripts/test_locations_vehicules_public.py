"""Tests : lecture publique des véhicules (Locations Phase V1).
Liste par loueur (forme, filtres), fiche complète sans N+1 (galerie,
panoramas, libellés, loueur, autres_vehicules, periodes_indisponibles).

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_locations_vehicules_public.py
"""
import json, uuid
from datetime import timedelta
from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from apps.catalog.correspondances import categories_correspondantes
from apps.catalog.models import Article, ArticleImage, Panorama, Vehicule
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

def utilisateur(username, role='client'):
    return User.objects.create(telephone=telephone_libre(), username=username, role=role, est_verifie=True)

def get(url):
    return Client().get(url, secure=True, HTTP_HOST=HOST)

def titres(r):
    return {x['titre'] for x in r.json()['resultats']}

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        ferke = Departement.objects.get(nom='Ferké')
        loc_f = Localite.objects.create(nom=f'VPub Ferke {uid}', departement=ferke)
        q_f = Quartier.objects.create(nom=f'VPub Q {uid}', localite=loc_f)
        loueur = ProfilPartenaire.objects.create(user=utilisateur('t_vpub_loueur', 'partenaire'), plan=plan,
            nom_commerce=f'Auto Pub QA {uid}', type_partenaire='loueur_voiture', statut='actif',
            est_visible=True, departement=ferke, telephone_pro='0700000000', whatsapp='0700000001')
        maison = ProfilPartenaire.objects.create(user=utilisateur('t_vpub_maison', 'partenaire'), plan=plan,
            nom_commerce=f'Maison Pub QA {uid}', type_partenaire='loueur_maison', statut='actif',
            est_visible=True, departement=ferke)
        categorie = categories_correspondantes('loueur_voiture').first()

        def creer(nom, prix, cat, places, boite, dispo='disponible', actif=True, chauffeur=False,
                  obligatoire=False, prix_chauffeur=None):
            a = Article.objects.create(partenaire=loueur, categorie=categorie, nom=nom,
                slug=f'{uuid.uuid4().hex[:8]}', type='vehicule', prix=prix, est_actif=actif)
            ArticleImage.objects.create(article=a, image='articles/x.png', est_principale=True, est_active=True)
            return Vehicule.objects.create(article=a, mode='location', marque='Toyota', modele=nom,
                categorie_vehicule=cat, places=places, boite_vitesse=boite, carburant='diesel',
                disponibilite=dispo, chauffeur_disponible=chauffeur, chauffeur_obligatoire=obligatoire,
                prix_jour_avec_chauffeur=prix_chauffeur, localite=loc_f, quartier_geo=q_f, secteur='Gare',
                equipements=['gps', 'usb'])

        v1 = creer(f'Yaris {uid}', 20000, 'voiture', 5, 'manuelle')
        v2 = creer(f'Prado {uid}', 60000, 'suv_4x4', 7, 'automatique', chauffeur=True, prix_chauffeur=75000)
        v3 = creer(f'Coaster {uid}', 120000, 'minibus', 22, 'manuelle', chauffeur=True, obligatoire=True,
                   prix_chauffeur=120000)
        v4 = creer(f'Indispo {uid}', 15000, 'voiture', 5, 'manuelle', dispo='indisponible')
        v5 = creer(f'Inactif {uid}', 15000, 'voiture', 5, 'manuelle', actif=False)
        for i in range(3):
            creer(f'Extra{i} {uid}', 30000 + i, 'voiture', 5, 'manuelle')
        Panorama.objects.create(article=v2.article, nom_piece='Intérieur', type_vue='photo_360', ordre=1)

        print('=== 1. LISTE PAR LOUEUR : forme et filtres ===')
        URL = f'/api/v1/locations/partenaires/{loueur.id}/vehicules/'
        with CaptureQueriesContext(connection) as ctx:
            r = get(URL)
        ok('anonyme -> 200', r.status_code == 200, r.content)
        ok('liste : nombre de requetes constant (<= 5)', len(ctx.captured_queries) <= 5, len(ctx.captured_queries))
        d = r.json()
        ok('loueur : id/nom/logo/couverture/contacts',
           set(d['loueur']) == {'id', 'nom', 'logo', 'couverture', 'telephone_pro', 'whatsapp'}, d['loueur'])
        ok('inactif exclu', f'Inactif {uid}' not in titres(r))
        ok('7 vehicules actifs', len(d['resultats']) == 7, titres(r))
        carte = next(x for x in d['resultats'] if x['titre'] == f'Prado {uid}')
        attendus = {'id', 'titre', 'photo', 'categorie_vehicule', 'categorie_libelle', 'marque', 'modele', 'annee',
                    'nb_places', 'boite_libelle', 'carburant_libelle', 'climatisation', 'prix_jour',
                    'prix_jour_avec_chauffeur', 'chauffeur_disponible', 'chauffeur_obligatoire',
                    'localisation_texte', 'disponibilite'}
        ok('carte : champs du contrat', set(carte) == attendus, set(carte) ^ attendus)
        ok('carte : libelles + photo + localisation', carte['categorie_libelle'] == 'SUV / 4x4'
           and carte['boite_libelle'] == 'Automatique' and carte['carburant_libelle'] == 'Diesel'
           and carte['photo'] and carte['localisation_texte'] == f'{loc_f.nom} - {q_f.nom} - Gare', carte)

        ok('filtre categorie=suv_4x4', titres(get(URL + '?categorie=suv_4x4')) == {f'Prado {uid}'})
        ok('filtre prix_max=20000', titres(get(URL + '?prix_max=20000')) == {f'Yaris {uid}', f'Indispo {uid}'})
        ok('filtre places_min=7', titres(get(URL + '?places_min=7')) == {f'Prado {uid}', f'Coaster {uid}'})
        ok('filtre boite=automatique', titres(get(URL + '?boite=automatique')) == {f'Prado {uid}'})
        ok('filtre avec_chauffeur=1', titres(get(URL + '?avec_chauffeur=1')) == {f'Prado {uid}', f'Coaster {uid}'})
        ok('filtre avec_chauffeur=0 exclut chauffeur obligatoire',
           f'Coaster {uid}' not in titres(get(URL + '?avec_chauffeur=0')) and f'Prado {uid}' in titres(get(URL + '?avec_chauffeur=0')))
        ok('filtre disponible=1', f'Indispo {uid}' not in titres(get(URL + '?disponible=1')))
        ok('prix_max invalide ignore', get(URL + '?prix_max=abc').status_code == 200)
        ok('loueur maison -> 404 sur /vehicules/',
           get(f'/api/v1/locations/partenaires/{maison.id}/vehicules/').status_code == 404)
        ok('loueur introuvable -> 404', get('/api/v1/locations/partenaires/999999/vehicules/').status_code == 404)

        print('=== 2. FICHE DETAIL : complete, sans N+1, periodes indisponibles ===')
        auj = timezone.localdate()
        client_user = utilisateur('t_vpub_client')
        for n, (deb, fin, statut) in enumerate([(3, 6, 'confirmee'), (10, 12, 'confirmee'),
                                                (-8, -5, 'confirmee'), (20, 25, 'nouvelle'), (30, 31, 'annulee')]):
            DemandeReservation.objects.create(numero=f'RSV-VP-{uid}-{n}', client=client_user, partenaire=loueur,
                objet=v2.article, nature='reservation', statut=statut,
                date_debut=auj + timedelta(days=deb), date_fin=auj + timedelta(days=fin))
        with CaptureQueriesContext(connection) as ctx:
            r = get(f'/api/v1/locations/vehicules/{v2.article_id}/')
        ok('detail -> 200', r.status_code == 200, r.content)
        ok('detail : nombre de requetes constant (<= 8)', len(ctx.captured_queries) <= 8, len(ctx.captured_queries))
        d2 = r.json()
        attendus = {'id', 'titre', 'description', 'galerie', 'panoramas', 'categorie_vehicule', 'categorie_libelle',
                    'marque', 'modele', 'annee', 'couleur', 'nb_places', 'boite', 'boite_libelle', 'carburant',
                    'carburant_libelle', 'climatisation', 'equipements', 'equipements_libelles', 'prix_jour',
                    'prix_jour_avec_chauffeur', 'chauffeur_disponible', 'chauffeur_obligatoire', 'caution',
                    'km_inclus_par_jour', 'prix_km_supplementaire', 'carburant_inclus', 'duree_min_jours',
                    'zone_circulation', 'disponibilite', 'disponibilite_libelle', 'localisation_texte',
                    'latitude', 'longitude', 'loueur', 'autres_vehicules', 'periodes_indisponibles'}
        ok('champs attendus', attendus <= set(d2), attendus - set(d2))
        ok('galerie (1 image)', len(d2['galerie']) == 1, d2['galerie'])
        ok('panorama interieur 360', d2['panoramas'][0]['titre'] == 'Intérieur'
           and d2['panoramas'][0]['type_vue'] == 'photo_360', d2['panoramas'])
        ok('equipements_libelles', d2['equipements_libelles'] == ['GPS', 'Prise USB'], d2['equipements_libelles'])
        ok('loueur', set(d2['loueur']) == {'id', 'nom', 'telephone_pro', 'whatsapp'}, d2['loueur'])
        ok('autres_vehicules : 4 max, disponibles, hors lui-meme',
           len(d2['autres_vehicules']) == 4 and all(x['disponibilite'] == 'disponible' and x['id'] != v2.article_id
                                                    for x in d2['autres_vehicules']), d2['autres_vehicules'])
        ok('periodes_indisponibles : confirmees a venir uniquement, triees', d2['periodes_indisponibles'] == [
            {'date_debut': str(auj + timedelta(days=3)), 'date_fin': str(auj + timedelta(days=6))},
            {'date_debut': str(auj + timedelta(days=10)), 'date_fin': str(auj + timedelta(days=12))}],
           d2['periodes_indisponibles'])
        ok('vehicule inactif -> 404', get(f'/api/v1/locations/vehicules/{v5.article_id}/').status_code == 404)
        ok('logement via /vehicules/ -> 404 (id inexistant)', get('/api/v1/locations/vehicules/999999/').status_code == 404)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
