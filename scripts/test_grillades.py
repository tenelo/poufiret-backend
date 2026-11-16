"""Tests : profil partenaire « Grillades » (type grilleur, gabarit grillades)
et formats (variantes) avec photo facultative.

- gabarit : grilleur -> grillades (moteur restaurant, menus désactivés,
  libellé des variantes « Formats »), restauration (TYPES_RESTAURATION),
  fiche restaurant créée, catégorie rattachée par types_partenaire ;
- carte : sections, articles (type plat), formats avec et sans image
  (multipart, partenaire et admin), image remplacée puis retirée,
  formats actifs par défaut en multipart ; API app : image (URL absolue)
  et prix_a_partir_de ;
- panier : format obligatoire (aucun format -> 400 « Choisissez un format »),
  format par défaut appliqué, format inconnu / d'un autre article / inactif
  -> 400, article sans format inchangé ;
- ouverture appliquée aux articles de la carte (fermé exceptionnellement,
  hors horaires, sans horaires -> 400 message_statut ; ouvert -> 201) ;
  commerce hors restauration non concerné ;
- menus refusés (gabarit) ; commande : filtre admin ?restauration=1 et
  ?type_partenaire=grilleur ; notification admin sur le canal restaurant.

Données propres, transaction annulée (rien ne persiste), médias dans un
dossier temporaire, limitation de débit désactivée, total OK / KO.
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_grillades.py
"""
import io
import json
import shutil
import tempfile
import uuid
from datetime import time
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from django.test.utils import override_settings
from django.utils import timezone
from PIL import Image
from rest_framework_simplejwt.tokens import AccessToken

from apps.catalog.models import Article, Categorie, PartenaireCategorie, Variante
from apps.geo.models import Departement
from apps.moderation.models import Notification
from apps.notifications.canaux import commande_est_restaurant
from apps.orders.models import Commande
from apps.orders.services import _notifier_admins_commande
from apps.restaurants import gabarits
from apps.restaurants import services as services_resto
from apps.restaurants.models import ProfilRestaurant
from apps.users.models import HoraireOuverture, PlanAbonnement, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
# Limitation de débit DRF désactivée pour ce script : sinon tous les scripts partagent
# le compteur anonyme (60/min, client de test = 127.0.0.1) et la suite complète reçoit des 429.
from unittest import mock as _mock_debit
from rest_framework.views import APIView as _APIViewDebit
_mock_debit.patch.object(_APIViewDebit, 'get_throttles', return_value=[]).start()

MON = '/api/v1/restaurants/mon-restaurant'
PANIER = '/api/v1/orders/paniers/ajouter/'


class Rollback(Exception):
    pass


NB_OK, KO = 0, []


def ok(libelle, cond, detail=''):
    global NB_OK
    if cond:
        NB_OK += 1
        print('OK  ', libelle)
    else:
        KO.append(libelle)
        print('FAIL', libelle, str(detail)[:500])


def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel


def utilisateur(role='client', **kw):
    return User.objects.create(telephone=telephone_libre(), username=f't_grill_{uuid.uuid4().hex[:8]}',
                               role=role, est_verifie=True, **kw)


