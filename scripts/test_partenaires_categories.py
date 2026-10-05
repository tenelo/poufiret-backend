"""Tests : correspondance type de partenaire → catégorie par défaut.
Rattachement à la création et au changement de type (service + signal),
catégories existantes conservées, une seule catégorie principale, pas de
ré-ajout d'une catégorie retirée lors d'une modif sans changement de type,
endpoint /catalogue/correspondances-types/ (admin), commande
controle_types_categories (lecture et --corriger).

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_partenaires_categories.py
"""
import io, json
from django.core.management import call_command
from django.db import transaction
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken
from apps.catalog.models import Categorie, PartenaireCategorie
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
class Rollback(Exception): pass
NB = 0
def ok(l, c, d=''):
    global NB
    print(('OK   ' if c else 'FAIL '), l, '' if c else d)
    assert c, f'{l} {d}'
    NB += 1

def utilisateur(tel, username, role):
    u = User.objects.create(telephone=tel, username=username, role=role, est_verifie=True,
                            is_staff=(role == 'admin'))
    u.set_password('0000'); u.save()
    return u

def liens(p):
    return set(PartenaireCategorie.objects.filter(partenaire=p).values_list('categorie__nom', flat=True))

def principales(p):
    return PartenaireCategorie.objects.filter(partenaire=p, est_principale=True).count()

try:
    with transaction.atomic():
        plan = PlanAbonnement.objects.get(libelle='Basique')
        resto_cat = Categorie.objects.get(nom='Restaurants')
        pharma_cat = Categorie.objects.get(nom='Pharmacie')
        boulange_cat = Categorie.objects.get(nom='Boulangerie & Pâtisserie')
        boutique_cat = Categorie.objects.get(nom='Boutiques & Commerce')

        print('=== 1. CREATION : rattachement automatique ===')
        u = utilisateur('+22507000050', 't_cat_resto', 'partenaire')
        resto = ProfilPartenaire.objects.create(user=u, plan=plan, nom_commerce='Resto CAT QA',
                                                type_partenaire='restaurateur')
        ok('restaurateur rattache a Restaurants', liens(resto) == {'Restaurants'}, liens(resto))
        ok('une seule categorie principale', principales(resto) == 1)

        print('=== 2. CHANGEMENT DE TYPE : ajout, rien retire ===')
        u2 = utilisateur('+22507000051', 't_cat_pharma', 'partenaire')
        p = ProfilPartenaire.objects.create(user=u2, plan=plan, nom_commerce='Pharma CAT QA',
                                            type_partenaire='pharmacien')
        ok('pharmacien rattache a Pharmacie', liens(p) == {'Pharmacie'}, liens(p))
        p.type_partenaire = 'boulanger'
        p.save()
        ok('apres passage a boulanger : Boulangerie ajoutee', 'Boulangerie & Pâtisserie' in liens(p), liens(p))
        ok('apres passage a boulanger : Pharmacie conservee', 'Pharmacie' in liens(p), liens(p))
        ok('toujours une seule principale', principales(p) == 1)

        print('=== 3. CATEGORIE EXISTANTE CONSERVEE A LA CREATION ===')
        u3 = utilisateur('+22507000052', 't_cat_boutique', 'partenaire')
        b = ProfilPartenaire.objects.create(user=u3, plan=plan, nom_commerce='Boutique CAT QA',
                                            type_partenaire='commercant')
        PartenaireCategorie.objects.filter(partenaire=b).delete()
        PartenaireCategorie.objects.create(partenaire=b, categorie=resto_cat, est_principale=True)
        b.type_partenaire = 'commercant'
        b.save()
        ok('pas de changement de type : rien ajoute', liens(b) == {'Restaurants'}, liens(b))

        print('=== 4. RETRAIT MANUEL NON ANNULE PAR UNE MODIF SANS CHANGEMENT DE TYPE ===')
        PartenaireCategorie.objects.filter(partenaire=resto, categorie=resto_cat).delete()
        resto.nom_commerce = 'Resto CAT QA renomme'
        resto.save()
        ok('modif du nom : la categorie retiree n\'est pas re-ajoutee', liens(resto) == set(), liens(resto))
        resto.type_partenaire = 'restaurateur'
        resto.save()
        ok('meme type re-enregistre : pas de re-ajout', liens(resto) == set(), liens(resto))

        print('=== 5. ENDPOINT /catalogue/correspondances-types/ ===')
        admin = utilisateur('+22507000053', 't_cat_admin', 'admin')
        non_admin = utilisateur('+22507000054', 't_cat_user', 'partenaire')
        c = Client()
        url = '/api/v1/catalogue/correspondances-types/'
        def get(user):
            kw = {'secure': True, 'HTTP_HOST': HOST}
            if user:
                kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
            return c.get(url, **kw)
        r = get(admin)
        ok('admin -> 200', r.status_code == 200, r.content)
        corr = r.json()['correspondances']
        ok('cle correspondances, champs attendus',
           corr and set(corr[0]) == {'type_partenaire', 'type_libelle', 'categorie_id', 'categorie_nom'}, corr[:1])
        ok('restaurateur -> Restaurants présent',
           any(x['type_partenaire'] == 'restaurateur' and x['categorie_nom'] == 'Restaurants' for x in corr))
        ok('type sans categorie (autre) absent', not any(x['type_partenaire'] == 'autre' for x in corr))
        ok('non-admin -> 403', get(non_admin).status_code == 403)
        ok('anonyme -> 401', get(None).status_code in (401, 403))

        print('=== 6. COMMANDE controle_types_categories ===')
        avant = PartenaireCategorie.objects.count()
        sortie = io.StringIO()
        call_command('controle_types_categories', stdout=sortie)
        ok('lecture seule : aucun lien cree', PartenaireCategorie.objects.count() == avant)
        ok('la sortie liste le partenaire sans categorie (resto CAT QA)',
           'Resto CAT QA renomme' in sortie.getvalue(), sortie.getvalue())
        sortie = io.StringIO()
        call_command('controle_types_categories', '--corriger', stdout=sortie)
        ok('--corriger : le partenaire recupere sa categorie', liens(resto) == {'Restaurants'}, liens(resto))
        ok('--corriger : sortie indique le nombre cree', 'rattachement(s) créé(s)' in sortie.getvalue())
        sortie = io.StringIO()
        call_command('controle_types_categories', stdout=sortie)
        ok('relance apres correction : le partenaire de test n\'apparait plus',
           'Resto CAT QA' not in sortie.getvalue(), sortie.getvalue())

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
