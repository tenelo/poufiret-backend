"""Tests : gabarits — phase 1 : GET /api/v1/restaurants/meta/gabarits/
(AllowAny), conforme au contrat (libellés, fonctions actives, pagination,
champs typés avec choix et obligation).

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_gabarits_phase1.py
"""
from django.db import transaction
from django.test import Client
from rest_framework.throttling import SimpleRateThrottle

SimpleRateThrottle.allow_request = lambda self, request, view: True
HOST = 'poufiret.tenelo.cloud'
class Rollback(Exception): pass
NB = 0
def ok(l, c, d=''):
    global NB
    print(('OK   ' if c else 'FAIL '), l, '' if c else d)
    assert c, f'{l} {d}'
    NB += 1

ATTENDU = {
    'restaurant': ('Section', 'Plat', 'Variantes', True, True, False, []),
    'boulangerie': ('Section', 'Produit', 'Formats', False, True, False,
                    [('sur_commande', 'booleen'), ('delai_heures', 'entier'), ('allergenes', 'texte')]),
    'pharmacie': ('Rayon', 'Produit', 'Formats', False, False, True,
                  [('forme', 'choix'), ('dosage', 'texte'), ('laboratoire', 'texte'),
                   ('conditionnement', 'texte'), ('sur_ordonnance', 'booleen')]),
    'mode': ('Catégorie', 'Article', 'Pointures', False, False, True,
             [('marque', 'texte'), ('matiere', 'texte'), ('couleur', 'texte'), ('genre', 'choix')]),
    'librairie': ('Rayon', 'Livre', 'Formats', False, False, True,
                  [('auteur', 'texte'), ('editeur', 'texte'), ('isbn', 'texte'), ('langue', 'texte'),
                   ('classe', 'texte'), ('annee', 'entier'), ('genre_livre', 'choix'), ('niveau', 'choix'),
                   ('etat', 'choix')]),
}
CHOIX = {
    ('pharmacie', 'forme'): ['comprime', 'gelule', 'sirop', 'pommade', 'injectable', 'sachet', 'collyre', 'autre'],
    ('mode', 'genre'): ['homme', 'femme', 'enfant', 'mixte'],
    ('librairie', 'genre_livre'): ['scolaire', 'roman', 'jeunesse', 'religieux', 'dictionnaire', 'essai', 'bd', 'autre'],
    ('librairie', 'niveau'): ['primaire', 'college', 'lycee', 'superieur', 'aucun'],
    ('librairie', 'etat'): ['neuf', 'occasion'],
}

try:
    with transaction.atomic():
        r = Client().get('/api/v1/restaurants/meta/gabarits/', secure=True, HTTP_HOST=HOST)
        ok('anonyme -> 200', r.status_code == 200, r.content)
        d = r.json()
        ok('5 gabarits', set(d) == set(ATTENDU), set(d))
        for g, (sec, prod, var, menus, options, pagination, champs) in ATTENDU.items():
            x = d[g]
            ok(f'{g} : cles', set(x) == {'libelle', 'libelle_section', 'libelle_produit', 'libelle_variantes',
                                         'menus_actifs', 'options_actives', 'pagination_publique', 'champs'}, set(x))
            ok(f'{g} : libelles {sec}/{prod}/{var}', (x['libelle_section'], x['libelle_produit'],
                                                      x['libelle_variantes']) == (sec, prod, var), x)
            ok(f'{g} : menus={menus} options={options} pagination={pagination}',
               (x['menus_actifs'], x['options_actives'], x['pagination_publique']) == (menus, options, pagination), x)
            ok(f'{g} : champs (cle, type) dans l ordre', [(c['cle'], c['type']) for c in x['champs']] == champs,
               [(c['cle'], c['type']) for c in x['champs']])
            ok(f'{g} : chaque champ a cle/libelle/type/choix/obligatoire', all(
                set(c) == {'cle', 'libelle', 'type', 'choix', 'obligatoire'} and c['libelle'] for c in x['champs']))
            for c in x['champs']:
                attendu = CHOIX.get((g, c['cle']))
                if c['type'] == 'choix':
                    ok(f'{g}.{c["cle"]} : choix', [v['valeur'] for v in c['choix']] == attendu
                       and all(v['libelle'] for v in c['choix']), c['choix'])
                else:
                    ok(f'{g}.{c["cle"]} : pas de choix', c['choix'] == [])
        obligatoires = {(g, c['cle']) for g, x in d.items() for c in x['champs'] if c['obligatoire']}
        ok('seul librairie.auteur est obligatoire', obligatoires == {('librairie', 'auteur')}, obligatoires)
        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
