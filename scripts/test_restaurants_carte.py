"""Tests : gestion de la carte sous les deux périmètres restaurants
(mon-restaurant/ et admin/<partenaire_id>/) — sections, plats (categorie
auto-résolue, section/ordre/disponibilité/réservé aux menus), raccourci
épuisé, images (+ quota du plan, comme /catalogue/ existant), variantes,
groupes d'options + options. Traçabilité modifie_par_role/nom/le, journal
admin (resto_plat_modif), droits (403 sans capacité, 400 cross-restaurant),
non-régression des endpoints /catalogue/ existants pour le même partenaire.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_restaurants_carte.py
"""
import io, json, uuid
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client
from PIL import Image
from rest_framework_simplejwt.tokens import AccessToken
from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.catalog.models import Article
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
def png_1px():
    buf = io.BytesIO()
    Image.new('RGB', (1, 1)).save(buf, format='PNG')
    return buf.getvalue()
PNG_1PX = png_1px()

class Rollback(Exception): pass
NB = 0
def ok(l, c, d=''):
    global NB
    print(('OK   ' if c else 'FAIL '), l, '' if c else d)
    assert c, f'{l} {d}'
    NB += 1
def h(user):
    return {'HTTP_AUTHORIZATION': f'Bearer {AccessToken.for_user(user)}', 'HTTP_HOST': HOST}
def j(url, method, user, corps=None):
    c = Client()
    fn = getattr(c, method)
    kw = {'secure': True, **h(user)}
    if corps is not None:
        return fn(url, json.dumps(corps), content_type='application/json', **kw)
    return fn(url, **kw)
def upload(url, user, data):
    c = Client()
    return c.post(url, data, secure=True, **h(user))

