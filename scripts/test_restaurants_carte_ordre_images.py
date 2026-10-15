"""Tests : carte publique restaurants — images absolues des plats et des
lignes de menu, ordre sections/plats (ordre puis nom), lignes de menu par
ordre, endpoint .../carte/plats/ordre/ (restaurateur + admin), lignes
renvoyées par menus_du_jour / menus_en_vigueur_maintenant.

Partie 0 : diagnostic en LECTURE SEULE sur Chez Capi (id 53) + extrait JSON
réel du premier plat de sa carte. Le reste se déroule dans une transaction
annulée (rien n'est persisté ; les images de test n'écrivent aucun fichier).

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_restaurants_carte_ordre_images.py
"""
import json
from datetime import time

from django.db import transaction
from django.test import Client
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.catalog.models import Article, ArticleImage, SectionMenu
from apps.restaurants import services
from apps.restaurants.models import LigneMenu, MenuProgramme
from apps.users.models import ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
# Limitation de débit DRF désactivée pour ce script : sinon tous les scripts partagent
# le compteur anonyme (60/min, client de test = 127.0.0.1) et la suite complète reçoit des 429.
from unittest import mock as _mock_debit
from rest_framework.views import APIView as _APIViewDebit
_mock_debit.patch.object(_APIViewDebit, 'get_throttles', return_value=[]).start()
NB = 0


class Rollback(Exception):
    pass


def ok(libelle, cond, detail=''):
    global NB
    print(('OK   ' if cond else 'FAIL '), libelle, '' if cond else detail)
    assert cond, f'{libelle} {detail}'
    NB += 1


def j(url, user=None, method='get', corps=None):
    kw = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    fn = getattr(Client(), method)
    if corps is not None:
        return fn(url, json.dumps(corps), content_type='application/json', **kw)
    return fn(url, **kw)


def plats_carte(data):
    return [p for s in data['carte'] for p in s['plats']]


# ═══════════════════════════════════════════════════════════════════════
# 0. DIAGNOSTIC CHEZ CAPI (lecture seule)
# ═══════════════════════════════════════════════════════════════════════
print('\n=== 0. CHEZ CAPI (id 53) ===')
capi = ProfilPartenaire.objects.filter(pk=53).first()
if capi is None:
    print('Partenaire 53 introuvable : diagnostic ignore.')
else:
    print(f'{capi.nom_commerce} : type={capi.type_partenaire} statut={capi.statut} visible={capi.est_visible}')
    for a in Article.objects.filter(partenaire=capi, nom__icontains='spaghetti').select_related('section_menu'):
        print(f'  plat {a.id} « {a.nom} » type={a.type} actif={a.est_actif} '
              f'reserve_menus={a.est_reserve_aux_menus} section={a.section_menu_id}'
              f'{"" if a.section_menu is None else " (active=%s)" % a.section_menu.est_active}')
        for i in a.images.all():
            existe = bool(i.image) and i.image.storage.exists(i.image.name)
            print(f'    image {i.id} principale={i.est_principale} active={i.est_active} '
                  f'ordre={i.ordre} nom={i.image.name!r} fichier_present={existe}')
    r = j('/api/v1/restaurants/53/')
    ok('GET /restaurants/53/ -> 200', r.status_code == 200, r.content[:300])
    plats = plats_carte(r.json())
    if plats:
        print('Extrait JSON reel, 1er plat de la carte :')
        print(json.dumps(plats[0], ensure_ascii=False, indent=2))
    spag = [p for p in plats if 'spaghetti' in p['nom'].lower()]
    for p in spag:
        print(f'  carte : « {p["nom"]} » image={p["image"]}')
    avec_image = {a.id for a in Article.objects.filter(partenaire=capi, nom__icontains='spaghetti')
                  if any(i.est_active and i.image for i in a.images.all())}
    ok('Spaghetti de la carte ayant une image active : image absolue',
       all((p['image'] or '').startswith('http') for p in spag if p['id'] in avec_image), spag)
    ok('toutes les images de la carte sont absolues ou null',
       all(p['image'] is None or p['image'].startswith('http') for p in plats))

