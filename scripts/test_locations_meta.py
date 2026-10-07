"""Tests : GET /api/v1/locations/meta/ — référentiels publics des logements,
construits depuis les choix réels (Logement.TypeLogement, EQUIPEMENTS_LIBELLES,
Logement.Disponibilite), pas de liste recopiée à la main.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_locations_meta.py
"""
from django.db import transaction
from django.test import Client
from apps.catalog.models import Logement
from apps.locations.services import EQUIPEMENTS_LIBELLES

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
        ok('cles attendues', set(d) == {'types_logement', 'equipements', 'disponibilites'}, set(d))

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

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
