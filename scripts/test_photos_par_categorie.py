"""Tests : nombre maximum de photos par article réglable par catégorie
(Categorie.max_photos_par_article, 1 à 4, hérité des parentes, prioritaire
sur le quota de l'abonnement). Plafond à 4 (5e refusée), héritage de la
parente, quota de l'abonnement inchangé sans valeur (routes imbriquées 400,
/catalogue/images/ 403), valeurs 0 / 5 refusées, baisse sans suppression,
plafond_photos dans les listes vendeur / admin, réponses publiques
inchangées, droits inchangés.

Données propres ; tout est annulé à la fin (aucune donnée ni fichier conservé).
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_photos_par_categorie.py
"""
import io
import json
import shutil
import tempfile
import uuid

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client
from django.test.utils import override_settings
from PIL import Image
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import PermissionsAdmin
from apps.catalog.models import Article, ArticleImage, Categorie, Vehicule
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
# Limitation de débit DRF désactivée pour ce script (même mécanisme que les autres scripts).
from unittest import mock as _mock_debit
from rest_framework.views import APIView as _APIViewDebit
_mock_debit.patch.object(_APIViewDebit, 'get_throttles', return_value=[]).start()
NB_OK = 0


class Rollback(Exception):
    pass


def ok(libelle, condition, detail=''):
    global NB_OK
    print(('OK   ' if condition else 'FAIL '), libelle, '' if condition else detail)
    assert condition, f'{libelle} {detail}'
    NB_OK += 1


def entetes(user):
    return {'HTTP_AUTHORIZATION': f'Bearer {AccessToken.for_user(user)}', 'HTTP_HOST': HOST}


def png():
    tampon = io.BytesIO()
    Image.new('RGB', (30, 30), (120, 60, 20)).save(tampon, format='PNG')
    return SimpleUploadedFile('photo.png', tampon.getvalue(), content_type='image/png')


def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel


def compte(nom, role='admin', staff=False, superuser=False):
    return User.objects.create(telephone=telephone_libre(), username=f'{nom}_{uuid.uuid4().hex[:5]}',
                               role=role, is_staff=staff, is_superuser=superuser, est_verifie=True)


