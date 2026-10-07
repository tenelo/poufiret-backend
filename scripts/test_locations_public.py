"""Tests : lecture publique des logements (Locations Phase M1) et liste
admin des loueurs avec indicateurs. Filtres, forme de la réponse, pas de
N+1 sur la fiche détail, exclusion des logements inactifs.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_locations_public.py
"""
import uuid
from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from rest_framework_simplejwt.tokens import AccessToken
from apps.administration.models import PermissionsAdmin
from apps.catalog.models import Article, Logement, Panorama
from apps.geo.models import Departement, Localite, Quartier
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

def get(url, user=None):
    kw = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    return Client().get(url, **kw)

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        ferke = Departement.objects.get(nom='Ferké')
        loc_f = Localite.objects.create(nom=f'Pub Ferke {uid}', departement=ferke)
        q_f = Quartier.objects.create(nom=f'Pub Q {uid}', localite=loc_f)

        loueur_user = utilisateur('t_locpub_loueur', role='partenaire')
        loueur = ProfilPartenaire.objects.create(user=loueur_user, plan=plan, nom_commerce=f'Loueur Pub QA {uid}',
            type_partenaire='loueur_maison', statut='actif', est_visible=True, departement=ferke,
            telephone_pro='0700000000', whatsapp='0700000001')

        def creer_logement(nom, prix, chambres, meuble, type_logement, dispo, actif=True):
            cat = Article.objects.filter(partenaire__type_partenaire='loueur_maison').first()
            from apps.catalog.correspondances import categories_correspondantes
            categorie = categories_correspondantes('loueur_maison').first()
            a = Article.objects.create(partenaire=loueur, categorie=categorie, nom=nom,
                slug=f'{nom.lower().replace(" ", "-")}-{uuid.uuid4().hex[:4]}', type='logement',
                prix=prix, est_actif=actif)
            return Logement.objects.create(article=a, type_logement=type_logement, nb_chambres=chambres,
                meuble=meuble, disponibilite=dispo, localite=loc_f, quartier_geo=q_f, secteur='Centre')

        l1 = creer_logement(f'Studio A {uid}', 40000, 1, False, 'studio', 'disponible')
        l2 = creer_logement(f'Villa B {uid}', 200000, 4, True, 'villa', 'disponible')
        l3 = creer_logement(f'Loue C {uid}', 90000, 2, True, 'appartement', 'loue')
        l4 = creer_logement(f'Inactif D {uid}', 90000, 2, True, 'appartement', 'disponible', actif=False)
        Panorama.objects.create(article=l2.article, nom_piece='Salon', type_vue='photo_360', ordre=1)

        print('=== 1. LISTE PAR LOUEUR : forme et filtres ===')
        URL = f'/api/v1/locations/partenaires/{loueur.id}/logements/'
        r = get(URL)
        ok('anonyme -> 200', r.status_code == 200, r.content)
        d = r.json()
        ok('cle loueur + resultats', {'loueur', 'resultats'} <= set(d))
        ok('loueur : nom/logo/couverture/contacts', {'id', 'nom', 'logo', 'couverture', 'telephone_pro', 'whatsapp'} <= set(d['loueur']))
        ok('inactif exclu par defaut', not any(x['titre'] == f'Inactif D {uid}' for x in d['resultats']))
        ok('3 logements actifs presents', len([x for x in d['resultats'] if uid in x['titre']]) == 3, d['resultats'])
        carte = next(x for x in d['resultats'] if x['titre'] == f'Studio A {uid}')
        ok('carte : champs attendus', {'id', 'titre', 'photo', 'type_logement', 'type_logement_libelle',
           'localisation_texte', 'loyer', 'nb_chambres', 'nb_salles_de_bain', 'meuble', 'disponibilite'} <= set(carte), carte)
        ok('localisation_texte formee', carte['localisation_texte'] == f'{loc_f.nom} - {q_f.nom} - Centre', carte)

        r = get(URL + '?type=villa')
        ok('filtre type=villa', {x['titre'] for x in r.json()['resultats']} == {f'Villa B {uid}'})
        r = get(URL + '?chambres_min=2')
        ok('filtre chambres_min=2', {x['titre'] for x in r.json()['resultats']} == {f'Villa B {uid}', f'Loue C {uid}'})
        r = get(URL + '?meuble=0')
        ok('filtre meuble=0', {x['titre'] for x in r.json()['resultats']} == {f'Studio A {uid}'})
        r = get(URL + '?disponible=1')
        ok('filtre disponible=1 exclut le loue', {x['titre'] for x in r.json()['resultats']} == {f'Studio A {uid}', f'Villa B {uid}'})
        r = get(URL + '?loyer_max=50000')
        ok('filtre loyer_max', {x['titre'] for x in r.json()['resultats']} == {f'Studio A {uid}'})
        ok('loueur introuvable -> 404', get(f'/api/v1/locations/partenaires/999999/logements/').status_code == 404)

        print('=== 2. FICHE DETAIL : complete, sans N+1, autres logements ===')
        with CaptureQueriesContext(connection) as ctx:
            r = get(f'/api/v1/locations/logements/{l2.article_id}/')
        ok('detail -> 200', r.status_code == 200, r.content)
        ok('nombre de requetes raisonnable (<= 10)', len(ctx.captured_queries) <= 10, len(ctx.captured_queries))
        d2 = r.json()
        attendus = {'id', 'titre', 'description', 'galerie', 'panoramas', 'type_logement', 'type_logement_libelle',
                    'nb_chambres', 'nb_salons', 'nb_salles_de_bain', 'surface_m2', 'meuble', 'loyer',
                    'caution_mois', 'avance_mois', 'frais_agence', 'compteur_eau_individuel',
                    'compteur_electricite_individuel', 'equipements', 'disponibilite', 'disponible_a_partir_du',
                    'localite_nom', 'quartier_nom', 'secteur', 'adresse_reperes', 'latitude', 'longitude',
                    'loueur', 'autres_logements'}
        ok('champs attendus', attendus <= set(d2), attendus - set(d2))
        ok('panorama present (type_vue/titre/ordre)', d2['panoramas'] and d2['panoramas'][0]['titre'] == 'Salon'
           and d2['panoramas'][0]['type_vue'] == 'photo_360', d2['panoramas'])
        ok('loueur : nom + telephones + whatsapp', {'id', 'nom', 'telephone_pro', 'whatsapp'} <= set(d2['loueur']))
        autres_titres = {x['titre'] for x in d2['autres_logements']}
        ok('autres logements disponibles du meme loueur (hors loue/inactif)',
           autres_titres == {f'Studio A {uid}'}, autres_titres)
        ok('logement inactif -> 404', get(f'/api/v1/locations/logements/{l4.article_id}/').status_code == 404)

        print('=== 3. LISTE ADMIN DES LOUEURS AVEC INDICATEURS ===')
        super_ = utilisateur('t_locpub_super', role='admin', staff=True, superuser=True)
        r = get('/api/v1/locations/admin/', super_)
        ok('liste admin -> 200', r.status_code == 200, r.content)
        ligne = next(x for x in r.json()['resultats'] if x['id'] == loueur.id)
        ok('indicateurs : disponibles/reserves/loues/demandes_en_attente', {
            'nb_disponibles', 'nb_reserves', 'nb_loues', 'demandes_en_attente'} <= set(ligne), ligne)
        ok('comptage correct (3 disponibles dont le brouillon inactif, 1 loue)',
           ligne['nb_disponibles'] == 3 and ligne['nb_loues'] == 1, ligne)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