def entetes(user=None):
    e = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        e['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    return e


def req(method, url, user=None, corps=None):
    c = Client()
    if corps is None:
        return getattr(c, method)(url, **entetes(user))
    return getattr(c, method)(url, json.dumps(corps), content_type='application/json', **entetes(user))


def multipart(method, url, user, donnees):
    c = Client()
    if method == 'post':
        return c.post(url, donnees, **entetes(user))
    return getattr(c, method)(url, encode_multipart(BOUNDARY, donnees), content_type=MULTIPART_CONTENT,
                              **entetes(user))


def image(nom='format.png', couleur=(200, 120, 30)):
    tampon = io.BytesIO()
    Image.new('RGB', (60, 40), couleur).save(tampon, format='PNG')
    return SimpleUploadedFile(nom, tampon.getvalue(), content_type='image/png')


def contenu(r):
    try:
        return json.dumps(r.json(), ensure_ascii=False)[:400]
    except Exception:
        return r.content[:400]


dossier_media = tempfile.mkdtemp(prefix='test_grillades_')
try:
    with override_settings(MEDIA_ROOT=dossier_media), transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        dep = Departement.objects.filter(est_actif=True).order_by('id').first()
        cat = Categorie.objects.create(nom=f'Grillades & Braisés {uid}', slug=f'qa-grillades-{uid}',
                                       types_partenaire=['grilleur'], types_articles=['plat'], ordre=950)
        g_user = utilisateur('partenaire')
        grilleur = ProfilPartenaire.objects.create(
            user=g_user, plan=plan, nom_commerce=f'Chez Mariam {uid}', type_partenaire='grilleur',
            statut='actif', est_visible=True, departement=dep)
        superadmin = utilisateur('admin', is_staff=True, is_superuser=True)
        client = utilisateur('client')

        print('=== 1. TYPE ET GABARIT ===')
        ok('choix grilleur (« Grillades / Braisé »)', dict(ProfilPartenaire.TypePartenaire.choices).get(
            'grilleur') == 'Grillades / Braisé')
        ok('gabarit grilleur = grillades', gabarits.gabarit_de(grilleur) == 'grillades')
        ok('grilleur dans le moteur et dans la restauration', 'grilleur' in gabarits.TYPES_MOTEUR
           and 'grilleur' in services_resto.TYPES_RESTAURATION
           and {'restaurateur', 'fast_food'} <= set(services_resto.TYPES_RESTAURATION))
        ok('restaurateur : gabarit restaurant inchange', gabarits.gabarit_de_type('restaurateur') == 'restaurant')
        meta = req('get', '/api/v1/restaurants/meta/gabarits/').json()
        ok('meta/gabarits : grillades sans menus, variantes « Formats »', meta.get('grillades', {}).get(
            'menus_actifs') is False and meta['grillades']['libelle_variantes'] == 'Formats'
           and meta['grillades']['libelle'] == 'Grillades & Braisés' and meta['restaurant']['menus_actifs'] is True,
           meta.get('grillades'))
        ok('fiche restaurant creee (moteur)', ProfilRestaurant.objects.filter(partenaire=grilleur).exists())
        ok('categorie « Grillades & Braises » rattachee (types_partenaire)', PartenaireCategorie.objects.filter(
            partenaire=grilleur, categorie=cat).exists())

        print('=== 2. CARTE ET FORMATS ===')
        r = req('post', f'{MON}/carte/sections/', g_user, {'nom': 'Poissons'})
        ok('section -> 201', r.status_code == 201, contenu(r))
        section = r.json()['id']

        def article(nom, prix=None):
            corps = {'nom': nom, 'section_menu': section}
            if prix is not None:
                corps['prix'] = prix
            r = req('post', f'{MON}/carte/plats/', g_user, corps)
            ok(f'article {nom} -> 201', r.status_code == 201, contenu(r))
            return r.json()

        poisson = article('Poisson braisé')
        porc = article('Porc au four')
        brochettes = article('Brochettes', 1000)
        ok('articles de type plat', Article.objects.get(pk=poisson['id']).type == 'plat')

        formats = {}
        for nom, prix in (('Petit', 2500), ('Moyen', 3000), ('Gros', 3500)):
            r = multipart('post', f'{MON}/carte/variantes/', g_user,
                          {'article': poisson['id'], 'nom': nom, 'prix': prix, 'image': image(f'{nom}.png')})
            d = r.json() if r.status_code == 201 else {}
            ok(f'format {nom} avec image (multipart) -> 201, actif par defaut', r.status_code == 201
               and d.get('image') and d['image'].startswith('http') and d['est_active'] is True
               and d['est_par_defaut'] is False and d['est_epuise'] is False, contenu(r))
            formats[nom] = d.get('id')
        v = Variante.objects.get(pk=formats['Petit'])
        ok('image stockee sous catalogue/variantes/', v.image.name.startswith('catalogue/variantes/'), v.image.name)
        for nom, prix in (('500 F', 500), ('1 000 F', 1000), ('1 500 F', 1500)):
            r = req('post', f'{MON}/carte/variantes/', g_user, {'article': porc['id'], 'nom': nom, 'prix': prix})
            ok(f'format porc {nom} sans image (JSON) -> 201, image null', r.status_code == 201
               and r.json()['image'] is None, contenu(r))
            formats[f'porc {nom}'] = r.json().get('id')

        ADM = f'/api/v1/restaurants/admin/{grilleur.id}/carte/variantes/'
        r = multipart('post', ADM, superadmin, {'article': poisson['id'], 'nom': 'Geant', 'prix': 5000,
                                                'image': image('g.png')})
        ok('admin : format avec image (multipart) -> 201', r.status_code == 201 and r.json()['image'], contenu(r))
        geant = r.json()['id']
        avant = Variante.objects.get(pk=geant).image.name
        r = multipart('patch', f'{ADM}{geant}/', superadmin, {'image': image('g2.png', (10, 10, 200))})
        ok('admin : image remplacee (PATCH multipart), format reste actif', r.status_code == 200
           and Variante.objects.get(pk=geant).image.name != avant and r.json()['est_active'] is True, contenu(r))
        r = req('patch', f'{ADM}{geant}/', superadmin, {'image': None})
        ok('admin : image retiree (PATCH image null)', r.status_code == 200 and r.json()['image'] is None
           and not Variante.objects.get(pk=geant).image, contenu(r))
        r = req('delete', f'{ADM}{geant}/', superadmin)
        ok('admin : suppression du format -> 204', r.status_code == 204)
        r = req('get', f'{MON}/carte/variantes/?plat={poisson["id"]}', g_user)
        lignes = r.json()['results'] if isinstance(r.json(), dict) else r.json()
        ok('partenaire : liste des formats avec image', r.status_code == 200 and len(lignes) == 3
           and all(x['image'] for x in lignes), contenu(r))

        def produits():
            r = req('get', f'/api/v1/restaurants/{grilleur.id}/produits/')
            d = r.json()
            return {x['id']: x for x in (d['results'] if isinstance(d, dict) and 'results' in d else d)}

        p = produits()
        ok('app : formats du poisson avec image (URL absolue)', [
            (x['nom'], bool(x['image']) and x['image'].startswith('http')) for x in p[poisson['id']]['variantes']]
           == [('Petit', True), ('Moyen', True), ('Gros', True)], p[poisson['id']]['variantes'])
        ok('app : formats du porc sans image (null)', all(
            x['image'] is None for x in p[porc['id']]['variantes']) and len(p[porc['id']]['variantes']) == 3)
        ok('app : prix_a_partir_de (poisson 2500, porc 500, brochettes 1000 sans format)', (
            Decimal(str(p[poisson['id']]['prix_a_partir_de'])), Decimal(str(p[porc['id']]['prix_a_partir_de'])),
            Decimal(str(p[brochettes['id']]['prix_a_partir_de']))) == (2500, 500, 1000),
           [p[i]['prix_a_partir_de'] for i in (poisson['id'], porc['id'], brochettes['id'])])
        Variante.objects.filter(pk=formats['Petit']).update(est_epuise=True)
        ok('app : Petit epuise -> prix_a_partir_de 3000', Decimal(str(produits()[poisson['id']]['prix_a_partir_de']))
           == 3000)
        Variante.objects.filter(pk=formats['Petit']).update(est_epuise=False)
        d = req('get', f'/api/v1/restaurants/produits/{poisson["id"]}/').json()
        ok('fiche produit : formats avec image + prix_a_partir_de', Decimal(str(d['prix_a_partir_de'])) == 2500
           and all(x['image'] for x in d['variantes']) and d['partenaire']['gabarit'] == 'grillades', d)
        d = req('get', f'/api/v1/restaurants/{grilleur.id}/').json()
        ok('detail public : gabarit grillades', d.get('gabarit') == 'grillades', d.get('gabarit'))

        print('=== 3. MENUS REFUSES ===')
        r = req('post', f'{MON}/menus/', g_user, {
            'nature': 'date', 'date': str(timezone.localdate()), 'service': 'midi',
            'heure_debut': '11:00', 'heure_fin': '14:00', 'titre': 'Menu'})
        ok('creation de menu -> 400 (gabarit grillades)', r.status_code == 400
           and 'gabarit' in (r.json().get('details') or {}), contenu(r))

        print('=== 4. PANIER : FORMAT OBLIGATOIRE ===')

        def ajouter(art, **kw):
            return req('post', PANIER, client, {'article': art['id'], 'quantite': 1, **kw})

        def ligne(r, art):
            return next((l for l in r.json().get('lignes', []) if l['article'] == art['id']), None)

        r = ajouter(poisson)
        ok('sans format, sans format par defaut -> 400 « Choisissez un format »', r.status_code == 400
           and r.json()['message'] == 'Choisissez un format.', contenu(r))
        r = ajouter(poisson, variante_id=999999999)
        ok('format inconnu -> 400', r.status_code == 400 and 'Format inconnu' in r.json()['message'], contenu(r))
        r = ajouter(poisson, variante_id=formats['porc 500 F'])
        ok('format d un autre article -> 400', r.status_code == 400, contenu(r))
        r = ajouter(poisson, variante_id='abc')
        ok('format non numerique -> 400', r.status_code == 400, contenu(r))
        Variante.objects.filter(pk=formats['Gros']).update(est_active=False)
        r = ajouter(poisson, variante_id=formats['Gros'])
        ok('format inactif -> 400', r.status_code == 400, contenu(r))
        Variante.objects.filter(pk=formats['Gros']).update(est_active=True)
        r = ajouter(poisson, variante_id=formats['Petit'])
        l = ligne(r, poisson)
        ok('format Petit -> 201, prix 2500', r.status_code == 201 and l and l['variante_id'] == formats['Petit']
           and Decimal(str(l['prix_unitaire'])) == 2500, contenu(r))
        r = req('patch', f'{MON}/carte/variantes/{formats["Moyen"]}/', g_user, {'est_par_defaut': True})
        ok('Moyen devient le format par defaut', r.status_code == 200 and r.json()['est_par_defaut'] is True, contenu(r))
        r = ajouter(poisson)
        moyen = [x for x in r.json().get('lignes', []) if x['variante_id'] == formats['Moyen']]
        ok('sans format -> format par defaut applique (Moyen, 3000)', r.status_code == 201 and moyen
           and Decimal(str(moyen[0]['prix_unitaire'])) == 3000, contenu(r))
        Variante.objects.filter(pk=formats['Gros']).update(est_epuise=True)
        ok('format epuise -> 400 (inchange)', ajouter(poisson, variante_id=formats['Gros']).status_code == 400)
        r = ajouter(brochettes)
        l = ligne(r, brochettes)
        ok('article sans format : sans variante -> 201, prix de l article (inchange)', r.status_code == 201 and l
           and l['variante_id'] is None and Decimal(str(l['prix_unitaire'])) == 1000, contenu(r))
        r = ajouter(porc, variante_id=formats['porc 1 000 F'], quantite=2)
        l = ligne(r, porc)
        ok('porc 1 000 F x2 -> 201, sans image, prix 1000', r.status_code == 201 and l
           and Decimal(str(l['prix_unitaire'])) == 1000, contenu(r))

        print('=== 5. OUVERTURE : MEME REGLE QUE LES MENUS POUR LES ARTICLES DE LA CARTE ===')
        panier_id = r.json()['id']
        jour = timezone.localdate().isoweekday() - 1  # HoraireOuverture : 0 = lundi

        def valider():
            return req('post', f'/api/v1/orders/paniers/{panier_id}/valider/', client, {'mode_livraison': 'emporter'})

        fiche = ProfilRestaurant.objects.get(partenaire=grilleur)
        fiche.services = ['sur_place', 'emporter', 'livraison']
        fiche.ferme_exceptionnellement, fiche.motif_fermeture = True, 'Congés'
        fiche.save()
        HoraireOuverture.objects.filter(partenaire=grilleur).delete()
        HoraireOuverture.objects.create(partenaire=grilleur, jour_semaine=jour, ouvert=True,
                                        heure_ouverture=time(0, 0), heure_fermeture=time(23, 59))
        nb_avant = Commande.objects.filter(partenaire=grilleur).count()
        r = valider()
        ok('grilleur ferme exceptionnellement -> 400, meme message que les menus (message_statut)',
           r.status_code == 400 and r.json()['message'] == services_resto.message_statut(fiche)
           and 'Fermé exceptionnellement' in r.json()['message'], contenu(r))
        fiche.ferme_exceptionnellement, fiche.motif_fermeture = False, ''
        fiche.save()
        HoraireOuverture.objects.filter(partenaire=grilleur).delete()
        HoraireOuverture.objects.create(partenaire=grilleur, jour_semaine=(jour + 1) % 7, ouvert=True,
                                        heure_ouverture=time(0, 0), heure_fermeture=time(23, 59))
        r = valider()
        ok('grilleur hors horaires (ouvert demain seulement) -> 400, message_statut',
           r.status_code == 400 and not services_resto.est_ouvert(fiche)
           and r.json()['message'] == services_resto.message_statut(fiche), contenu(r))
        HoraireOuverture.objects.filter(partenaire=grilleur).delete()
        r = valider()
        ok('grilleur sans horaires -> 400 (« Horaires non renseignés », comme les menus)',
           r.status_code == 400 and r.json()['message'] == services_resto.message_statut(fiche), contenu(r))
        ok('aucune commande creee pendant les refus', Commande.objects.filter(partenaire=grilleur).count() == nb_avant)
        HoraireOuverture.objects.create(partenaire=grilleur, jour_semaine=jour, ouvert=True,
                                        heure_ouverture=time(0, 0), heure_fermeture=time(23, 59))
        r = valider()
        ok('grilleur ouvert -> validation du panier 201', r.status_code == 201, contenu(r))

        # Commerce hors restauration, sans fiche ni horaires : non concerné.
        com_user = utilisateur('partenaire')
        commerce = ProfilPartenaire.objects.create(
            user=com_user, plan=plan, nom_commerce=f'Boutique {uid}', type_partenaire='commercant',
            statut='actif', est_visible=True, departement=dep)
        cat_com = Categorie.objects.create(nom=f'QA Commerce {uid}', slug=f'qa-commerce-grill-{uid}', ordre=951)
        savon = Article.objects.create(partenaire=commerce, categorie=cat_com, nom=f'Savon {uid}',
                                       slug=f'savon-grill-{uid}', type='produit', prix=1500)
        r_c = req('post', PANIER, client, {'article': savon.id, 'quantite': 1})
        ok('commerce : ajout au panier -> 201', r_c.status_code == 201, contenu(r_c))
        r_c = req('post', f'/api/v1/orders/paniers/{r_c.json()["id"]}/valider/', client, {'mode_livraison': 'emporter'})
        ok('commerce non restaurant, sans horaires : validation 201 (non concerne)', r_c.status_code == 201
           and not HoraireOuverture.objects.filter(partenaire=commerce).exists(), contenu(r_c))

        print('=== 6. COMMANDE : FILTRE RESTAURATION ET CANAL ===')
        commande = Commande.objects.get(pk=r.json()['id'])
        ok('commande : formats enregistres (Moyen, Petit, 1 000 F)', {
            x.get('variante_nom') for x in r.json()['lignes']} >= {'Petit', 'Moyen', '1 000 F'}, r.json()['lignes'])

        def ids_admin(params):
            r = req('get', '/api/v1/orders/admin/commandes/?' + '&'.join(f'{k}={v}' for k, v in params.items()),
                    superadmin)
            d = r.json()
            return {x['id'] for x in (d['results'] if isinstance(d, dict) and 'results' in d else d)}

        ok('admin ?restauration=1 : commande du grilleur presente', commande.id in ids_admin(
            {'restauration': 1, 'partenaire': grilleur.id, 'page_size': 100}))
        ok('admin ?type_partenaire=grilleur : commande presente', commande.id in ids_admin(
            {'type_partenaire': 'grilleur', 'page_size': 100}))
        ok('commande_est_restaurant -> True', commande_est_restaurant(commande) is True)
        _notifier_admins_commande(commande, 'commande_nouvelle', 'Nouvelle commande', 'Test grillades')
        notif = Notification.objects.filter(user=superadmin, type='commande_nouvelle',
                                            data__commande_id=commande.id).first()
        ok('notification admin commande_nouvelle : canal restaurant', notif is not None
           and notif.canal == 'restaurant', getattr(notif, 'canal', None))

        raise Rollback()
except Rollback:
    print('\nRollback effectue (rien persiste).')
finally:
    shutil.rmtree(dossier_media, ignore_errors=True)

print(f'\n=== TOTAL : {NB_OK} OK / {len(KO)} KO ===')
if KO:
    print('KO :', *KO, sep='\n - ')
    raise SystemExit(1)
