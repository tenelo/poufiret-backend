"""Tests : (A) partenaire inactif / supprimé / suspendu / banni absent de toute
réponse publique + endpoints admin ; (B) marqueur « [DEMO] » absent de toute
réponse API, base inchangée ; (C) liste des établissements filtrable par type.

A — familles publiques vérifiées pour chaque état : catégories (compteur),
annuaire, vitrine, articles (liste, détail), sous-ressources, recherche, carte,
restaurants (liste, détail, produits, fiche produit), locations (véhicules,
logements, établissement, hébergement, disponibilités, liste des
établissements), publicités, avis, panier, demande de réservation.
États : masqué (visibilite/), supprimé (supprimer/ → restaurer/), suspendu et
banni (modération) ; retour public après chaque rétablissement.

Autonome : données propres, limitation de débit désactivée, transaction
annulée. Affiche un total OK / KO.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_visibilite_demo_hotels.py
"""
import json, uuid
from datetime import timedelta

from django.contrib.gis.geos import Point
from django.db import transaction
from django.test import Client
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.catalog.models import (
    Article, ArticleImage, Categorie, Hebergement, Logement, PartenaireCategorie, Vehicule,
)
from apps.locations.models import ProfilEtablissement
from apps.publicites.models import FormulePublicite, Publicite
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


def ok(libelle, cond, detail=''):
    global NB_OK
    if cond:
        NB_OK += 1
        print('OK  ', libelle)
    else:
        KO.append(libelle)
        print('FAIL', libelle, detail)


def req(method, url, user=None, corps=None):
    kw = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    fn = getattr(Client(), method)
    if corps is not None:
        return fn(url, json.dumps(corps), content_type='application/json', **kw)
    return fn(url, **kw)


def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel


def resultats(r):
    d = r.json()
    if isinstance(d, dict):
        return d.get('results', d.get('resultats', []))
    return d


