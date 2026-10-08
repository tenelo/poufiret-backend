"""Tests : GET /api/v1/locations/meta/ — référentiels publics des logements
(M1), des véhicules (V1) et des hébergements (V2), construits depuis les
choix réels (Logement.TypeLogement, EQUIPEMENTS_LIBELLES,
Logement.Disponibilite, Vehicule.CategorieVehicule/BoiteVitesse/Carburant,
EQUIPEMENTS_VEHICULE_LIBELLES, ProfilEtablissement.TypeEtablissement/
PetitDejeuner, Hebergement.TypeHebergement, EQUIPEMENTS_ETABLISSEMENT_LIBELLES,
EQUIPEMENTS_HEBERGEMENT_LIBELLES), pas de liste recopiée à la main.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_locations_meta.py
"""
from django.db import transaction
from django.test import Client
from apps.catalog.models import Hebergement, Logement, Vehicule
from apps.locations.models import ProfilEtablissement
from apps.locations.services import (
    EQUIPEMENTS_ETABLISSEMENT_LIBELLES, EQUIPEMENTS_HEBERGEMENT_LIBELLES, EQUIPEMENTS_LIBELLES,
    EQUIPEMENTS_VEHICULE_LIBELLES,
)

HOST = 'poufiret.tenelo.cloud'
class Rollback(Exception): pass
NB = 0
def ok(l, c, d=''):
    global NB
    print(('OK   ' if c else 'FAIL '), l, '' if c else d)
    assert c, f'{l} {d}'
    NB += 1

try:
    with transaction.atomic():
        r = Client().get('/api/v1/locations/meta/', secure=True, HTTP_HOST=HOST)
        ok('anonyme -> 200', r.status_code == 200, r.content)
        d = r.json()
        ok('cles attendues (M1 conservees + V1 + V2)', set(d) == {
            'types_logement', 'equipements', 'disponibilites',
            'categories_vehicule', 'boites', 'carburants', 'equipements_vehicule',
            'types_etablissement', 'types_hebergement', 'equipements_etablissement',
            'equipements_hebergement', 'petit_dejeuner'}, set(d))

        ok('types_logement : valeur+libelle, egal aux choix reels',
           d['types_logement'] == [{'valeur': v, 'libelle': l} for v, l in Logement.TypeLogement.choices],
           d['types_logement'])
        ok('disponibilites : valeur+libelle, egal aux choix reels',
           d['disponibilites'] == [{'valeur': v, 'libelle': l} for v, l in Logement.Disponibilite.choices],
           d['disponibilites'])
        ok('equipements : valeur+libelle, egal au referentiel reel',
           d['equipements'] == [{'valeur': v, 'libelle': l} for v, l in EQUIPEMENTS_LIBELLES.items()],
           d['equipements'])
        ok("'disponible' present dans disponibilites",
           any(x['valeur'] == 'disponible' for x in d['disponibilites']))
        ok("'villa' present dans types_logement", any(x['valeur'] == 'villa' for x in d['types_logement']))
        ok("'climatisation' present dans equipements", any(x['valeur'] == 'climatisation' for x in d['equipements']))

        def choix(c):
            return [{'valeur': v, 'libelle': l} for v, l in c.choices]
        ok('categories_vehicule = choix reels', d['categories_vehicule'] == choix(Vehicule.CategorieVehicule),
           d['categories_vehicule'])
        ok('boites = choix reels', d['boites'] == choix(Vehicule.BoiteVitesse), d['boites'])
        ok('carburants = choix reels', d['carburants'] == choix(Vehicule.Carburant), d['carburants'])
        ok('equipements_vehicule = referentiel reel', d['equipements_vehicule'] == [
            {'valeur': v, 'libelle': l} for v, l in EQUIPEMENTS_VEHICULE_LIBELLES.items()], d['equipements_vehicule'])
        ok('types_etablissement = choix reels',
           d['types_etablissement'] == choix(ProfilEtablissement.TypeEtablissement), d['types_etablissement'])
        ok('types_hebergement = choix reels',
           d['types_hebergement'] == choix(Hebergement.TypeHebergement), d['types_hebergement'])
        ok('petit_dejeuner = choix reels', d['petit_dejeuner'] == choix(ProfilEtablissement.PetitDejeuner),
           d['petit_dejeuner'])
        ok('equipements_etablissement = referentiel reel', d['equipements_etablissement'] == [
            {'valeur': v, 'libelle': l} for v, l in EQUIPEMENTS_ETABLISSEMENT_LIBELLES.items()])
        ok('equipements_hebergement = referentiel reel', d['equipements_hebergement'] == [
            {'valeur': v, 'libelle': l} for v, l in EQUIPEMENTS_HEBERGEMENT_LIBELLES.items()])
        ok("'residence_meublee', 'chambre_twin', 'securite_24h', 'eau_chaude' presents",
           any(x['valeur'] == 'residence_meublee' for x in d['types_etablissement'])
           and any(x['valeur'] == 'chambre_twin' for x in d['types_hebergement'])
           and any(x['valeur'] == 'securite_24h' for x in d['equipements_etablissement'])
           and any(x['valeur'] == 'eau_chaude' for x in d['equipements_hebergement']))
        ok("'suv_4x4' et 'camera_recul' presents",
           any(x['valeur'] == 'suv_4x4' for x in d['categories_vehicule'])
           and any(x['valeur'] == 'camera_recul' for x in d['equipements_vehicule']))

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
