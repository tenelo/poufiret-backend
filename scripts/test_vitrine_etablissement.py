"""Tests : vitrine des hôtels / résidences (carrousel de la page publique).

- vitrine mixte (photo de chambre + photo propre) et son ordre ; réordonnancement ;
- maximum respecté, refus au-delà (400), baisse du maximum (rien supprimé,
  réponse publique plafonnée) ;
- vitrine vide : repli sur la photo principale de chaque hébergement, plafonné ;
- photo de chambre désactivée / supprimée qui sort ; doublon refusé ;
- isolement entre partenaires ; droits (hôtelier, admin avec / sans
  gerer_locations, paramètres réservés au super-admin) ;
- quota par plan : non appliqué aux photos propres, inchangé pour les chambres ;
- format de etablissement.galerie inchangé (liste d'URL) ; galerie d'une chambre inchangée.

Données propres, rollback (fichiers téléversés supprimés), limitation de débit
désactivée, total OK / KO.
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_vitrine_etablissement.py
"""
import io, json, uuid

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client
from PIL import Image
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.catalog.models import Article, ArticleImage, Categorie, Hebergement
from apps.locations.models import ImageVitrine, ParametresLocations, ProfilEtablissement
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
# Limitation de débit DRF désactivée pour ce script : sinon tous les scripts partagent
# le compteur anonyme (60/min, client de test = 127.0.0.1) et la suite complète reçoit des 429.
from unittest import mock as _mock_debit
from rest_framework.views import APIView as _APIViewDebit
_mock_debit.patch.object(_APIViewDebit, 'get_throttles', return_value=[]).start()


class Rollback(Exception):
    pass


NB_OK, KO = 0, []
FICHIERS = []  # fichiers téléversés pendant le test (supprimés à la fin)


def ok(libelle, cond, detail=''):
    global NB_OK
    if cond:
        NB_OK += 1
        print('OK  ', libelle)
    else:
        KO.append(libelle)
        print('FAIL', libelle, detail)


def req(method, url, user=None, corps=None, multipart=None):
    kw = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    fn = getattr(Client(), method)
    if multipart is not None:
        return fn(url, multipart, **kw)
    if corps is not None:
        return fn(url, json.dumps(corps), content_type='application/json', **kw)
    return fn(url, **kw)


def png(nom):
    tampon = io.BytesIO()
    Image.new('RGB', (40, 30), (200, 80, 40)).save(tampon, 'PNG')
    return SimpleUploadedFile(nom, tampon.getvalue(), content_type='image/png')


def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel


def fin(url):
    """Chemin média d'une URL (comparaison indépendante de l'hôte)."""
    return url.split('/media/', 1)[-1] if url else url