# ═══════════════════════════════════════════════════════════════════════
# 1..5 — transaction annulée
# ═══════════════════════════════════════════════════════════════════════
try:
    with transaction.atomic():
        pa = ProfilPartenaire.objects.filter(type_partenaire='restaurateur').first()
        autre_pa = ProfilPartenaire.objects.filter(type_partenaire='restaurateur').exclude(id=pa.id).first()
        # Visible publiquement le temps du test (annulé au rollback).
        pa.statut, pa.est_visible = ProfilPartenaire.Statut.ACTIF, True
        pa.save(update_fields=['statut', 'est_visible'])
        fiche = services.fiche_de(pa)
        # Même résolution que la création de plat par l'API (le partenaire
        # de test peut n'avoir encore aucun article), repli sur une catégorie quelconque.
        from apps.catalog.models import Categorie
        from apps.restaurants.views_carte import _categorie_par_defaut
        categorie = _categorie_par_defaut(pa) or Categorie.objects.order_by('id').first()
        ok('categorie disponible pour les plats de test', categorie is not None)

        admin_sans = User.objects.create(telephone='+22507100001', username='t_ord_sans', role='admin',
                                         is_staff=True, is_superuser=False, est_verifie=True)
        PermissionsAdmin.objects.create(admin=admin_sans)
        admin_avec = User.objects.create(telephone='+22507100002', username='t_ord_avec', role='admin',
                                         is_staff=True, is_superuser=False, est_verifie=True)
        PermissionsAdmin.objects.create(admin=admin_avec, gerer_restaurants=True)

        sec_b = SectionMenu.objects.create(partenaire=pa, nom='QA Zeta', ordre=-500)
        sec_a = SectionMenu.objects.create(partenaire=pa, nom='qa alpha', ordre=-500)
        sec_c = SectionMenu.objects.create(partenaire=pa, nom='QA Aaa', ordre=-400)

        def plat(nom, ordre, section=sec_a, partenaire=pa):
            return Article.objects.create(
                partenaire=partenaire, categorie=categorie, type=Article.Type.PLAT, nom=nom,
                slug=f'qa-ord-{nom.lower().replace(" ", "-")}-{partenaire.id}', prix=1000,
                section_menu=section, ordre=ordre, est_actif=True)

        p_b = plat('QA Bissap', 2)
        p_a = plat('qa attieke', 2)
        p_c = plat('QA Choukouya', 1)
        p_autre_section = plat('QA Garba', 1, section=sec_b)

        def image(article, nom, ordre, principale=False, active=True):
            return ArticleImage.objects.create(article=article, image=f'articles/{nom}.png',
                                               ordre=ordre, est_principale=principale, est_active=active)

        image(p_a, 'qa_a_2', 2)
        image(p_a, 'qa_a_principale', 5, principale=True)
        image(p_b, 'qa_b_3', 3)
        image(p_b, 'qa_b_1', 1)
        image(p_b, 'qa_b_0_inactive', 0, active=False)

        print('\n=== 1. IMAGES DE LA CARTE ===')
        r = j(f'/api/v1/restaurants/{pa.id}/')
        ok('GET detail -> 200', r.status_code == 200, r.content[:300])
        data = r.json()
        par_id = {p['id']: p for p in plats_carte(data)}
        ok('image principale, URL absolue',
           par_id[p_a.id]['image'] == f'https://{HOST}/media/articles/qa_a_principale.png', par_id[p_a.id]['image'])
        ok('sans principale : 1re image active par ordre',
           par_id[p_b.id]['image'] == f'https://{HOST}/media/articles/qa_b_1.png', par_id[p_b.id]['image'])
        ok('sans image -> null', par_id[p_c.id]['image'] is None)

        print('\n=== 2. ORDRE SECTIONS ET PLATS ===')
        ids_sections = [s['id'] for s in data['carte']]
        ok('sections : ordre puis nom (qa alpha, QA Zeta, QA Aaa)',
           [i for i in ids_sections if i in (sec_a.id, sec_b.id, sec_c.id)] == [sec_a.id, sec_b.id, sec_c.id],
           ids_sections)
        cles = [(s['ordre'], s['nom'].casefold()) for s in data['carte']]
        ok('toutes les sections triees (ordre, nom)', cles == sorted(cles), cles)
        section_a = next(s for s in data['carte'] if s['id'] == sec_a.id)
        ok('plats : ordre puis nom (Choukouya[1], attieke[2], Bissap[2])',
           [p['id'] for p in section_a['plats']] == [p_c.id, p_a.id, p_b.id],
           [(p['nom']) for p in section_a['plats']])

        print('\n=== 3. MENU A 2 LIGNES : services + API ===')
        MenuProgramme.objects.filter(restaurant=fiche).update(publie=False)
        service = MenuProgramme.Service.choices[0][0]
        menu = MenuProgramme.objects.create(
            restaurant=fiche, nature=MenuProgramme.Nature.DATE, date=timezone.localdate(),
            service=service, heure_debut=time(0, 0), heure_fin=time(23, 59, 59),
            titre='Menu QA', publie=True)
        LigneMenu.objects.create(menu=menu, plat=p_b, prix_menu=1500, ordre=2)
        LigneMenu.objects.create(menu=menu, plat=p_a, prix_menu=1200, ordre=1)
        mj = services.menus_du_jour(fiche)
        ok('menus_du_jour renvoie le menu', mj[service] is not None and mj[service].id == menu.id, mj)
        ok('menus_du_jour : 2 lignes', mj[service].lignes.count() == 2)
        mv = services.menus_en_vigueur_maintenant(fiche)
        ok('menus_en_vigueur_maintenant : le menu, 2 lignes',
           service in mv and mv[service].id == menu.id and mv[service].lignes.count() == 2, mv)

        data = j(f'/api/v1/restaurants/{pa.id}/').json()
        for cle in ('menus_du_jour', 'menus_en_vigueur_maintenant'):
            lignes = data[cle][service]['lignes']
            ok(f'API {cle} : 2 lignes triees par ordre',
               [l['plat'] for l in lignes] == [p_a.id, p_b.id], lignes)
            ok(f'API {cle} : plat_image absolue (meme regle)',
               lignes[0]['plat_image'] == f'https://{HOST}/media/articles/qa_a_principale.png'
               and lignes[1]['plat_image'] == f'https://{HOST}/media/articles/qa_b_1.png', lignes)

        print('\n=== 4. POST .../carte/plats/ordre/ (restaurateur) ===')
        url_mon = '/api/v1/restaurants/mon-restaurant/carte/plats/ordre/'
        r = j(url_mon, pa.user, 'post', {'section_id': sec_a.id, 'ordre': [p_b.id, p_c.id, p_a.id]})
        ok('-> 200', r.status_code == 200, r.content)
        ok('reponse : plats de la section dans le nouvel ordre',
           [p['id'] for p in r.json()] == [p_b.id, p_c.id, p_a.id], r.json())
        for p, rang in ((p_b, 1), (p_c, 2), (p_a, 3)):
            p.refresh_from_db()
            ok(f'{p.nom} ordre={rang}, trace restaurateur',
               p.ordre == rang and p.modifie_par_role == 'restaurateur', (p.ordre, p.modifie_par_role))
        section_a = next(s for s in j(f'/api/v1/restaurants/{pa.id}/').json()['carte'] if s['id'] == sec_a.id)
        ok('carte publique suit le nouvel ordre',
           [p['id'] for p in section_a['plats']] == [p_b.id, p_c.id, p_a.id])

        r = j(url_mon, pa.user, 'post', {'section_id': sec_a.id, 'ordre': [p_a.id]})
        ok('liste partielle -> 200 : listes 1..n, les autres suivent',
           r.status_code == 200 and [p['id'] for p in r.json()] == [p_a.id, p_b.id, p_c.id], r.content)
        r = j(url_mon, pa.user, 'post', {'section_id': sec_a.id, 'ordre': [p_a.id, p_autre_section.id]})
        ok('plat d\'une autre section -> 400', r.status_code == 400
           and r.json()['plats_invalides'] == [p_autre_section.id], r.content)
        if autre_pa:
            p_etranger = plat('QA Etranger', 1, section=None, partenaire=autre_pa)
            r = j(url_mon, pa.user, 'post', {'section_id': sec_a.id, 'ordre': [p_etranger.id]})
            ok('plat d\'un autre restaurant -> 400', r.status_code == 400, r.content)
            sec_etrangere = SectionMenu.objects.create(partenaire=autre_pa, nom='QA etrangere')
            r = j(url_mon, pa.user, 'post', {'section_id': sec_etrangere.id, 'ordre': [p_a.id]})
            ok('section d\'un autre restaurant -> 400', r.status_code == 400, r.content)
        for corps, libelle in (({'section_id': sec_a.id, 'ordre': [p_a.id, p_a.id]}, 'doublon'),
                               ({'section_id': sec_a.id, 'ordre': []}, 'liste vide'),
                               ({'ordre': [p_a.id]}, 'section_id absent'),
                               ({'section_id': sec_a.id, 'ordre': 'x'}, 'ordre invalide')):
            ok(f'{libelle} -> 400', j(url_mon, pa.user, 'post', corps).status_code == 400)
        ok('client (non restaurateur) -> 403',
           j(url_mon, User.objects.filter(role='client').first(), 'post',
             {'section_id': sec_a.id, 'ordre': [p_a.id]}).status_code == 403)

        print('\n=== 5. POST admin/<id>/carte/plats/ordre/ ===')
        url_admin = f'/api/v1/restaurants/admin/{pa.id}/carte/plats/ordre/'
        corps = {'section_id': sec_a.id, 'ordre': [p_c.id, p_b.id, p_a.id]}
        ok('admin sans gerer_restaurants -> 403', j(url_admin, admin_sans, 'post', corps).status_code == 403)
        avant = JournalModeration.objects.count()
        r = j(url_admin, admin_avec, 'post', corps)
        ok('admin avec capacite -> 200', r.status_code == 200
           and [p['id'] for p in r.json()] == [p_c.id, p_b.id, p_a.id], r.content)
        p_c.refresh_from_db()
        ok('trace admin', p_c.ordre == 1 and p_c.modifie_par_role == 'admin', p_c.modifie_par_role)
        ok('journal resto_plat_modif ecrit', JournalModeration.objects.count() == avant + 1
           and JournalModeration.objects.order_by('-cree_le').first().action == 'resto_plat_modif')
        superadmin = User.objects.filter(is_superuser=True).first()
        ok('super-admin -> 200', j(url_admin, superadmin, 'post', corps).status_code == 200)
        if autre_pa:
            r = j(f'/api/v1/restaurants/admin/{autre_pa.id}/carte/plats/ordre/', admin_avec, 'post', corps)
            ok('admin : section d\'un autre partenaire -> 400', r.status_code == 400, r.content)

        raise Rollback('annulation volontaire')
except Rollback as e:
    print('\nRollback effectue :', e)

ok('rien persiste', not Article.objects.filter(slug__startswith='qa-ord-').exists()
   and not User.objects.filter(username__startswith='t_ord_').exists())
print(f'\n=== TOTAL : {NB} verifications reussies ===')