try:
    with transaction.atomic():
        pa = ProfilPartenaire.objects.filter(type_partenaire='restaurateur').first()
        # Quota photos fixé explicitement (3) : ne dépend pas du plan réel du partenaire.
        pa.plan = PlanAbonnement.objects.filter(nb_photos_par_article=3).first()
        pa.save()
        autre_pa = ProfilPartenaire.objects.filter(
            type_partenaire='restaurateur').exclude(id=pa.id).first()
        admin_sans = User.objects.create(telephone='+22507000030', username='t_r_carte_sans',
            role='admin', is_staff=True, is_superuser=False, est_verifie=True)
        admin_sans.set_password('0000'); admin_sans.save()
        PermissionsAdmin.objects.create(admin=admin_sans)
        admin_avec = User.objects.create(telephone='+22507000031', username='t_r_carte_avec',
            role='admin', is_staff=True, is_superuser=False, est_verifie=True)
        admin_avec.set_password('0000'); admin_avec.save()
        PermissionsAdmin.objects.create(admin=admin_avec, gerer_restaurants=True)

        base_mon = '/api/v1/restaurants/mon-restaurant/carte'
        base_admin = f'/api/v1/restaurants/admin/{pa.id}/carte'

        print('=== SECTIONS (restaurateur) ===')
        r = j(f'{base_mon}/sections/', 'post', pa.user,
              {'nom': 'Grillades CARTE-QA', 'ordre': 1})
        ok('POST section -> 201', r.status_code == 201, r.content)
        section_id = r.json()['id']
        ok('traçabilité restaurateur', r.json()['modifie_par_role'] == 'restaurateur', r.json())
        r = j(f'{base_mon}/sections/', 'get', pa.user)
        ok('GET sections -> 200, la section y figure',
           r.status_code == 200 and any(s['id'] == section_id for s in r.json()['results']), r.content)

        print('=== SECTIONS (admin) ===')
        r = j(f'{base_admin}/sections/', 'get', admin_sans)
        ok('admin sans capacite -> 403', r.status_code == 403, r.content)
        r = j(f'{base_admin}/sections/{section_id}/', 'patch', admin_avec, {'ordre': 2})
        ok('admin avec capacite : PATCH section -> 200', r.status_code == 200 and r.json()['ordre'] == 2, r.content)
        ok('traçabilité admin', r.json()['modifie_par_role'] == 'admin', r.json())
        nb_journal_avant = JournalModeration.objects.filter(
            cible=pa.user, action='resto_plat_modif').count()
        ok('journal resto_plat_modif trace (section modifiee par admin)', nb_journal_avant >= 1)

        print('=== PLATS (restaurateur) : creation, categorie auto-resolue ===')
        r = j(f'{base_mon}/plats/', 'post', pa.user, {
            'nom': 'Poulet Yassa CARTE-QA', 'description': 'Mariné citron oignons',
            'prix': 3500, 'section_menu': section_id, 'ordre': 1})
        ok('POST plat -> 201', r.status_code == 201, r.content)
        plat_id = r.json()['id']
        ok('categorie auto-resolue (non vide)', r.json()['categorie'] is not None, r.json())
        ok('type force a plat', Article.objects.get(pk=plat_id).type == 'plat')
        ok('section_menu_nom expose', r.json()['section_menu_nom'] == 'Grillades CARTE-QA', r.json())
        ok('traçabilité restaurateur', r.json()['modifie_par_role'] == 'restaurateur', r.json())

        print('=== PLATS : filtres ?section=&reserve_aux_menus= ===')
        r = j(f'{base_mon}/plats/?section={section_id}', 'get', pa.user)
        ok('filtre section -> contient le plat', any(p['id'] == plat_id for p in r.json()['results']), r.content)
        r = j(f'{base_mon}/plats/{plat_id}/', 'patch', pa.user, {'est_reserve_aux_menus': True})
        ok('PATCH est_reserve_aux_menus=true -> 200', r.status_code == 200 and r.json()['est_reserve_aux_menus'] is True)
        r = j(f'{base_mon}/plats/?reserve_aux_menus=1', 'get', pa.user)
        ok('filtre reserve_aux_menus=1 -> contient le plat', any(p['id'] == plat_id for p in r.json()['results']), r.content)
        r = j(f'{base_mon}/plats/?reserve_aux_menus=0', 'get', pa.user)
        ok('filtre reserve_aux_menus=0 -> ne contient plus le plat', not any(p['id'] == plat_id for p in r.json()['results']))
        j(f'{base_mon}/plats/{plat_id}/', 'patch', pa.user, {'est_reserve_aux_menus': False})

        print('=== PLATS : section d\'un autre restaurant refusee ===')
        autre_section = j(f'/api/v1/restaurants/admin/{autre_pa.id}/carte/sections/', 'post',
                          admin_avec, {'nom': 'Section autre resto', 'ordre': 1}).json()
        r = j(f'{base_mon}/plats/', 'post', pa.user, {
            'nom': 'Plat section invalide', 'prix': 1000, 'section_menu': autre_section['id']})
        ok('section d\'un autre restaurant -> 400', r.status_code == 400, r.content)

        print('=== PLATS : raccourci epuise ===')
        r = j(f'{base_mon}/plats/{plat_id}/epuise/', 'post', pa.user, {'epuise': True})
        ok('POST epuise=true -> 200, est_disponible=false', r.status_code == 200
           and r.json()['est_disponible'] is False and r.json()['est_epuise'] is True, r.content)
        r = j(f'{base_admin}/plats/{plat_id}/epuise/', 'post', admin_avec, {'epuise': False})
        ok('admin : POST epuise=false -> 200, de nouveau disponible',
           r.status_code == 200 and r.json()['est_disponible'] is True, r.content)
        ok('traçabilité admin sur epuise', r.json()['modifie_par_role'] == 'admin', r.json())

        print('=== IMAGES DU PLAT ===')
        r = upload(f'{base_mon}/plats/{plat_id}/images/', pa.user,
                   {'article': plat_id, 'image': SimpleUploadedFile('p1.png', PNG_1PX, content_type='image/png'),
                    'est_principale': 'true'})
        ok('POST image 1 -> 201', r.status_code == 201, r.content)
        r = j(f'{base_mon}/plats/{plat_id}/images/', 'get', pa.user)
        ok('GET images -> 1', r.status_code == 200 and len(r.json()['results']) == 1, r.content)
        # Quota du plan = 3 : 2 images de plus doivent passer, la 4e doit etre refusee.
        for i in range(2):
            r = upload(f'{base_mon}/plats/{plat_id}/images/', pa.user,
                       {'article': plat_id,
                        'image': SimpleUploadedFile(f'p{i+2}.png', PNG_1PX, content_type='image/png')})
            ok(f'POST image {i+2} -> 201 (sous le quota)', r.status_code == 201, r.content)
        r = upload(f'{base_mon}/plats/{plat_id}/images/', pa.user,
                   {'article': plat_id, 'image': SimpleUploadedFile('p4.png', PNG_1PX, content_type='image/png')})
        ok('POST image 4 -> 403 (quota atteint, comme /catalogue/ existant)', r.status_code == 403, r.content)

        print('=== VARIANTES (?plat=) ===')
        r = j(f'{base_mon}/variantes/', 'post', pa.user,
              {'article': plat_id, 'nom': 'Grande taille', 'prix_supplement': 500})
        ok('POST variante -> 201', r.status_code == 201, r.content)
        r = j(f'{base_mon}/variantes/?plat={plat_id}', 'get', pa.user)
        ok('GET variantes ?plat= -> 1', r.status_code == 200 and len(r.json()['results']) == 1, r.content)
        r = j(f'{base_mon}/variantes/', 'post', pa.user,
              {'article': autre_pa.articles.first().id if autre_pa.articles.exists() else 999999,
               'nom': 'Invalide', 'prix_supplement': 0})
        ok('variante sur un plat d\'un autre restaurant -> 400', r.status_code == 400, r.content)

        print('=== GROUPES D\'OPTIONS + OPTIONS (?plat=/?groupe=) ===')
        r = j(f'{base_mon}/groupes-options/', 'post', pa.user,
              {'article': plat_id, 'libelle': 'Garniture', 'min_choix': 1, 'max_choix': 1})
        ok('POST groupe-option -> 201', r.status_code == 201, r.content)
        groupe_id = r.json()['id']
        r = j(f'{base_mon}/groupes-options/?plat={plat_id}', 'get', pa.user)
        ok('GET groupes-options ?plat= -> 1', r.status_code == 200 and len(r.json()['results']) == 1, r.content)
        r = j(f'{base_mon}/options/', 'post', pa.user,
              {'groupe': groupe_id, 'nom': 'Riz', 'prix_supplement': 0})
        ok('POST option -> 201', r.status_code == 201, r.content)
        r = j(f'{base_mon}/options/?groupe={groupe_id}', 'get', pa.user)
        ok('GET options ?groupe= -> 1', r.status_code == 200 and len(r.json()['results']) == 1, r.content)

        print('=== ADMIN : creation plat + suppression (avec capacite) ===')
        r = j(f'{base_admin}/plats/', 'post', admin_avec, {'nom': 'Plat admin CARTE-QA', 'prix': 1200})
        ok('admin cree un plat -> 201', r.status_code == 201, r.content)
        plat_admin_id = r.json()['id']
        ok('traçabilité admin', r.json()['modifie_par_role'] == 'admin', r.json())
        r = j(f'{base_admin}/plats/{plat_admin_id}/', 'delete', admin_avec)
        ok('admin supprime son plat -> 204', r.status_code == 204, r.content)
        r = j(f'{base_admin}/plats/', 'post', admin_sans, {'nom': 'Refuse', 'prix': 100})
        ok('admin sans capacite : POST plat -> 403', r.status_code == 403, r.content)

        print('=== NON-REGRESSION : /catalogue/ existant toujours fonctionnel ===')
        r = j(f'/api/v1/catalogue/articles/?partenaire={pa.id}&type=plat', 'get', pa.user)
        ok('liste /catalogue/articles/ -> 200, le plat y figure',
           r.status_code == 200 and any(a['id'] == plat_id for a in r.json()['results']), r.content)
        r = j(f'/api/v1/catalogue/variantes/?article={plat_id}', 'get', pa.user)
        ok('variantes via /catalogue/ (meme donnee) -> 1', r.status_code == 200 and len(r.json()['results']) == 1, r.content)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