try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        mot = f'zvisqa{uid}'
        plan = PlanAbonnement.objects.get(libelle='Basique')
        cat = Categorie.objects.create(nom=f'Visi QA {uid}', slug=f'visi-qa-{uid}', ordre=-100000, est_active=True,
                                       types_partenaire=['restaurateur'], types_articles=['plat', 'produit'])

        def utilisateur(role, **kw):
            u = User.objects.create(telephone=telephone_libre(), username=f't_vis_{uuid.uuid4().hex[:8]}',
                                    role=role, est_verifie=True, first_name='QA', **kw)
            return u

        def partenaire(nom, type_partenaire, **kw):
            p = ProfilPartenaire.objects.create(
                user=utilisateur('partenaire'), plan=plan, nom_commerce=f'{nom} {mot}',
                type_partenaire=type_partenaire, statut='actif', est_visible=True, **kw)
            # Le signal (catalog.signals) peut déjà avoir créé le lien selon le type.
            PartenaireCategorie.objects.get_or_create(partenaire=p, categorie=cat, defaults={'est_principale': True})
            return p

        def article(p, type_article, prix=1000, **kw):
            return Article.objects.create(partenaire=p, categorie=cat, nom=f'{type_article} {mot}',
                                          slug=f'vis-{uuid.uuid4().hex[:10]}', type=type_article, prix=prix,
                                          est_actif=True, **kw)

        boutique = partenaire('Boutique', 'commercant', localisation=Point(-5.2, 9.6, srid=4326),
                              description=f'Boutique centrale.\n[DEMO] Données de démonstration.')
        resto = partenaire('Resto', 'restaurateur')
        garage = partenaire('Garage', 'loueur_voiture')
        agence = partenaire('Agence', 'loueur_maison', description='[DEMO] Données de démonstration.')
        hotel = partenaire('Hotel', 'hotelier', description='Hôtel calme.\n[DEMO] Données de démonstration.')
        residence = partenaire('Residence', 'hotelier')
        hotel_sans_fiche = partenaire('Hotel sans fiche', 'hotelier')
        ProfilEtablissement.objects.create(partenaire=hotel, type_etablissement='hotel', etoiles=3)
        ProfilEtablissement.objects.create(partenaire=residence, type_etablissement='residence_meublee')
        # Tous les partenaires du test (même catégorie, même mot) : sinon ceux non masqués
        # restent légitimement dans le compteur de la catégorie et la recherche.
        tous = [boutique, resto, garage, agence, hotel, residence, hotel_sans_fiche]

        produit = article(boutique, 'produit', description='Savon artisanal.\n[DEMO]')
        ArticleImage.objects.create(article=produit, image='articles/vis.png', est_principale=True)
        plat = article(resto, 'plat')
        a_veh = article(garage, 'vehicule', prix=20000)
        Vehicule.objects.create(article=a_veh, marque='Toyota', modele='Yaris', mode='location')
        a_log = article(agence, 'logement', prix=100000, description='Villa.\n[DEMO]')
        Logement.objects.create(article=a_log, type_logement='villa')
        a_heb = article(hotel, 'hebergement', prix=15000)
        Hebergement.objects.create(article=a_heb, type_hebergement='chambre_double', nb_unites=2)
        a_heb2 = article(residence, 'hebergement', prix=25000)
        Hebergement.objects.create(article=a_heb2, type_hebergement='appartement')
        formule = FormulePublicite.objects.first()
        pub = Publicite.objects.create(partenaire=boutique, formule=formule, titre=f'Pub {mot}',
                                       statut='active', debut_diffusion=timezone.now() - timedelta(hours=1),
                                       image_couverture='publicites/vis.png') if formule else None

        client = utilisateur('client')
        superadmin = utilisateur('admin', is_staff=True, is_superuser=True)
        admin_vis = utilisateur('admin', is_staff=True)
        PermissionsAdmin.objects.create(admin=admin_vis, masquer_partenaire=True, supprimer_soft_partenaire=True,
                                        restaurer_partenaire=True, voir_indicateurs=True, gerer_restaurants=True,
                                        gerer_locations=True, creer_partenaire=True)
        admin_sans = utilisateur('admin', is_staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans)
        J1, J3 = (timezone.localdate() + timedelta(days=1)).isoformat(), (timezone.localdate() + timedelta(days=3)).isoformat()

        def presences():
            """{famille: bool} — présence de NOS partenaires dans chaque famille publique."""
            pr = {}
            grille = resultats(req('get', '/api/v1/catalogue/categories/?page_size=100'))
            ligne = next((c for c in grille if c['id'] == cat.id), {})
            pr['categories (compteur)'] = ligne.get('nb_partenaires', 0) > 0
            ids = {c['id'] for c in req('get', f'/api/v1/catalogue/categories/{cat.slug}/partenaires/').json()}
            pr['annuaire'] = bool(ids & {p.id for p in tous})
            pr['vitrine'] = req('get', f'/api/v1/auth/partenaires/{boutique.id}/').status_code == 200
            pr['articles (liste)'] = bool(resultats(req('get', f'/api/v1/catalogue/articles/?partenaire={boutique.id}')))
            pr['article (detail)'] = req('get', f'/api/v1/catalogue/articles/{produit.slug}/').status_code == 200
            pr['images d article'] = bool(resultats(req('get', f'/api/v1/catalogue/images/?article={produit.id}')))
            rech = req('get', f'/api/v1/catalogue/recherche/?q={mot}').json()
            pr['recherche'] = bool(rech['partenaires'] or rech['articles'])
            pr['carte'] = boutique.id in {c['id'] for c in req('get', f'/api/v1/catalogue/carte/partenaires/?categorie={cat.slug}').json()}
            pr['restaurants (liste)'] = resto.id in {x['id'] for x in req('get', '/api/v1/restaurants/').json()['resultats']}
            pr['restaurant (detail)'] = req('get', f'/api/v1/restaurants/{resto.id}/').status_code == 200
            pr['restaurant (produits)'] = req('get', f'/api/v1/restaurants/{resto.id}/produits/').status_code == 200
            pr['fiche produit'] = req('get', f'/api/v1/restaurants/produits/{plat.id}/').status_code == 200
            pr['vehicules (loueur)'] = req('get', f'/api/v1/locations/partenaires/{garage.id}/vehicules/').status_code == 200
            pr['vehicule (detail)'] = req('get', f'/api/v1/locations/vehicules/{a_veh.id}/').status_code == 200
            pr['vehicule (disponibilites)'] = req('get', f'/api/v1/locations/vehicules/{a_veh.id}/disponibilites/').status_code == 200
            pr['logements (loueur)'] = req('get', f'/api/v1/locations/partenaires/{agence.id}/logements/').status_code == 200
            pr['logement (detail)'] = req('get', f'/api/v1/locations/logements/{a_log.id}/').status_code == 200
            pr['etablissement'] = req('get', f'/api/v1/locations/partenaires/{hotel.id}/etablissement/').status_code == 200
            pr['hebergement (detail)'] = req('get', f'/api/v1/locations/hebergements/{a_heb.id}/').status_code == 200
            pr['etablissements (liste)'] = hotel.id in {x['id'] for x in req('get', '/api/v1/locations/etablissements/').json()['resultats']}
            pr['avis (public)'] = req('get', f'/api/v1/partenaires/{boutique.id}/avis/').status_code == 200
            if pub is not None:
                pr['publicite (detail)'] = req('get', f'/api/v1/publicites/{pub.id}/').status_code == 200
            pr['panier (ajout)'] = req('post', '/api/v1/orders/paniers/ajouter/', client,
                                       {'article': produit.id, 'quantite': 1}).status_code == 201
            pr['reservation (creation)'] = req('post', '/api/v1/reservations/', client, {
                'objet_id': a_veh.id, 'nature': 'reservation', 'date_debut': J1, 'date_fin': J3}).status_code == 201
            return pr

        def verifier(etat, attendu):
            pr = presences()
            mauvais = {f: v for f, v in pr.items() if v != attendu}
            ok(f'{etat} : {"present" if attendu else "absent"} de toutes les familles publiques ({len(pr)})',
               not mauvais, mauvais)

        # ═══════════════════════════════════════════════════════════════
        print('\n=== A. VISIBILITE PUBLIQUE ===')
        verifier('etat initial (public)', True)

        print('--- masque (inactif) ---')
        V = lambda p: f'/api/v1/administration/partenaires/{p.id}/visibilite/'  # noqa: E731
        ok('visibilite sans masquer_partenaire -> 403',
           req('patch', V(boutique), admin_sans, {'est_visible': False}).status_code == 403)
        ok('est_visible non booleen -> 400', req('patch', V(boutique), admin_vis, {'est_visible': 'non'}).status_code == 400)
        for p in tous:
            r = req('patch', V(p), admin_vis, {'est_visible': False, 'motif': 'Fermeture'})
        ok('masquer -> 200, est_visible false, est_public false', r.status_code == 200
           and r.json()['est_visible'] is False and r.json()['est_public'] is False, r.content[:200])
        ok('masquage journalise (partenaire_masque)', JournalModeration.objects.filter(
            acteur=admin_vis, action='partenaire_masque', motif__contains='Fermeture').exists())
        verifier('masque', False)
        for p in tous:
            req('patch', V(p), admin_vis, {'est_visible': True})
        ok('reaffichage journalise (partenaire_affiche)',
           JournalModeration.objects.filter(acteur=admin_vis, action='partenaire_affiche').exists())
        verifier('reaffiche', True)

        print('--- supprime (soft) / restaure ---')
        S = lambda p, action: f'/api/v1/administration/partenaires/{p.id}/{action}/'  # noqa: E731
        ok('supprimer sans capacite -> 403', req('post', S(boutique, 'supprimer'), admin_sans, {}).status_code == 403)
        ok('restaurer un partenaire non supprime -> 409', req('post', S(boutique, 'restaurer'), admin_vis, {}).status_code == 409)
        for p in tous:
            r = req('post', S(p, 'supprimer'), admin_vis, {'motif': 'Doublon'})
        ok('supprimer -> 200, est_supprime true', r.status_code == 200 and r.json()['est_supprime'] is True, r.content[:200])
        ok('suppression journalisee (supprimer_soft)', JournalModeration.objects.filter(
            acteur=admin_vis, action='supprimer_soft').exists())
        verifier('supprime', False)
        ok('reafficher un supprime -> 409', req('patch', V(boutique), admin_vis, {'est_visible': True}).status_code == 409)
        L = '/api/v1/administration/partenaires/liste/'
        ids = lambda r: {x['id'] for x in r.json().get('resultats', r.json())}  # noqa: E731
        ok('liste admin : supprimes exclus par defaut', boutique.id not in ids(req('get', L, admin_vis)))
        r = req('get', L + '?supprimes=1', admin_vis)
        ok('liste admin ?supprimes=1 : corbeille, colonne est_supprime', boutique.id in ids(r)
           and all(x['est_supprime'] for x in r.json().get('resultats', r.json())), r.content[:200])
        for p in tous:
            r = req('post', S(p, 'restaurer'), admin_vis, {})
        ok('restaurer -> 200, de nouveau public', r.status_code == 200 and r.json()['est_public'] is True, r.content[:200])
        verifier('restaure', True)

        print('--- suspendu / banni (moderation existante) ---')
        M = '/api/v1/administration/moderation/'
        for p in tous:
            req('post', M, superadmin, {'cible_id': p.user_id, 'action': 'suspendre', 'motif': 'Controle'})
        verifier('suspendu', False)
        for p in tous:
            req('post', M, superadmin, {'cible_id': p.user_id, 'action': 'reactiver'})
        verifier('reactive', True)
        for p in tous:
            req('post', M, superadmin, {'cible_id': p.user_id, 'action': 'bannir', 'motif': 'Fraude'})
        verifier('banni', False)
        for p in tous:
            req('post', M, superadmin, {'cible_id': p.user_id, 'action': 'reactiver'})
        print('--- drapeau de compte seul (ceinture de securite) ---')
        User.objects.filter(pk=boutique.user_id).update(est_supprime=True)
        ok('compte marque supprime (profil encore actif/visible) -> vitrine 404',
           req('get', f'/api/v1/auth/partenaires/{boutique.id}/').status_code == 404)
        User.objects.filter(pk=boutique.user_id).update(est_supprime=False)

        print('--- listes admin ---')
        req('patch', V(boutique), admin_vis, {'est_visible': False})
        ok('liste partenaires ?visible=0', ids(req('get', L + '?visible=0', admin_vis)) >= {boutique.id}
           and resto.id not in ids(req('get', L + '?visible=0', admin_vis)))
        r = req('get', '/api/v1/restaurants/admin/?visible=1', admin_vis)
        ligne = next((x for x in r.json()['resultats'] if x['id'] == resto.id), None)
        ok('restaurants admin : est_visible / est_supprime / est_public + ?visible', ligne is not None
           and {'est_visible', 'est_supprime', 'est_public'} <= set(ligne), ligne)
        r = req('get', '/api/v1/locations/admin/', admin_vis)
        ligne = next((x for x in r.json()['resultats'] if x['id'] == garage.id), None)
        ok('loueurs admin : est_visible / est_supprime', ligne is not None
           and ligne['est_visible'] is True and ligne['est_supprime'] is False, ligne)
        req('patch', V(boutique), admin_vis, {'est_visible': True})

        # ═══════════════════════════════════════════════════════════════
        print('\n=== B. MARQUEUR [DEMO] MASQUE ===')
        urls = [
            f'/api/v1/auth/partenaires/{boutique.id}/', f'/api/v1/auth/partenaires/{agence.id}/',
            f'/api/v1/catalogue/articles/{produit.slug}/', f'/api/v1/catalogue/articles/?partenaire={boutique.id}',
            f'/api/v1/catalogue/recherche/?q={mot}', f'/api/v1/catalogue/categories/{cat.slug}/partenaires/',
            f'/api/v1/locations/logements/{a_log.id}/', f'/api/v1/locations/partenaires/{hotel.id}/etablissement/',
            f'/api/v1/locations/etablissements/',
        ]
        trouves = [u for u in urls if '[DEMO]' in req('get', u).content.decode()]
        ok('aucune reponse publique ne contient [DEMO]', not trouves, trouves)
        admin_urls = [f'/api/v1/administration/partenaires/{boutique.id}/edition/', L,
                      f'/api/v1/locations/admin/{agence.id}/logements/']
        trouves = [u for u in admin_urls if '[DEMO]' in req('get', u, admin_vis).content.decode()]
        ok('aucune reponse admin ne contient [DEMO]', not trouves, trouves)
        v = req('get', f'/api/v1/auth/partenaires/{boutique.id}/').json()
        ok('texte utile conserve', v['description'] == 'Boutique centrale.', v['description'])
        ok('champ ne contenant que le marqueur -> chaine vide',
           req('get', f'/api/v1/auth/partenaires/{agence.id}/').json()['description'] == '')
        ok('article : marqueur seul retire', req('get', f'/api/v1/catalogue/articles/{produit.slug}/').json()
           ['description'] == 'Savon artisanal.')
        boutique.refresh_from_db(); produit.refresh_from_db(); agence.refresh_from_db()
        ok('base inchangee (marqueurs toujours presents)', '[DEMO] Données de démonstration.' in boutique.description
           and produit.description.endswith('[DEMO]') and agence.description == '[DEMO] Données de démonstration.')

        # ═══════════════════════════════════════════════════════════════
        print('\n=== C. HOTELS / RESIDENCES ===')
        E = '/api/v1/locations/etablissements/'
        lignes = {x['id']: x for x in req('get', E).json()['resultats']}
        nos = {hotel.id, residence.id, hotel_sans_fiche.id}
        ok('liste : nos 3 etablissements', nos <= set(lignes), set(lignes) & nos)
        ok('type_etablissement + libelle par ligne', lignes[residence.id]['type_etablissement'] == 'residence_meublee'
           and lignes[residence.id]['type_etablissement_libelle'] == 'Résidence meublée'
           and lignes[hotel.id]['type_etablissement_libelle'] == 'Hôtel' and lignes[hotel.id]['etoiles'] == 3,
           lignes.get(residence.id))
        ok('hotel sans fiche -> hotel', lignes[hotel_sans_fiche.id]['type_etablissement'] == 'hotel')
        ok('prix nuit min et nb hebergements', lignes[hotel.id]['nb_hebergements'] == 1
           and int(lignes[hotel.id]['prix_nuit_min']) == 15000, lignes[hotel.id])
        ids_h = {x['id'] for x in req('get', E + '?type_etablissement=hotel').json()['resultats']}
        ok('?type_etablissement=hotel', {hotel.id, hotel_sans_fiche.id} <= ids_h and residence.id not in ids_h)
        ids_r = {x['id'] for x in req('get', E + '?type_etablissement=residence_meublee').json()['resultats']}
        ok('?type_etablissement=residence_meublee', residence.id in ids_r and hotel.id not in ids_r)
        ok('type inconnu -> 400', req('get', E + '?type_etablissement=chateau').status_code == 400)
        r = req('get', f'/api/v1/catalogue/categories/{cat.slug}/partenaires/?type_etablissement=residence_meublee')
        ok('annuaire ?type_etablissement=residence_meublee', [c['id'] for c in r.json()] == [residence.id], r.content[:200])
        cartes = {c['id']: c for c in req('get', f'/api/v1/catalogue/categories/{cat.slug}/partenaires/').json()}
        ok('annuaire : type_etablissement (null hors hoteliers)', cartes[hotel.id]['type_etablissement'] == 'hotel'
           and cartes[boutique.id]['type_etablissement'] is None)
        ok('annuaire : type inconnu -> 400', req(
            'get', f'/api/v1/catalogue/categories/{cat.slug}/partenaires/?type_etablissement=x').status_code == 400)

        raise Rollback()
except Rollback:
    print('\nRollback effectue (rien persiste).')

print(f'\n=== TOTAL : {NB_OK} OK / {len(KO)} KO ===')
if KO:
    print('KO :', *KO, sep='\n - ')
    raise SystemExit(1)
