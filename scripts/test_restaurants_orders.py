"""Tests : intégration commandes <-> menus restaurant — ajout au panier
depuis une ligne de menu (prix figé), respect des groupes d'options
obligatoires, blocage si restaurant fermé / heure limite dépassée, stock
journalier (décrément verrouillé, rollback propre si insuffisant,
restauration à l'annulation), filtres admin type_partenaire/restauration.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_restaurants_orders.py
"""
import json, uuid
from datetime import date, datetime, time, timedelta
from django.db import transaction
from django.test import Client
from django.utils import timezone
from django.utils.text import slugify
from rest_framework_simplejwt.tokens import AccessToken
from apps.administration.models import PermissionsAdmin
from apps.catalog.models import Categorie, Article
from apps.orders.models import Commande, LignePanier, Panier
from apps.orders.services import appliquer_transition_commande
from apps.restaurants import services as services_resto
from apps.restaurants.models import LigneMenu, MenuProgramme, ProfilRestaurant
from apps.users.models import HoraireOuverture, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
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

try:
    with transaction.atomic():
        pa = ProfilPartenaire.objects.filter(type_partenaire='restaurateur').first()
        admin_cmd = User.objects.create(telephone='+22507000010', username='t_r_cmd',
            role='admin', is_staff=True, is_superuser=False, est_verifie=True)
        admin_cmd.set_password('0000'); admin_cmd.save()
        PermissionsAdmin.objects.create(admin=admin_cmd, gerer_commandes=True)

        fiche, _ = ProfilRestaurant.objects.get_or_create(partenaire=pa)
        fiche.ferme_exceptionnellement = False
        fiche.save()
        HoraireOuverture.objects.filter(partenaire=pa).delete()

        cat = Categorie.objects.filter(est_archivee=False).first()
        plat = Article.objects.create(partenaire=pa, categorie=cat, nom='Poulet DG QA',
            slug=slugify('poulet-dg-qa-' + str(uuid.uuid4())[:6]), type='plat', prix=3000)
        groupe = plat.groupes_options.create(libelle='Garniture', min_choix=1, max_choix=1)
        opt_riz = groupe.options.create(nom='Riz', prix_supplement=0)
        opt_attieke = groupe.options.create(nom='Attieke', prix_supplement=500)

        aujourdhui = timezone.localdate()
        jour_iso = aujourdhui.isoweekday()
        menu = MenuProgramme.objects.create(
            restaurant=fiche, nature='hebdomadaire', jour_semaine=jour_iso, service='midi',
            heure_debut=time(0, 0), heure_fin=time(23, 59), titre='Menu QA orders',
            publie=True)
        ligne_menu = LigneMenu.objects.create(
            menu=menu, plat=plat, prix_menu=2000, stock_initial=1, ordre=1)

        print('=== FERME : ValiderPanier bloque (restaurant sans horaires) ===')
        r = j('/api/v1/orders/paniers/ajouter/', 'post', pa.user,
              {'ligne_menu': ligne_menu.id, 'quantite': 1,
               'option_ids': [opt_riz.id]})
        ok('ajouter ligne-menu (option garniture ok) -> 201', r.status_code == 201, r.content)
        panier_id = r.json()['id']
        ok('prix_unitaire = prix_menu (frozen)',
           float(r.json()['lignes'][0]['prix_unitaire']) == 2000.0, r.json())
        r = j(f'/api/v1/orders/paniers/{panier_id}/valider/', 'post', pa.user, {})
        ok('valider -> 400 (restaurant ferme, aucun horaire)', r.status_code == 400, r.content)
        ok('message = message_statut du restaurant',
           r.json()['message'] == services_resto.message_statut(fiche), r.json())
        ok('stock non decremente (toujours 1)',
           services_resto.stock_restant(ligne_menu) == 1, services_resto.stock_restant(ligne_menu))

        print('=== OUVERT : options manquantes -> 400 a l ajout ===')
        HoraireOuverture.objects.create(
            partenaire=pa, jour_semaine=jour_iso - 1, ouvert=True,
            heure_ouverture=time(0, 0), heure_fermeture=time(23, 59))
        r = j('/api/v1/orders/paniers/ajouter/', 'post', pa.user,
              {'article': plat.id, 'quantite': 1})
        ok('ajout plat sans garniture -> 400', r.status_code == 400, r.content)
        ok('message cite le groupe Garniture', 'Garniture' in r.json()['message'], r.json())

        print('=== OUVERT : validation OK, stock decremente ===')
        r = j(f'/api/v1/orders/paniers/{panier_id}/valider/', 'post', pa.user, {})
        ok('valider -> 201 (restaurant ouvert)', r.status_code == 201, r.content)
        commande_id = r.json()['id']
        ligne_cmd = r.json()['lignes'][0]
        ok('ligne commande prix_unitaire figé = 2000', float(ligne_cmd['prix_unitaire']) == 2000.0, ligne_cmd)
        ok('supplements contient Riz (groupe_libelle=Garniture)',
           any(s.get('groupe_libelle') == 'Garniture' and s.get('nom') == 'Riz'
               for s in ligne_cmd['supplements']), ligne_cmd)
        ligne_menu.refresh_from_db()
        ok('stock decremente a 0', services_resto.stock_restant(ligne_menu) == 0,
           services_resto.stock_restant(ligne_menu))

        print('=== STOCK INSUFFISANT : 2e commande refusee, aucune commande creee ===')
        r = j('/api/v1/orders/paniers/ajouter/', 'post', pa.user,
              {'ligne_menu': ligne_menu.id, 'quantite': 1, 'option_ids': [opt_riz.id]})
        ok('ajout 2e ligne-menu -> 201', r.status_code == 201, r.content)
        panier2_id = r.json()['id']
        nb_commandes_avant = Commande.objects.filter(partenaire=pa).count()
        r = j(f'/api/v1/orders/paniers/{panier2_id}/valider/', 'post', pa.user, {})
        ok('valider -> 400 (stock insuffisant)', r.status_code == 400, r.content)
        ok('aucune commande supplementaire creee',
           Commande.objects.filter(partenaire=pa).count() == nb_commandes_avant)
        ok('stock toujours a 0 (rollback propre)', services_resto.stock_restant(ligne_menu) == 0)

        print('=== DELAI DEPASSE : heure_limite_commande ===')
        menu.heure_limite_commande = (timezone.localtime(timezone.now()) - timedelta(hours=1)).time()
        menu.save()
        Panier.objects.filter(pk=panier2_id).delete()
        r = j('/api/v1/orders/paniers/ajouter/', 'post', pa.user,
              {'ligne_menu': ligne_menu.id, 'quantite': 1, 'option_ids': [opt_riz.id]})
        panier3_id = r.json()['id']
        r = j(f'/api/v1/orders/paniers/{panier3_id}/valider/', 'post', pa.user, {})
        ok('valider -> 400 (heure limite depassee)', r.status_code == 400, r.content)
        ok('message = heure limite', 'limite' in r.json()['message'], r.json())
        menu.heure_limite_commande = None
        menu.save()
        Panier.objects.filter(pk=panier3_id).delete()

        print('=== ANNULATION : stock restaure ===')
        commande = Commande.objects.get(pk=commande_id)
        ok_transition, _msg = appliquer_transition_commande(
            commande, 'annulee', pa.user, 'client')
        ok('transition annulee OK', ok_transition, _msg)
        ligne_menu.refresh_from_db()
        ok('stock restaure a 1', services_resto.stock_restant(ligne_menu) == 1,
           services_resto.stock_restant(ligne_menu))

        print('=== ADMIN COMMANDES : filtre restauration / type_partenaire ===')
        r = j('/api/v1/orders/admin/meta/', 'get', admin_cmd)
        ok('meta -> 200, types_partenaire present', r.status_code == 200
           and 'types_partenaire' in r.json(), r.content)
        r = j('/api/v1/orders/admin/commandes/?restauration=1', 'get', admin_cmd)
        ok('liste admin restauration=1 -> 200', r.status_code == 200, r.content)
        ids = [c['id'] for c in r.json()['results']] if 'results' in r.json() else \
              [c['id'] for c in r.json()]
        ok('la commande du restaurant y figure', commande.id in ids, ids)
        r = j('/api/v1/orders/admin/commandes/?type_partenaire=restaurateur', 'get', admin_cmd)
        ok('liste admin type_partenaire=restaurateur -> 200', r.status_code == 200, r.content)
        r = j('/api/v1/orders/admin/commandes/?type_partenaire=zzz', 'get', admin_cmd)
        ok('type_partenaire invalide -> 400', r.status_code == 400, r.content)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
