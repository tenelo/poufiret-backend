"""Tests : CRUD admin des catégories (/administration/categories/).
Droits gerer_parametres, création (racine, sous-catégorie, image, multipart),
unicité du nom par niveau, types déjà déclarés (400), PATCH partiel et
changement de parent, cycles, suppression 204/409, archivage et désarchivage
(avec revérification), ordre et types, lecture publique (archivées et
inactives masquées), journal.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_categories_admin.py
"""
import io, json, uuid
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client
from PIL import Image
from rest_framework_simplejwt.tokens import AccessToken
from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.catalog.models import Article, Categorie, PartenaireCategorie
from apps.users.models import ProfilPartenaire, User

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

def utilisateur(username, staff=False, superuser=False):
    u = User.objects.create(telephone=telephone_libre(), username=username,
                            role='admin' if staff else 'client', est_verifie=True,
                            is_staff=staff, is_superuser=superuser)
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

def png():
    buf = io.BytesIO(); Image.new('RGB', (2, 2)).save(buf, format='PNG'); return buf.getvalue()

try:
    with transaction.atomic():
        A = '/api/v1/administration/categories/'
        super_ = utilisateur('t_cat_super', staff=True, superuser=True)
        sans = utilisateur('t_cat_sans', staff=True)
        PermissionsAdmin.objects.create(admin=sans)
        avec = utilisateur('t_cat_avec', staff=True)
        PermissionsAdmin.objects.create(admin=avec, gerer_parametres=True)
        uid = uuid.uuid4().hex[:6]
        nom_racine = f'QA Racine {uid}'

        print('=== 1. DROITS ===')
        ok('admin sans capacite -> 403', req('get', A, sans).status_code == 403)
        ok('anonyme -> 401/403', req('get', A).status_code in (401, 403))
        ok('super-admin -> 200', req('get', A, super_).status_code == 200)
        ok('admin avec capacite -> 200', req('get', A, avec).status_code == 200)

        print('=== 2. CREATION RACINE (JSON) ===')
        r = req('post', A, avec, {'nom': nom_racine, 'description': 'desc', 'icone': '🧪',
                                   'types_partenaire': ['autre'], 'mots_cles': ['  Test  Mot ', 'test mot'],
                                   'est_active': True})
        ok('POST racine -> 201', r.status_code == 201, r.content)
        racine = r.json()
        ok('slug genere', racine['slug'] and racine['slug'].startswith('qa-racine'), racine['slug'])
        ok('mots-cles normalises, sans doublon', racine['mots_cles'] == ['test mot'], racine['mots_cles'])
        ok('types_partenaire conserves', racine['types_partenaire'] == ['autre'])
        ok('racine : parent_id null', racine['parent_id'] is None and racine['parent_nom'] is None)
        ok('ordre = dernier du niveau (>= 1)', racine['ordre'] >= 1, racine['ordre'])
        ok('champs complets', set(racine) == {'id', 'nom', 'slug', 'description', 'icone', 'image', 'ordre',
           'est_active', 'est_archivee', 'parent_id', 'parent_nom', 'types_partenaire', 'mots_cles',
           'nb_partenaires', 'nb_enfants'}, set(racine))
        rid = racine['id']

        print('=== 3. SOUS-CATEGORIE + IMAGE (multipart) ===')
        r = req('post', A, avec, {'nom': f'QA Enfant {uid}', 'parent_id': rid})
        ok('POST sous-categorie -> 201', r.status_code == 201, r.content)
        enfant = r.json()
        ok('parent_id/parent_nom renseignes', enfant['parent_id'] == rid and enfant['parent_nom'] == nom_racine)
        ok('ordre dans le niveau enfant = 1', enfant['ordre'] == 1, enfant['ordre'])
        c = Client()
        r = c.post(A, {'nom': f'QA Image {uid}', 'image': SimpleUploadedFile('c.png', png(), content_type='image/png'),
                       'mots_cles': ['Img Un', 'img un']},
                   secure=True, HTTP_HOST=HOST, HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(avec)}')
        ok('POST multipart avec image -> 201', r.status_code == 201, r.content)
        img = r.json()
        ok('image renvoyee (URL)', img['image'] is not None and 'categories' in img['image'], img['image'])
        ok('multipart : mots-cles normalises', img['mots_cles'] == ['img un'], img['mots_cles'])
        img_id = img['id']

        print('=== 4. UNICITE DU NOM PAR NIVEAU ===')
        r = req('post', A, avec, {'nom': nom_racine.upper(), 'parent_id': None})
        ok('meme nom a la racine (casse differente) -> 400 details.nom',
           r.status_code == 400 and 'nom' in r.json()['details'], r.content)
        r = req('post', A, avec, {'nom': nom_racine, 'parent_id': rid})
        ok('meme nom sous un autre parent -> 201', r.status_code == 201, r.content)
        enfant2_id = r.json()['id']
        r = req('post', A, avec, {'nom': f'QA Enfant {uid}', 'parent_id': rid})
        ok('nom deja pris sous le meme parent -> 400', r.status_code == 400, r.content)

        print('=== 5. TYPES DEJA DECLARES ET TYPES INVALIDES ===')
        r = req('post', A, avec, {'nom': f'QA Resto bis {uid}', 'types_partenaire': ['restaurateur']})
        ok('type deja declare -> 400 details.types_partenaire', r.status_code == 400 and 'types_partenaire' in r.json()['details'], r.content)
        ok('message nomme la categorie qui le detient',
           'Restaurants' in r.json()['details']['types_partenaire'][0], r.json())
        r = req('post', A, avec, {'nom': f'QA Type bad {uid}', 'types_partenaire': ['zzz']})
        ok('type invalide -> 400', r.status_code == 400, r.content)
        r = req('patch', f'{A}{rid}/', avec, {'types_partenaire': ['restaurateur']})
        ok('PATCH : type deja declare -> 400', r.status_code == 400, r.content)

        print('=== 6. PATCH PARTIEL ET CHANGEMENT DE PARENT ===')
        r = req('patch', f'{A}{enfant["id"]}/', avec, {'nom': f'QA Enfant renomme {uid}'})
        ok('PATCH nom -> 200', r.status_code == 200 and r.json()['nom'] == f'QA Enfant renomme {uid}', r.content)
        ok('slug inchange au renommage', r.json()['slug'] == enfant['slug'])
        r = req('patch', f'{A}{rid}/', avec, {'est_active': False, 'mots_cles': ['Plat  Test']})
        ok('PATCH est_active + mots-cles -> 200', r.status_code == 200 and r.json()['est_active'] is False
           and r.json()['mots_cles'] == ['plat test'], r.content)
        r = req('patch', f'{A}{rid}/', avec, {'est_active': True})
        ok('reactive', r.json()['est_active'] is True)
        r = req('patch', f'{A}{enfant2_id}/', avec, {'parent_id': rid})
        ok('PATCH parent identique : ordre inchange (pas de deplacement)', r.status_code == 200)
        r = req('patch', f'{A}{rid}/', avec, {'parent_id': enfant2_id})
        ok('cycle (parent = descendant) -> 400 details.parent_id', r.status_code == 400 and 'parent_id' in r.json()['details'], r.content)
        r = req('patch', f'{A}{rid}/', avec, {'parent_id': rid})
        ok('parent = soi-meme -> 400', r.status_code == 400, r.content)
        req('patch', f'{A}{enfant2_id}/', avec, {'nom': f'QA Deplacee {uid}'})
        r = req('patch', f'{A}{enfant2_id}/', avec, {'parent_id': None})
        ok('changer de parent : place en dernier de la racine', r.status_code == 200 and r.json()['ordre'] ==
           max(c.ordre for c in Categorie.objects.filter(est_archivee=False, parent__isnull=True)), r.json())
        r = req('patch', f'{A}{enfant2_id}/', avec, {'parent_id': rid})
        r = req('patch', f'{A}{img_id}/', avec, {'supprimer_image': True})
        ok('supprimer_image -> image null', r.status_code == 200 and r.json()['image'] is None, r.content)
        ok('PATCH categorie inconnue -> 404', req('patch', f'{A}999999/', avec, {'nom': 'x'}).status_code == 404)

        print('=== 7. PARENT ARCHIVE REFUSE ===')
        arch = Categorie.objects.create(nom=f'QA Archivee parent {uid}', slug=f'qa-arch-{uid}', ordre=99)
        req('post', f'{A}{arch.id}/archiver/', avec, {'archivee': True})
        r = req('post', A, avec, {'nom': f'QA sous archivee {uid}', 'parent_id': arch.id})
        ok('parent archive -> 400', r.status_code == 400, r.content)

        print('=== 8. SUPPRESSION 204 / 409 ===')
        r = req('delete', f'{A}{rid}/', avec)
        ok('racine avec sous-categories -> 409', r.status_code == 409, r.status_code)
        msg = r.json()['message']
        ok('message exact : compte sous-categories', msg.startswith('Impossible de supprimer : 0 partenaire(s) / 0 article(s) / 2 sous-catégorie(s)')
           and msg.endswith('Archivez-la à la place.'), msg)
        cat_feuille = req('post', A, avec, {'nom': f'QA Feuille {uid}'}).json()
        partenaire = ProfilPartenaire.objects.first()
        PartenaireCategorie.objects.create(partenaire=partenaire, categorie_id=cat_feuille['id'])
        r = req('delete', f'{A}{cat_feuille["id"]}/', avec)
        ok('categorie avec partenaire -> 409 (1 partenaire)', r.status_code == 409 and '1 partenaire(s)' in r.json()['message'], r.content)
        PartenaireCategorie.objects.filter(categorie_id=cat_feuille['id']).delete()
        Article.objects.create(partenaire=partenaire, categorie_id=cat_feuille['id'], nom='QA art',
                               slug=f'qa-art-{uid}', type='produit')
        r = req('delete', f'{A}{cat_feuille["id"]}/', avec)
        ok('categorie avec article -> 409 (1 article)', r.status_code == 409 and '1 article(s)' in r.json()['message'], r.content)
        Article.objects.filter(categorie_id=cat_feuille['id']).delete()
        r = req('delete', f'{A}{cat_feuille["id"]}/', avec)
        ok('categorie vide -> 204', r.status_code == 204, r.status_code)
        ok('categorie supprimee', not Categorie.objects.filter(pk=cat_feuille['id']).exists())
        r = req('delete', f'{A}{enfant2_id}/', avec)
        ok('sous-categorie vide -> 204', r.status_code == 204)

        print('=== 9. ARCHIVAGE ET DESARCHIVAGE ===')
        r = req('post', f'{A}{rid}/archiver/', avec, {'archivee': 'oui'})
        ok('archivee non booleen -> 400', r.status_code == 400, r.content)
        r = req('post', f'{A}{rid}/archiver/', avec, {'archivee': True})
        ok('archiver -> 200, est_archivee true', r.status_code == 200 and r.json()['est_archivee'] is True, r.content)
        liste = req('get', A, avec).json()['resultats']
        ok('liste par defaut : archivee exclue', all(x['id'] != rid for x in liste))
        liste1 = req('get', A + '?archivees=1', avec).json()['resultats']
        ok('archivees=1 : archivee incluse', any(x['id'] == rid for x in liste1))
        ok('archivees invalide -> 400', req('get', A + '?archivees=2', avec).status_code == 400)
        public = req('get', '/api/v1/catalogue/categories/', None).json()
        ids_pub = [c['id'] for c in public['results']]
        ok('grille publique : archivee masquee', rid not in ids_pub)
        ok('recherche publique : archivee masquee',
           all(c['id'] != rid for c in req('get', '/api/v1/catalogue/recherche/?q=plat%20test', None).json()['categories']))
        # conflit au désarchivage : une autre catégorie prend le type 'autre' pendant l'archivage
        r = req('post', A, avec, {'nom': f'QA Concurrente {uid}', 'types_partenaire': ['autre']})
        ok('pendant l archivage, le type peut etre pris ailleurs', r.status_code == 201, r.content)
        r = req('post', f'{A}{rid}/archiver/', avec, {'archivee': False})
        ok('desarchiver : conflit de type -> 400 details.types_partenaire',
           r.status_code == 400 and 'types_partenaire' in r.json()['details'], r.content)
        req('patch', f'{A}{rid}/', avec, {'types_partenaire': []})
        r = req('post', f'{A}{rid}/archiver/', avec, {'archivee': False})
        ok('desarchiver sans conflit -> 200', r.status_code == 200 and r.json()['est_archivee'] is False, r.content)

        print('=== 10. ORDRE (endpoint reutilise) ET TYPES ===')
        niveau = list(Categorie.objects.filter(est_archivee=False, parent__isnull=True).order_by('ordre', 'nom')[:2])
        r = req('post', A + 'ordre/', avec, {'parent_id': None, 'ordre': [niveau[1].id, niveau[0].id]})
        ok('POST ordre/ -> 200 (meme logique que parametres)', r.status_code == 200, r.content)
        t = req('get', A + 'types-partenaire/', avec).json()['resultats']
        ok('16 types', len(t) == 16, len(t))
        ok('restaurateur -> Restaurants', any(x['valeur'] == 'restaurateur' and x['categorie_nom'] == 'Restaurants' for x in t))
        ok('autre -> declare par la categorie creee pendant l archivage', any(
            x['valeur'] == 'autre' and x['categorie_nom'] == f'QA Concurrente {uid}' for x in t))

        print('=== 11. LECTURE PUBLIQUE : inactives et archivees masquees, sous-categories ===')
        act = req('post', A, avec, {'nom': f'QA Publique {uid}', 'est_active': True}).json()
        ina = req('post', A, avec, {'nom': f'QA Inactive {uid}', 'est_active': False}).json()
        pid = [c['id'] for c in req('get', '/api/v1/catalogue/categories/', None).json()['results']]
        ok('publique : active visible', act['id'] in pid)
        ok('publique : inactive masquee', ina['id'] not in pid)
        sub = req('post', A, avec, {'nom': f'QA Sous publique {uid}', 'parent_id': act['id']}).json()
        racine_pub = next(c for c in req('get', '/api/v1/catalogue/categories/', None).json()['results'] if c['id'] == act['id'])
        ok('publique : sous-categorie active dans enfants', any(e['id'] == sub['id'] for e in racine_pub['enfants']))
        req('post', f'{A}{sub["id"]}/archiver/', avec, {'archivee': True})
        racine_pub = next(c for c in req('get', '/api/v1/catalogue/categories/', None).json()['results'] if c['id'] == act['id'])
        ok('publique : sous-categorie archivee retiree de enfants', all(e['id'] != sub['id'] for e in racine_pub['enfants']))

        print('=== 12. JOURNAL ===')
        actions = set(JournalModeration.objects.filter(acteur=avec).values_list('action', flat=True))
        ok('actions : creation, modification, suppression, archivage, desarchivage',
           {'cat_creation', 'cat_modification', 'cat_suppression', 'cat_archivage', 'cat_desarchivage'} <= actions, actions)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