try:
    with transaction.atomic():
        u = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        plan.nb_photos_par_article = 1  # quota par plan (annulé au rollback)
        plan.save(update_fields=['nb_photos_par_article'])
        params = ParametresLocations.obtenir()
        params.nb_max_images_vitrine = 10
        params.save()
        cat = Categorie.objects.create(nom=f'Hotels QA vitrine {u}', slug=f'hotels-vitrine-{u}')

        def utilisateur(role='client', **kw):
            return User.objects.create(telephone=telephone_libre(), username=f't_vit_{uuid.uuid4().hex[:8]}',
                                       role=role, est_verifie=True, **kw)

        def hotelier(nom):
            p = ProfilPartenaire.objects.create(user=utilisateur('partenaire'), plan=plan, nom_commerce=f'{nom} {u}',
                                                type_partenaire='hotelier', statut='actif', est_visible=True)
            ProfilEtablissement.objects.get_or_create(partenaire=p)
            return p

        def hebergement(p, nom, prix, photos, actif=True):
            """photos : [(nom_fichier, ordre, est_principale)] -> {nom: ArticleImage}"""
            a = Article.objects.create(partenaire=p, categorie=cat, nom=f'{nom} {u}', slug=f'vit-{uuid.uuid4().hex[:10]}',
                                       type='hebergement', prix=prix, est_actif=actif)
            Hebergement.objects.create(article=a, type_hebergement='chambre_double', nb_unites=1)
            return a, {n: ArticleImage.objects.create(article=a, image=f'articles/vit_{u}_{n}.png', ordre=o,
                                                      est_principale=pr) for n, o, pr in photos}

        h1, h2 = hotelier('Hotel Vitrine'), hotelier('Autre Hotel')
        art_a, im_a = hebergement(h1, 'Chambre A', 10000, [('a1', 1, False), ('a2', 2, True)])
        art_b, im_b = hebergement(h1, 'Chambre B', 20000, [('b1', 1, False), ('b2', 2, False)])
        art_c, im_c = hebergement(h1, 'Chambre C', 30000, [('c1', 1, False)])
        _, im_i = hebergement(h1, 'Chambre inactive', 5000, [('i1', 1, True)], actif=False)
        _, im_x = hebergement(h2, 'Chambre X', 15000, [('x1', 1, True)])
        a1, a2, b1, b2, c1, x1 = im_a['a1'], im_a['a2'], im_b['b1'], im_b['b2'], im_c['c1'], im_x['x1']

        client = utilisateur()
        superadmin = utilisateur('admin', is_staff=True, is_superuser=True)
        admin_loc = utilisateur('admin', is_staff=True)
        PermissionsAdmin.objects.create(admin=admin_loc, gerer_locations=True)
        admin_sans = utilisateur('admin', is_staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans)

        MON = '/api/v1/locations/mon-espace/vitrine/'
        ADM = f'/api/v1/locations/admin/{h1.id}/vitrine/'
        PARAM = '/api/v1/locations/admin/parametres/'
        PUB = f'/api/v1/locations/partenaires/{h1.id}/etablissement/'

        def galerie():
            return req('get', PUB).json()['etablissement']['galerie']

        def noms(urls):
            return [fin(x).rsplit('_', 1)[-1].split('.')[0] for x in urls]

        # ═══════════════════════════════════════════════════════════════
        print('=== 1. VITRINE VIDE : REPLI ===')
        g = galerie()
        ok('format inchange : liste de chaines (URL absolues)', isinstance(g, list)
           and all(isinstance(x, str) and x.startswith('http') for x in g), g)
        ok('repli : principale (a2), sinon premiere par ordre (b1, c1), chambres actives, ordre par prix',
           noms(g) == ['a2', 'b1', 'c1'], noms(g))
        params.nb_max_images_vitrine = 2
        params.save()
        ok('repli plafonne au maximum (2)', noms(galerie()) == ['a2', 'b1'], noms(galerie()))
        params.nb_max_images_vitrine = 10
        params.save()
        d = req('get', f'/api/v1/locations/hebergements/{art_a.id}/').json()
        ok('galerie de la page d une chambre inchangee (toutes ses photos)', noms(d['galerie']) == ['a1', 'a2'],
           d.get('galerie'))

        print('=== 2. DROITS ===')
        ok('anonyme -> 401', req('get', MON).status_code == 401)
        ok('client (pas hotelier) -> 403', req('get', MON, client).status_code == 403)
        ok('admin sans gerer_locations -> 403', req('get', ADM, admin_sans).status_code == 403)
        ok('admin gerer_locations -> 200', req('get', ADM, admin_loc).status_code == 200)
        ok('admin : partenaire non hotelier -> 404',
           req('get', f'/api/v1/locations/admin/{client.id + 10 ** 7}/vitrine/', admin_loc).status_code == 404)
        ok('parametres : admin gerer_locations -> 403', req('get', PARAM, admin_loc).status_code == 403)
        r = req('get', PARAM, superadmin)
        ok('parametres : super-admin GET -> 200, 10', r.status_code == 200 and r.json()['nb_max_images_vitrine'] == 10,
           r.content[:200])
        ok('parametres : 0 -> 400', req('patch', PARAM, superadmin, {'nb_max_images_vitrine': 0}).status_code == 400)
        ok('parametres : texte -> 400', req('patch', PARAM, superadmin, {'nb_max_images_vitrine': 'dix'}).status_code == 400)

        print('=== 3. LISTE ET PHOTOS DISPONIBLES ===')
        d = req('get', MON, h1.user).json()
        ok('vide : nb_max 10, 0 image', (d['nb_max_images'], d['nb_images'], d['images']) == (10, 0, []), d)
        dispo = {p['id']: p for p in d['photos_disponibles']}
        ok('photos disponibles : celles de SES chambres actives (pas inactive, pas h2)',
           set(dispo) == {a1.id, a2.id, b1.id, b2.id, c1.id}, set(dispo))
        ok('photo disponible : id, url, nom de la chambre', dispo[b2.id]['hebergement_nom'] == art_b.nom
           and fin(dispo[b2.id]['url']) == b2.image.name and dispo[b2.id]['dans_vitrine'] is False, dispo[b2.id])
        d2 = req('get', MON, h2.user).json()
        ok('isolement : h2 ne voit que sa photo', [p['id'] for p in d2['photos_disponibles']] == [x1.id], d2)

        print('=== 4. VITRINE MIXTE ===')
        r = req('post', MON, h1.user, {'image_hebergement': b2.id, 'legende': 'Suite'})
        ok('ajout photo de chambre -> 201', r.status_code == 201 and r.json()['images'][0]['source'] == 'hebergement'
           and r.json()['images'][0]['legende'] == 'Suite' and r.json()['images'][0]['hebergement_nom'] == art_b.nom,
           r.content[:300])
        r = req('post', MON, h1.user, multipart={'image': png('piscine.png'), 'legende': 'Piscine'})
        ok('ajout photo propre (multipart) -> 201', r.status_code == 201
           and r.json()['images'][1]['source'] == 'propre' and r.json()['images'][1]['url'], r.content[:300])
        FICHIERS.extend(ImageVitrine.objects.exclude(image='').values_list('image', flat=True))
        r = req('post', ADM, admin_loc, {'image_hebergement': a1.id})
        ok('admin ajoute a la place du partenaire -> 201', r.status_code == 201 and r.json()['nb_images'] == 3,
           r.content[:300])
        ok('action admin journalisee', JournalModeration.objects.filter(
            acteur=admin_loc, action='loc_etablissement_modif', motif__contains='Vitrine').exists())
        ok('doublon de photo de chambre -> 400',
           req('post', MON, h1.user, {'image_hebergement': b2.id}).status_code == 400)
        ok('les deux sources -> 400', req('post', MON, h1.user, multipart={
            'image': png('x.png'), 'image_hebergement': str(c1.id)}).status_code == 400)
        ok('aucune source -> 400', req('post', MON, h1.user, {'legende': 'rien'}).status_code == 400)
        ok('photo d un autre partenaire -> 400 (isolement)',
           req('post', MON, h1.user, {'image_hebergement': x1.id}).status_code == 400)
        ok('photo d une chambre inactive -> 400',
           req('post', MON, h1.user, {'image_hebergement': im_i['i1'].id}).status_code == 400)
        d = req('get', MON, h1.user).json()
        ids = {el['source'] + (str(el['image_hebergement_id']) if el['image_hebergement_id'] else ''): el['id']
               for el in d['images']}
        el_b2, el_propre, el_a1 = ids[f'hebergement{b2.id}'], ids['propre'], ids[f'hebergement{a1.id}']
        ok('ordre d ajout : b2, propre, a1', [el['id'] for el in d['images']] == [el_b2, el_propre, el_a1])
        ok('dans_vitrine coche', {p['id'] for p in d['photos_disponibles'] if p['dans_vitrine']} == {a1.id, b2.id})
        g = galerie()
        ok('public : galerie = vitrine dans l ordre (format liste d URL)',
           [fin(x) for x in g] == [b2.image.name, fin(d['images'][1]['url']), a1.image.name], g)

        print('=== 5. LEGENDE, ORDRE ===')
        r = req('patch', f'{MON}{el_propre}/', h1.user, {'legende': 'Piscine chauffee'})
        ok('legende modifiee', r.status_code == 200 and any(
            el['legende'] == 'Piscine chauffee' for el in r.json()['images']), r.content[:200])
        ok('element d un autre partenaire -> 404', req('patch', f'{MON}{el_propre}/', h2.user,
                                                       {'legende': 'x'}).status_code == 404)
        r = req('post', f'{MON}ordre/', h1.user, {'ids': [el_a1, el_b2, el_propre]})
        ok('reordonner en un appel -> 200', r.status_code == 200
           and [el['id'] for el in r.json()['images']] == [el_a1, el_b2, el_propre], r.content[:300])
        ok('public suit le nouvel ordre', [fin(x) for x in galerie()][:2] == [a1.image.name, b2.image.name])
        ok('ordre : element manquant -> 400', req('post', f'{MON}ordre/', h1.user,
                                                  {'ids': [el_a1, el_b2]}).status_code == 400)
        ok('ordre : doublon -> 400', req('post', f'{MON}ordre/', h1.user,
                                         {'ids': [el_a1, el_a1, el_propre]}).status_code == 400)
        ok('ordre : par l admin -> 200', req('post', f'{ADM}ordre/', admin_loc,
                                             {'ids': [el_a1, el_b2, el_propre]}).status_code == 200)

        print('=== 6. MAXIMUM ===')
        ok('super-admin : maximum 3', req('patch', PARAM, superadmin, {'nb_max_images_vitrine': 3}).json()
           ['nb_max_images_vitrine'] == 3)
        r = req('post', MON, h1.user, {'image_hebergement': c1.id})
        ok('ajout au-dela du maximum -> 400, message clair', r.status_code == 400
           and 'maximum' in r.json().get('message', '') and r.json()['details'] == {'nb_max_images': 3, 'nb_images': 3},
           r.content[:300])
        req('patch', PARAM, superadmin, {'nb_max_images_vitrine': 2})
        ok('baisse du maximum : rien supprime', ImageVitrine.objects.filter(etablissement__partenaire=h1).count() == 3)
        d = req('get', MON, h1.user).json()
        ok('gestion : les 3 images restent visibles, maximum 2', (d['nb_images'], d['nb_max_images']) == (3, 2), d)
        ok('public : 2 premieres seulement', [fin(x) for x in galerie()] == [a1.image.name, b2.image.name], galerie())
        req('patch', PARAM, superadmin, {'nb_max_images_vitrine': 10})

        print('=== 7. PHOTO DESACTIVEE / SUPPRIMEE ===')
        ArticleImage.objects.filter(pk=a1.pk).update(est_active=False)
        d = req('get', MON, h1.user).json()
        ok('photo desactivee : sort de la vitrine et des photos disponibles', el_a1 not in [
            el['id'] for el in d['images']] and a1.id not in [p['id'] for p in d['photos_disponibles']], d)
        ok('photo desactivee : sort de la galerie publique', a1.image.name not in [fin(x) for x in galerie()])
        ok('reordonner sans elle -> 200', req('post', f'{MON}ordre/', h1.user,
                                              {'ids': [el_propre, el_b2]}).status_code == 200)
        ArticleImage.objects.filter(pk=a1.pk).update(est_active=True)
        ok('photo reactivee : revient (apres les autres)', [el['id'] for el in req('get', MON, h1.user).json()['images']]
           == [el_propre, el_b2, el_a1])
        b2.delete()
        ok('photo de chambre supprimee : element supprime', not ImageVitrine.objects.filter(pk=el_b2).exists())

        print('=== 8. QUOTA PAR PLAN ===')
        for n in range(3):
            r = req('post', MON, h1.user, multipart={'image': png(f'facade{n}.png')})
            ok(f'photo propre {n + 1} malgre quota plan = 1 -> 201', r.status_code == 201, r.content[:200])
        FICHIERS.extend(ImageVitrine.objects.exclude(image='').values_list('image', flat=True))
        r = req('post', f'/api/v1/locations/mon-espace/hebergements/{art_c.id}/images/', h1.user,
                multipart={'image': png('chambre.png')})
        ok('photo de chambre : quota plan toujours applique -> 400', r.status_code == 400, r.content[:200])

        print('=== 9. RETRAIT ===')
        d = req('get', MON, h1.user).json()
        for el in d['images']:
            ok(f'retrait {el["source"]} -> 200', req('delete', f'{MON}{el["id"]}/', h1.user).status_code == 200)
        ok('photo de chambre retiree mais pas supprimee', ArticleImage.objects.filter(pk=a1.pk).exists())
        ok('vitrine vide -> repli public', noms(galerie()) == ['a2', 'b1', 'c1'], noms(galerie()))

        raise Rollback()
except Rollback:
    print('\nRollback effectue (rien persiste).')
finally:
    for nom in set(FICHIERS):
        try:
            if nom and default_storage.exists(nom):
                default_storage.delete(nom)
        except Exception:
            pass

print(f'\n=== TOTAL : {NB_OK} OK / {len(KO)} KO ===')
if KO:
    print('KO :', *KO, sep='\n - ')
    raise SystemExit(1)