dossier_media = tempfile.mkdtemp(prefix='test_photos_cat_')
avant_images = ArticleImage.objects.count()
avant_categories = Categorie.objects.count()
try:
    with override_settings(MEDIA_ROOT=dossier_media), transaction.atomic():
        c = Client()
        uid = uuid.uuid4().hex[:6]
        plan_1 = PlanAbonnement.objects.create(code='basique', libelle=f'Plan QA {uid}', nb_photos_par_article=1,
                                               duree_jours=90000 + int(uid, 16) % 9000)
        mode = Categorie.objects.create(nom=f'Mode QA {uid}', slug=f'mode-qa-{uid}', max_photos_par_article=2)
        chaussures = Categorie.objects.create(nom=f'Chaussures QA {uid}', slug=f'chaussures-qa-{uid}', parent=mode)
        sous = Categorie.objects.create(nom=f'Baskets QA {uid}', slug=f'baskets-qa-{uid}', parent=chaussures)
        cat4 = Categorie.objects.create(nom=f'Sacs QA {uid}', slug=f'sacs-qa-{uid}', parent=mode,
                                        max_photos_par_article=4)
        sans = Categorie.objects.create(nom=f'Divers QA {uid}', slug=f'divers-qa-{uid}')

        vendeur_user = compte('t_photo_vendeur', role='partenaire')
        vendeur = ProfilPartenaire.objects.create(
            user=vendeur_user, plan=plan_1, nom_commerce=f'Mode QA {uid}', type_partenaire='boutique_mode',
            statut='actif', est_visible=True)
        autre_user = compte('t_photo_autre', role='partenaire')
        ProfilPartenaire.objects.create(user=autre_user, plan=plan_1, nom_commerce=f'Autre QA {uid}',
                                        type_partenaire='boutique_mode', statut='actif', est_visible=True)
        loueur_user = compte('t_photo_loueur', role='partenaire')
        loueur = ProfilPartenaire.objects.create(
            user=loueur_user, plan=plan_1, nom_commerce=f'Auto QA {uid}', type_partenaire='loueur_voiture',
            statut='actif', est_visible=True)
        super_ = compte('t_photo_super', staff=True, superuser=True)
        admin_resto = compte('t_photo_resto', staff=True)
        PermissionsAdmin.objects.create(admin=admin_resto, gerer_restaurants=True)
        admin_param = compte('t_photo_param', staff=True)
        PermissionsAdmin.objects.create(admin=admin_param, gerer_parametres=True)
        admin_sans = compte('t_photo_sans', staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans)

        def article(nom, categorie):
            return Article.objects.create(partenaire=vendeur, categorie=categorie, nom=f'{nom} {uid}',
                                          slug=f'{nom.lower()}-{uuid.uuid4().hex[:6]}', type='produit', prix=5000)

        MON = '/api/v1/restaurants/mon-restaurant/carte/plats'
        ADM = f'/api/v1/restaurants/admin/{vendeur.id}/carte/plats'

        def ajouter(art, user=vendeur_user, base=MON):
            return c.post(f'{base}/{art.id}/images/', {'image': png()}, secure=True, **entetes(user))

        def lister(art, user=vendeur_user, base=MON):
            return c.get(f'{base}/{art.id}/images/', secure=True, **entetes(user))

        print('=== 1. CHAMP DE CATEGORIE : VALIDATION ET DROITS ===')
        CAT = '/api/v1/administration/categories/'
        def patch_cat(cat, valeur, user=admin_param):
            return c.patch(f'{CAT}{cat.id}/', json.dumps({'max_photos_par_article': valeur}),
                           content_type='application/json', secure=True, **entetes(user))
        for valeur in (0, 5, -1, 'abc'):
            r = patch_cat(sans, valeur)
            ok(f'valeur {valeur!r} -> 400', r.status_code == 400
               and 'max_photos_par_article' in r.json().get('details', {}), r.content)
        ok('valeur 3 -> 200', patch_cat(sans, 3).json().get('max_photos_par_article') == 3)
        ok('valeur null -> 200 (vide)', patch_cat(sans, None).json().get('max_photos_par_article', 'x') is None)
        ok('admin sans gerer_parametres -> 403 (droits inchanges)', patch_cat(sans, 2, admin_sans).status_code == 403)
        r = c.get(CAT, secure=True, **entetes(admin_param))
        ligne = next(x for x in r.json()['resultats'] if x['id'] == cat4.id)
        ok('liste admin des categories : champ lisible', ligne['max_photos_par_article'] == 4, ligne)
        r = c.post(CAT, json.dumps({'nom': f'Neuve QA {uid}', 'max_photos_par_article': 2}),
                   content_type='application/json', secure=True, **entetes(admin_param))
        ok('creation avec valeur -> 201', r.status_code == 201 and r.json()['max_photos_par_article'] == 2, r.content)
        try:
            Categorie(nom='x', slug=f'x-{uid}', max_photos_par_article=5).full_clean()
            refuse = False
        except ValidationError as e:
            refuse = 'max_photos_par_article' in e.message_dict
        ok('modele : full_clean refuse 5', refuse)
        try:
            with transaction.atomic():
                Categorie.objects.filter(pk=sans.pk).update(max_photos_par_article=0)
            contrainte = False
        except IntegrityError:
            contrainte = True
        ok('base : contrainte 1..4 (0 refuse meme en ecriture directe)', contrainte)

        print('=== 2. CATEGORIE A 4 : 4 PHOTOS, 5e REFUSEE ===')
        sac = article('Sac', cat4)
        for i in range(4):
            r = ajouter(sac)
            ok(f'photo {i + 1}/4 -> 201', r.status_code == 201, r.content)
        r = ajouter(sac)
        ok('5e photo -> 400', r.status_code == 400, r.content)
        ok('message clair avec le maximum et la categorie', r.json()['message'].startswith(
            f'Nombre maximum de photos atteint : 4 photo(s) par article pour la catégorie « {cat4.nom} » (4 déjà).'),
           r.json())
        ok('details : quota, nb_images, source', r.json()['details'] == {
            'quota': 4, 'nb_images': 4, 'source': 'categorie', 'categorie_id': cat4.id}, r.json())
        ok('4 photos en base (abonnement a 1 ignore)', sac.images.count() == 4)

        print('=== 3. HERITAGE : categorie vide + parente a 2 ===')
        basket = article('Basket', sous)
        ok('2 photos -> 201', ajouter(basket).status_code == 201 and ajouter(basket).status_code == 201)
        r = ajouter(basket)
        ok('3e -> 400, plafond de la parente (Mode QA, 2)', r.status_code == 400
           and r.json()['details']['quota'] == 2 and r.json()['details']['categorie_id'] == mode.id
           and f'« {mode.nom} »' in r.json()['message'], r.content)
        d = lister(basket).json()['plafond_photos']
        ok('plafond_photos herite', (d['max'], d['source'], d['categorie_id'], d['nb_photos'], d['peut_ajouter'])
           == (2, 'categorie', mode.id, 2, False), d)

        print('=== 4. AUCUNE VALEUR : QUOTA DE L ABONNEMENT INCHANGE ===')
        divers = article('Divers', sans)
        ok('1re photo -> 201', ajouter(divers).status_code == 201)
        r = ajouter(divers)
        ok('2e -> 400 avec le message historique du plan', r.status_code == 400
           and r.json()['message'] == (f"Quota de photos atteint : 1 photo(s) par article avec le plan "
                                       f"« {plan_1.libelle} » (1 déjà). Supprimez une photo ou passez "
                                       f"à un plan supérieur pour en ajouter.")
           and r.json()['details'] == {'quota': 1, 'nb_images': 1}, r.content)
        d = lister(divers).json()['plafond_photos']
        ok('plafond_photos source abonnement', (d['max'], d['source'], d['plan_libelle'], d['nb_photos']) ==
           (1, 'abonnement', plan_1.libelle, 1), d)
        r = c.post('/api/v1/catalogue/images/', {'article': divers.id, 'image': png()}, secure=True,
                   **entetes(vendeur_user))
        ok('/catalogue/images/ sans valeur : 403 et message historique (inchanges)', r.status_code == 403
           and f'Quota photos atteint (1/article pour le plan {plan_1.libelle}).' in r.content.decode(), r.content)
        PlanAbonnement.objects.filter(pk=plan_1.pk).update(nb_photos_par_article=0)
        ok('abonnement a 0 = illimite (inchange)', ajouter(divers).status_code == 201
           and lister(divers).json()['plafond_photos']['max'] is None)
        PlanAbonnement.objects.filter(pk=plan_1.pk).update(nb_photos_par_article=1)

        print('=== 5. /catalogue/images/ AVEC VALEUR DE CATEGORIE ===')
        sac2 = article('Sac2', cat4)
        for i in range(4):
            ok(f'/catalogue/images/ photo {i + 1} -> 201', c.post('/api/v1/catalogue/images/',
               {'article': sac2.id, 'image': png()}, secure=True, **entetes(vendeur_user)).status_code == 201)
        r = c.post('/api/v1/catalogue/images/', {'article': sac2.id, 'image': png()}, secure=True,
                   **entetes(vendeur_user))
        ok('/catalogue/images/ 5e -> 400 (message categorie)', r.status_code == 400
           and r.json()['details']['source'] == 'categorie', r.content)
        r = c.get(f'/api/v1/catalogue/images/?article={sac2.id}', secure=True, **entetes(vendeur_user))
        ok('/catalogue/images/?article= (vendeur) : plafond_photos', r.json()['plafond_photos']['max'] == 4
           and r.json()['plafond_photos']['nb_photos'] == 4, r.content)
        r = c.get(f'/api/v1/catalogue/images/?article={sac2.id}', secure=True, HTTP_HOST=HOST)
        ok('/catalogue/images/ anonyme : reponse inchangee (pas de plafond)', 'plafond_photos' not in r.json())
        r = c.get(f'/api/v1/catalogue/images/?article={sac2.id}', secure=True, **entetes(autre_user))
        ok('/catalogue/images/ autre vendeur : pas de plafond', 'plafond_photos' not in r.json())

        print('=== 6. BAISSE DU PLAFOND : AUCUNE SUPPRESSION ===')
        Categorie.objects.filter(pk=cat4.pk).update(max_photos_par_article=2)
        ok('les 4 photos restent', sac.images.count() == 4)
        r = ajouter(sac)
        ok('ajout bloque (4 >= 2)', r.status_code == 400 and r.json()['details']['quota'] == 2, r.content)
        d = lister(sac).json()
        ok('liste : 4 photos, plafond 2, peut_ajouter false', len(d['results']) == 4
           and (d['plafond_photos']['max'], d['plafond_photos']['nb_photos'], d['plafond_photos']['peut_ajouter'])
           == (2, 4, False), d['plafond_photos'])
        ok('modification d une photo existante toujours possible', c.patch(
            f'{MON}/{sac.id}/images/{sac.images.first().id}/', json.dumps({'legende': 'Profil'}),
            content_type='application/json', secure=True, **entetes(vendeur_user)).status_code == 200)
        ok('suppression d une photo toujours possible', c.delete(
            f'{MON}/{sac.id}/images/{sac.images.last().id}/', secure=True, **entetes(vendeur_user)).status_code == 204)

        print('=== 7. COTE ADMIN ET LOCATIONS ===')
        r = lister(sac, admin_resto, ADM)
        ok('admin (gerer_restaurants) : liste + plafond_photos', r.status_code == 200
           and r.json()['plafond_photos']['max'] == 2, r.content)
        ok('admin sans gerer_restaurants -> 403 (inchange)', lister(sac, admin_sans, ADM).status_code == 403)
        ok('admin : plafond applique aussi', ajouter(sac, super_, ADM).status_code == 400)
        ok('autre vendeur -> 404 sur cet article (inchange)', lister(sac, autre_user).status_code == 404)
        auto = Article.objects.create(partenaire=loueur, categorie=cat4, nom=f'Corolla {uid}', slug=f'cor-{uid}',
                                      type='vehicule', prix=20000)
        Vehicule.objects.create(article=auto, marque='Toyota', modele='Corolla', mode='location')
        VEH = '/api/v1/locations/mon-espace/vehicules'
        ok('locations : 2 photos (plafond 2) puis refus', all(
            c.post(f'{VEH}/{auto.id}/images/', {'image': png()}, secure=True, **entetes(loueur_user)).status_code == 201
            for _ in range(2)) and c.post(f'{VEH}/{auto.id}/images/', {'image': png()}, secure=True,
                                          **entetes(loueur_user)).status_code == 400)
        r = c.get(f'{VEH}/{auto.id}/images/', secure=True, **entetes(loueur_user))
        ok('locations : plafond_photos dans la liste', r.json()['plafond_photos']['max'] == 2
           and r.json()['plafond_photos']['nb_photos'] == 2, r.content)
        r = c.get(f'/api/v1/locations/admin/{loueur.id}/vehicules/{auto.id}/images/', secure=True, **entetes(super_))
        ok('locations admin : plafond_photos', r.status_code == 200 and 'plafond_photos' in r.json(), r.content)

        print('=== 8. REPONSES PUBLIQUES INCHANGEES ===')
        principale = sac.images.order_by('ordre').last()
        ArticleImage.objects.filter(article=sac).update(est_principale=False)
        ArticleImage.objects.filter(pk=principale.pk).update(est_principale=True)
        r = c.get(f'/api/v1/restaurants/produits/{sac.id}/', secure=True, HTTP_HOST=HOST)
        ok('fiche produit publique : principale en premier', r.status_code == 200
           and r.json()['images'][0]['id'] == principale.id and 'plafond_photos' not in r.json(), r.content)
        r = c.get('/api/v1/catalogue/categories/', secure=True, HTTP_HOST=HOST)
        cats = r.json()['results'] if isinstance(r.json(), dict) else r.json()
        ok('categories publiques : champ non expose', cats and all('max_photos_par_article' not in x for x in cats))

        print(f'\n=== {NB_OK} verifications reussies ===')
        raise Rollback('annulation volontaire')
except Rollback as e:
    print('Rollback effectue :', e)
finally:
    shutil.rmtree(dossier_media, ignore_errors=True)

assert ArticleImage.objects.count() == avant_images, 'des images de test ont persiste !'
assert Categorie.objects.count() == avant_categories, 'des categories de test ont persiste !'
print('Aucune donnee persistee (images : %d, categories : %d avant/apres), dossier media temporaire supprime.'
      % (avant_images, avant_categories))
