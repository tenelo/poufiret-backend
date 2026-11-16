"""Tests : pubs Poufiret (pubs maison du carrousel) et parcours « Découvrir Poufiret ».

- droits admin : sans gerer_pubs_poufiret -> 403, partenaire -> 403, anonyme -> 401 ;
  capacité privilégiée (accordable par le super-admin seul), False par défaut ;
- CRUD et image (multipart), journal ; catégorie invalide (désactivée, archivée,
  parent inaccessible, absente) -> 400 ; sous-catégorie et parente acceptées ;
  categorie_disponible côté admin ;
- ordre (pubs et écrans) ; portée (tout / région / département, utilisateur
  sans département) et dates ;
- placement dans `elements` : k = 0, k < N, k = N, k = 2N+1, moins de pubs maison
  que de places ; aucun doublon ; rotation (affichages du jour puis ordre) ;
- flag publicite_active éteint ; pubs_maison_actives éteint ; `publicites` inchangé ;
- impression et clic, personne touchée une seule fois ; pubs partenaires non touchées ;
- stats (par pub, liste, période) ; export CSV ;
- parcours : publier refusé hors 3 à 8 écrans, version incrémentée, decouvrir
  actif / inactif, bouton null si catégorie indisponible ; réglages.

Le flag waffle et la sélection des pubs partenaires sont simulés (mock) : le
script ne dépend ni des pubs réelles ni de l'état du flag, et ne touche pas
au cache waffle. Données propres, transaction annulée (rien ne persiste),
médias dans un dossier temporaire, limitation de débit désactivée.
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_publicites_poufiret.py
"""
import io
import json
import shutil
import tempfile
import uuid
from datetime import timedelta
from unittest import mock

from django.db import transaction
from django.test import Client
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from django.test.utils import override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.administration.views import CAPACITES_PRIVILEGIEES
from apps.catalog.models import Categorie
from apps.geo.models import Departement
from apps.publicites.models import (EcranDecouverte, FormulePublicite, ImpressionPublicite,
                                    ImpressionPubPoufiret, ParametresPoufiret, Publicite,
                                    PubPoufiret)
from apps.publicites.serializers import PubliciteListSerializer
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
# Limitation de débit DRF désactivée pour ce script : sinon tous les scripts partagent
# le compteur anonyme (60/min, client de test = 127.0.0.1) et la suite complète reçoit des 429.
from rest_framework.views import APIView as _APIViewDebit
mock.patch.object(_APIViewDebit, 'get_throttles', return_value=[]).start()

A = '/api/v1/publicites/admin/poufiret/'
CARROUSEL = '/api/v1/publicites/carrousel/'
DECOUVRIR = '/api/v1/publicites/decouvrir/'
CHAMPS_MAISON = {'type', 'id', 'titre', 'texte', 'image_couverture', 'duree_affichage_secondes', 'categorie'}


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
    return User.objects.create(telephone=telephone_libre(), username=f't_pouf_{uuid.uuid4().hex[:8]}',
                               role=role, est_verifie=True, **kw)


def entetes(user=None):
    e = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        e['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    return e


def image(nom='pouf.png', couleur=(30, 120, 200)):
    tampon = io.BytesIO()
    Image.new('RGB', (40, 40), couleur).save(tampon, format='PNG')
    return SimpleUploadedFile(nom, tampon.getvalue(), content_type='image/png')


def details(r):
    try:
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception:
        return r.content[:300].decode('utf-8', 'replace')


dossier_media = tempfile.mkdtemp(prefix='test_poufiret_')
try:
    with override_settings(MEDIA_ROOT=dossier_media), transaction.atomic():
        c = Client()
        uid = uuid.uuid4().hex[:6]
        maintenant = timezone.now()
        # Isolation : pubs Poufiret / écrans existants mis de côté (rollback à la fin).
        PubPoufiret.objects.update(est_active=False)
        EcranDecouverte.objects.update(est_actif=False)
        params = ParametresPoufiret.obtenir()
        ParametresPoufiret.objects.filter(pk=params.pk).update(
            pubs_maison_actives=True, frequence_pub_maison=3, duree_affichage_secondes=5, parcours_actif=False)

        superadmin = utilisateur('admin', is_staff=True, is_superuser=True)
        admin_avec = utilisateur('admin', is_staff=True)
        PermissionsAdmin.objects.create(admin=admin_avec, gerer_pubs_poufiret=True)
        admin_sans = utilisateur('admin', is_staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans, gerer_formules_pub=True, voir_stats=True)
        p_user = utilisateur('partenaire')
        plan = PlanAbonnement.objects.get(libelle='Basique')
        partenaire = ProfilPartenaire.objects.create(
            user=p_user, plan=plan, nom_commerce=f'Boutique Pouf {uid}', type_partenaire='commercant',
            statut='actif', est_visible=True)

        dep1 = Departement.objects.filter(est_actif=True).select_related('region').first()
        dep2 = Departement.objects.filter(est_actif=True).exclude(region=dep1.region).select_related('region').first()
        assert dep1 and dep2, 'Il faut au moins deux départements dans deux régions différentes.'
        client_dep1 = utilisateur('client', departement=dep1)
        client_sans_dep = utilisateur('client')

        def cat(nom, **kw):
            return Categorie.objects.create(nom=f'{nom} {uid}', slug=f'pouf-{nom.lower()}-{uid}', ordre=900, **kw)

        cat_ok = cat('Mode')
        cat_parente = cat('Beaute')
        cat_enfant = cat('Coiffure', parent=cat_parente)
        cat_off = cat('Bientot', est_active=False)
        cat_arch = cat('Archivee', est_archivee=True)
        cat_parent_off = cat('ParentOff', est_active=False)
        cat_sous_off = cat('SousOff', parent=cat_parent_off)

        print('=== 1. DROITS ===')
        ok('capacite gerer_pubs_poufiret : False par defaut, privilegiee',
           PermissionsAdmin._meta.get_field('gerer_pubs_poufiret').default is False
           and 'gerer_pubs_poufiret' in CAPACITES_PRIVILEGIEES)
        for url in (A + 'pubs/', A + 'ecrans/', A + 'reglages/', A + 'stats/'):
            ok(f'{url} : admin avec la capacite -> 200', c.get(url, **entetes(admin_avec)).status_code == 200)
            ok(f'{url} : super-admin -> 200', c.get(url, **entetes(superadmin)).status_code == 200)
            ok(f'{url} : admin sans la capacite -> 403', c.get(url, **entetes(admin_sans)).status_code == 403)
            ok(f'{url} : partenaire -> 403', c.get(url, **entetes(p_user)).status_code == 403)
            ok(f'{url} : anonyme -> 401', c.get(url, **entetes()).status_code == 401)
        ok('publier : admin sans la capacite -> 403',
           c.post(A + 'parcours/publier/', **entetes(admin_sans)).status_code == 403)
        ok('creation : anonyme -> 401', c.post(A + 'pubs/', {'titre': 'x'}, **entetes()).status_code == 401)
        # Listes des formulaires Angular (catégorie cible, région, département) :
        # lisibles avec gerer_pubs_poufiret seul ; écriture toujours refusée.
        for url in ('/api/v1/administration/categories/', '/api/v1/administration/geo/regions/options/',
                    '/api/v1/administration/geo/departements/options/'):
            ok(f'{url} : lecture avec gerer_pubs_poufiret seul -> 200',
               c.get(url, **entetes(admin_avec)).status_code == 200)
            ok(f'{url} : admin sans la capacite -> 403', c.get(url, **entetes(admin_sans)).status_code == 403)
        r = c.get('/api/v1/administration/categories/', **entetes(admin_avec))
        ok('categories : la categorie de test est dans la liste', cat_ok.id in {
            x['id'] for x in r.json()['resultats']}, details(r)[:300])
        r = c.get('/api/v1/administration/geo/departements/options/', {'region': dep1.region_id}, **entetes(admin_avec))
        ok('departements/options?region= : departement 1 present', dep1.id in {
            x['id'] for x in r.json()['resultats']}, details(r)[:300])
        ok('categories : creation toujours refusee avec gerer_pubs_poufiret seul -> 403', c.post(
            '/api/v1/administration/categories/', json.dumps({'nom': f'Interdite {uid}'}),
            content_type='application/json', **entetes(admin_avec)).status_code == 403)
        ok('carrousel et decouvrir : publics (anonyme -> 200)', c.get(CARROUSEL, **entetes()).status_code == 200
           and c.get(DECOUVRIR, **entetes()).status_code == 200)

        print('=== 2. CRUD, IMAGE, CATEGORIE ===')

        def creer(user=admin_avec, **champs):
            donnees = {'titre': f'Pub maison {uid}', 'categorie': cat_ok.id, 'image_couverture': image(), **champs}
            return c.post(A + 'pubs/', {k: v for k, v in donnees.items() if v is not None}, **entetes(user))

        r = creer(image_couverture=None)
        ok('sans image -> 400', r.status_code == 400 and 'Image' in details(r), details(r))
        r = creer(categorie=None)
        ok('sans categorie -> 400', r.status_code == 400, details(r))
        for libelle, categorie, attendu in (('desactivee', cat_off, 'désactivée'), ('archivee', cat_arch, 'archivée'),
                                            ('parent inaccessible', cat_sous_off, 'inaccessible')):
            r = creer(categorie=categorie.id)
            ok(f'categorie {libelle} -> 400, message clair', r.status_code == 400 and attendu in details(r), details(r))
        r = creer(titre=f'Sous-categorie {uid}', categorie=cat_enfant.id)
        ok('sous-categorie acceptee -> 201', r.status_code == 201, details(r))
        r = creer(titre=f'Parente {uid}', categorie=cat_parente.id)
        ok('categorie parente acceptee -> 201', r.status_code == 201, details(r))
        r = creer(texte='Découvrez la mode', ordre=4)
        d = r.json()
        ok('creation -> 201, champs', r.status_code == 201 and d['titre'] == f'Pub maison {uid}'
           and d['texte'] == 'Découvrez la mode' and d['categorie'] == cat_ok.id and d['categorie_disponible'] is True
           and d['portee'] == 'tout' and d['image_couverture'] and d['nb_impressions'] == 0, d)
        pub = PubPoufiret.objects.get(pk=d['id'])
        ok('multipart sans est_active : pub active par defaut', d['est_active'] is True and pub.est_active is True, d)
        r = creer(titre=f'Inactive {uid}', est_active='false')
        ok('multipart est_active=false : pub inactive', r.status_code == 201 and r.json()['est_active'] is False,
           details(r))
        ok('cree_par + image enregistree', pub.cree_par_id == admin_avec.id and pub.image_couverture.name.startswith(
            'publicites/poufiret/'), pub.image_couverture.name)
        ok('journal pub_poufiret_creer', JournalModeration.objects.filter(
            action='pub_poufiret_creer', acteur=admin_avec, motif__contains=str(pub.id)).exists())
        r = creer(portee='region')
        ok('portee region sans region -> 400', r.status_code == 400 and 'Région obligatoire' in details(r), details(r))
        r = creer(portee='departement', region=dep1.region_id)
        ok('portee departement sans departement -> 400', r.status_code == 400, details(r))
        r = creer(titre=f'Region {uid}', portee='region', region=dep1.region_id, departement=dep2.id)
        ok('portee region : departement remis a null', r.status_code == 201 and r.json()['region'] == dep1.region_id
           and r.json()['departement'] is None, details(r))
        r = creer(date_debut=(maintenant + timedelta(days=2)).isoformat(), date_fin=(maintenant + timedelta(days=1)).isoformat())
        ok('date_fin avant date_debut -> 400', r.status_code == 400, details(r))

        r = c.get(A + f'pubs/{pub.id}/', **entetes(admin_avec))
        ok('GET detail', r.status_code == 200 and r.json()['id'] == str(pub.id))
        r = c.patch(A + f'pubs/{pub.id}/', json.dumps({'titre': f'Pub renommee {uid}'}),
                    content_type='application/json', **entetes(admin_avec))
        ok('PATCH titre (JSON)', r.status_code == 200 and r.json()['titre'] == f'Pub renommee {uid}', details(r))
        ok('journal pub_poufiret_modif', JournalModeration.objects.filter(
            action='pub_poufiret_modif', motif__contains=str(pub.id)).exists())
        ancienne = PubPoufiret.objects.get(pk=pub.pk).image_couverture.name
        r = c.patch(A + f'pubs/{pub.id}/', encode_multipart(BOUNDARY, {'image_couverture': image('b.png', (200, 10, 10))}),
                    content_type=MULTIPART_CONTENT, **entetes(admin_avec))
        ok('PATCH image (multipart)', r.status_code == 200
           and PubPoufiret.objects.get(pk=pub.pk).image_couverture.name != ancienne, details(r))
        r = c.patch(A + f'pubs/{pub.id}/', json.dumps({'categorie': cat_arch.id}),
                    content_type='application/json', **entetes(admin_avec))
        ok('PATCH vers une categorie archivee -> 400', r.status_code == 400, details(r))
        a_supprimer = creer(titre=f'A supprimer {uid}').json()['id']
        r = c.delete(A + f'pubs/{a_supprimer}/', **entetes(admin_avec))
        ok('DELETE -> 204, supprimee + journal', r.status_code == 204 and not PubPoufiret.objects.filter(
            pk=a_supprimer).exists() and JournalModeration.objects.filter(
            action='pub_poufiret_suppr', motif__contains=a_supprimer).exists())
        ok('DELETE inconnue -> 404', c.delete(A + f'pubs/{uuid.uuid4()}/', **entetes(admin_avec)).status_code == 404)
        Categorie.objects.filter(pk=cat_parente.pk).update(est_active=False)
        lignes = {x['id']: x for x in c.get(A + 'pubs/', {'page_size': 100}, **entetes(admin_avec)).json()['results']}
        touchees = [x['categorie_disponible'] for x in lignes.values()
                    if x['titre'] in (f'Parente {uid}', f'Sous-categorie {uid}')]
        ok('categorie devenue indisponible (parente desactivee) : categorie_disponible false (pub et sous-categorie)',
           touchees == [False, False] and lignes[str(pub.id)]['categorie_disponible'] is True, touchees)
        Categorie.objects.filter(pk=cat_parente.pk).update(est_active=True)

        print('=== 3. ORDRE ===')
        PubPoufiret.objects.update(est_active=False)
        M = [PubPoufiret.objects.create(titre=f'M{i} {uid}', categorie=cat_ok, ordre=i, cree_par=superadmin,
                                        image_couverture='publicites/poufiret/m.jpg') for i in range(3)]
        ids = [str(m.id) for m in reversed(M)]
        r = c.post(A + 'pubs/ordre/', json.dumps({'ids': ids}), content_type='application/json', **entetes(admin_avec))
        ok('reordonnancement -> 200, ordre = position', r.status_code == 200 and [
            PubPoufiret.objects.get(pk=i).ordre for i in ids] == [0, 1, 2], details(r))
        r = c.post(A + 'pubs/ordre/', json.dumps({'ids': ids + [str(uuid.uuid4())]}),
                   content_type='application/json', **entetes(admin_avec))
        ok('ordre : id inconnu -> 400', r.status_code == 400, details(r))
        ok('ordre : liste vide -> 400', c.post(A + 'pubs/ordre/', json.dumps({'ids': []}),
                                             content_type='application/json', **entetes(admin_avec)).status_code == 400)
        for i, m in enumerate(M):  # retour a l'ordre M0, M1, M2
            PubPoufiret.objects.filter(pk=m.pk).update(ordre=i)

        # ── Carrousel : flag et pubs partenaires simulés ──
        formule = FormulePublicite.objects.create(nom=f'Formule Pouf {uid}', prix=5000, duree_jours=7,
                                                  quota_partenaires=1000, types_affichage=['carrousel'])
        partenaires = [Publicite.objects.create(
            partenaire=partenaire, formule=formule, titre=f'P{i} {uid}', statut='active',
            image_couverture='publicites/couvertures/p.jpg', debut_diffusion=maintenant - timedelta(days=1),
            fin_diffusion=maintenant + timedelta(days=5)) for i in range(7)]

        def carrousel(k, user=None, flag=True):
            with mock.patch('apps.publicites.views.flag_is_active', return_value=flag), \
                    mock.patch('apps.publicites.services.selectionner_pubs', return_value=partenaires[:k]):
                r = c.get(CARROUSEL, **entetes(user))
            assert r.status_code == 200, r.content[:300]
            return r.json()

        def types(d):
            return ''.join('P' if e['type'] == 'partenaire' else 'M' for e in d['elements'])

        def maisons(d):
            return [e['id'] for e in d['elements'] if e['type'] == 'poufiret']

        print('=== 4. PORTEE ET DATES ===')
        G = {
            'tout': PubPoufiret.objects.create(titre=f'G tout {uid}', categorie=cat_ok, ordre=10,
                                               image_couverture='publicites/poufiret/g.jpg'),
            'region1': PubPoufiret.objects.create(titre=f'G region {uid}', categorie=cat_ok, ordre=11,
                                                  portee='region', region=dep1.region,
                                                  image_couverture='publicites/poufiret/g.jpg'),
            'dep2': PubPoufiret.objects.create(titre=f'G dep2 {uid}', categorie=cat_ok, ordre=12,
                                               portee='departement', departement=dep2,
                                               image_couverture='publicites/poufiret/g.jpg'),
            'futur': PubPoufiret.objects.create(titre=f'G futur {uid}', categorie=cat_ok, ordre=13,
                                                date_debut=maintenant + timedelta(days=1),
                                                image_couverture='publicites/poufiret/g.jpg'),
            'passe': PubPoufiret.objects.create(titre=f'G passe {uid}', categorie=cat_ok, ordre=14,
                                                date_fin=maintenant - timedelta(hours=1),
                                                image_couverture='publicites/poufiret/g.jpg'),
            'en_cours': PubPoufiret.objects.create(titre=f'G en cours {uid}', categorie=cat_ok, ordre=15,
                                                   date_debut=maintenant - timedelta(days=1),
                                                   date_fin=maintenant + timedelta(days=1),
                                                   image_couverture='publicites/poufiret/g.jpg'),
            'inactive': PubPoufiret.objects.create(titre=f'G inactive {uid}', categorie=cat_ok, ordre=16,
                                                   est_active=False, image_couverture='publicites/poufiret/g.jpg'),
            'cat_off': PubPoufiret.objects.create(titre=f'G cat off {uid}', categorie=cat_off, ordre=17,
                                                  image_couverture='publicites/poufiret/g.jpg'),
        }
        PubPoufiret.objects.filter(pk__in=[m.pk for m in M]).update(est_active=False)
        gid = {k: str(v.id) for k, v in G.items()}
        visibles = {gid['tout'], gid['region1'], gid['dep2'], gid['en_cours']}
        ok('anonyme : tout, region, departement, en cours (pas futur / passe / inactive / categorie off)',
           set(maisons(carrousel(0))) == visibles, maisons(carrousel(0)))
        ok('utilisateur sans departement : voit tout', set(maisons(carrousel(0, client_sans_dep))) == visibles)
        ok('utilisateur du departement 1 : tout + sa region, pas le departement 2', set(
            maisons(carrousel(0, client_dep1))) == visibles - {gid['dep2']}, maisons(carrousel(0, client_dep1)))
        ok('admin/pubs ?en_cours=true', {x['id'] for x in c.get(A + 'pubs/', {'en_cours': 'true', 'page_size': 100},
                                                                  **entetes(admin_avec)).json()['results']}
           >= visibles and gid['futur'] not in {x['id'] for x in c.get(
               A + 'pubs/', {'en_cours': 'true', 'page_size': 100}, **entetes(admin_avec)).json()['results']})
        ok('admin/pubs ?est_active=false', gid['inactive'] in {x['id'] for x in c.get(
            A + 'pubs/', {'est_active': 'false', 'page_size': 100}, **entetes(admin_avec)).json()['results']})
        PubPoufiret.objects.filter(pk__in=[g.pk for g in G.values()]).update(est_active=False)
        PubPoufiret.objects.filter(pk__in=[m.pk for m in M]).update(est_active=True)

        print('=== 5. PLACEMENT ===')
        d = carrousel(0)
        ok('k = 0 : seulement les pubs maison (les 3), dans l ordre', types(d) == 'MMM'
           and maisons(d) == [str(m.id) for m in M] and d['publicites'] == [], (types(d), maisons(d)))
        e = d['elements'][0]
        ok('element maison : champs, duree, categorie identique a une tuile', set(e) == CHAMPS_MAISON
           and e['duree_affichage_secondes'] == 5 and e['categorie']['slug'] == cat_ok.slug
           and {'mode_transaction', 'module_flutter', 'affiche_catalogue', 'affichage_enfants', 'enfants',
                'nb_enfants', 'est_active'} <= set(e['categorie']), e)
        d = carrousel(2)
        ok('k = 2 < N : P P M', types(d) == 'PPM', types(d))
        d = carrousel(3)
        ok('k = N = 3 : P P P M', types(d) == 'PPPM', types(d))
        d = carrousel(7)
        ok('k = 2N+1 = 7 : PPPMPPPMP', types(d) == 'PPPMPPPMP', types(d))
        ok('aucun doublon', len(maisons(d)) == len(set(maisons(d))) == 2)
        ok('publicites : strictement les pubs partenaires (memes champs, meme ordre)',
           [x['id'] for x in d['publicites']] == [str(p.id) for p in partenaires[:7]]
           and all(set(x) == set(PubliciteListSerializer.Meta.fields) for x in d['publicites']), d['publicites'][:1])
        ok('elements partenaires = publicites + type', [
            {k: v for k, v in x.items() if k != 'type'} for x in d['elements'] if x['type'] == 'partenaire']
           == d['publicites'])
        ParametresPoufiret.objects.filter(pk=params.pk).update(frequence_pub_maison=1)
        d = carrousel(7)
        ok('N = 1, 7 partenaires, 3 pubs maison : PMPMPMPPPP (sans doublon)', types(d) == 'PMPMPMPPPP'
           and len(set(maisons(d))) == 3, types(d))
        ParametresPoufiret.objects.filter(pk=params.pk).update(frequence_pub_maison=3)

        print('=== 6. FLAG ET REGLAGE ===')
        d = carrousel(7, flag=False)
        ok('flag publicite_active eteint : publicites vide, elements = pubs maison seules',
           d['publicites'] == [] and types(d) == 'MMM', (d['publicites'], types(d)))
        ParametresPoufiret.objects.filter(pk=params.pk).update(pubs_maison_actives=False)
        d = carrousel(7)
        ok('pubs_maison_actives eteint : elements = pubs partenaires seules', types(d) == 'PPPPPPP'
           and len(d['publicites']) == 7, types(d))
        d = carrousel(0, flag=False)
        ok('tout eteint : publicites et elements vides', d == {'publicites': [], 'elements': []}, d)
        ParametresPoufiret.objects.filter(pk=params.pk).update(pubs_maison_actives=True)

        print('=== 7. IMPRESSIONS, CLICS, ROTATION ===')
        imp = '/api/v1/publicites/poufiret/{}/impression/'
        avant_partenaires = ImpressionPublicite.objects.count()
        r = c.post(imp.format(M[0].id), {'type_affichage': 'carrousel'}, **entetes())
        ok('affichage anonyme -> 201', r.status_code == 201, details(r))
        d = carrousel(0)
        ok('rotation (anonyme) : la plus affichee aujourd hui passe en dernier', maisons(d) == [
            str(M[1].id), str(M[2].id), str(M[0].id)], maisons(d))
        ok('rotation (connecte) : ses propres affichages seulement -> ordre reglé',
           maisons(carrousel(0, client_dep1)) == [str(m.id) for m in M])
        r = c.post(imp.format(M[1].id), {'type_affichage': 'carrousel'}, **entetes(client_dep1))
        ok('affichage connecte -> 201', r.status_code == 201)
        ok('rotation (connecte) : M1 vu par lui -> en dernier', maisons(carrousel(0, client_dep1)) == [
            str(M[0].id), str(M[2].id), str(M[1].id)])
        c.post(imp.format(M[1].id), {'type_affichage': 'bandeau_bas'}, **entetes(client_dep1))
        r = c.post(imp.format(M[1].id), {'type_affichage': 'carrousel', 'cliquee': True}, **entetes(client_dep1))
        ok('clic -> 201', r.status_code == 201)
        c.post(imp.format(M[1].id), {'type_affichage': 'carrousel'}, **entetes(client_sans_dep))
        m1 = PubPoufiret.objects.get(pk=M[1].pk)
        ok('compteurs : 4 affichages (clic compris), 1 clic, 2 personnes (une seule fois chacune)', (
            m1.nb_impressions, m1.nb_clics, m1.nb_personnes_touchees) == (4, 1, 2),
           (m1.nb_impressions, m1.nb_clics, m1.nb_personnes_touchees))
        m0 = PubPoufiret.objects.get(pk=M[0].pk)
        ok('anonyme : affichage compte, aucune personne touchee', (m0.nb_impressions, m0.nb_personnes_touchees) == (1, 0))
        ok('emplacement inconnu -> 400', c.post(imp.format(M[0].id), {'type_affichage': 'pop'},
                                              **entetes()).status_code == 400)
        ok('pub inconnue -> 404', c.post(imp.format(uuid.uuid4()), {}, **entetes()).status_code == 404)
        ok('impressions des pubs partenaires non touchees', ImpressionPublicite.objects.count() == avant_partenaires)

        print('=== 8. STATS ET EXPORT ===')
        r = c.get(A + f'pubs/{M[1].id}/stats/', **entetes(admin_avec))
        s = r.json()
        ok('stats d une pub', r.status_code == 200 and (
            s['nb_impressions'], s['nb_clics'], s['taux_clic'], s['nb_personnes_touchees'], s['impressions_par_type'])
           == (4, 1, 25.0, 2, {'carrousel': 3, 'bandeau_bas': 1}), s)
        lignes = {x['id']: x for x in c.get(A + 'pubs/', {'page_size': 100}, **entetes(admin_avec)).json()['results']}
        x = lignes[str(M[1].id)]
        ok('liste admin : memes stats', (x['nb_impressions'], x['nb_clics'], x['taux_clic'], x['nb_personnes_touchees'],
                                         x['impressions_par_type']) == (4, 1, 25.0, 2, {'carrousel': 3, 'bandeau_bas': 1}), x)
        aujourdhui = str(timezone.localdate())
        r = c.get(A + 'stats/', {'du': aujourdhui, 'au': aujourdhui}, **entetes(admin_avec))
        par_pub = {x['id']: x for x in r.json()['par_pub']}
        ok('stats periode : ligne de la pub', r.status_code == 200 and (
            par_pub[str(M[1].id)]['nb_impressions'], par_pub[str(M[1].id)]['nb_clics'],
            par_pub[str(M[1].id)]['nb_personnes_touchees']) == (4, 1, 2), r.json())
        ok('stats periode : champs globaux', {'nb_impressions', 'nb_clics', 'taux_clic', 'nb_personnes_touchees',
                                              'impressions_par_type', 'par_pub'} <= set(r.json()))
        ok('stats : date invalide -> 400', c.get(A + 'stats/', {'du': '16/11/2026'},
                                                 **entetes(admin_avec)).status_code == 400)
        r = c.get(A + 'pubs/', {'export': 'csv'}, **entetes(admin_avec))
        contenu = r.content.decode('utf-8')
        ok('export CSV : fichier, BOM, en-tetes, ligne de la pub', r.status_code == 200
           and r['Content-Type'].startswith('text/csv') and 'poufiret_pubs_poufiret_' in r['Content-Disposition']
           and contenu.startswith('﻿id;titre;categorie;') and f'M1 {uid}' in contenu, contenu[:200])
        ok('export CSV : admin sans la capacite -> 403',
           c.get(A + 'pubs/', {'export': 'csv'}, **entetes(admin_sans)).status_code == 403)

        print('=== 9. PARCOURS ===')
        v0 = ParametresPoufiret.obtenir().version_parcours

        def ecran(user=admin_avec, **champs):
            donnees = {'titre': f'Ecran {uid}', 'image': image('e.png'), **champs}
            return c.post(A + 'ecrans/', donnees, **entetes(user))

        r = ecran(bouton_libelle='Voir')
        ok('ecran : libelle sans categorie -> 400', r.status_code == 400, details(r))
        r = ecran(bouton_libelle='Voir', bouton_categorie=cat_off.id)
        ok('ecran : categorie desactivee -> 400', r.status_code == 400 and 'désactivée' in details(r), details(r))
        ok('ecran : sans image -> 400', c.post(A + 'ecrans/', {'titre': 'x'}, **entetes(admin_avec)).status_code == 400)
        r1 = ecran(titre=f'E1 {uid}', ordre=0, texte='Bienvenue')
        r2 = ecran(titre=f'E2 {uid}', ordre=1, bouton_libelle='Voir la mode', bouton_categorie=cat_ok.id)
        ok('2 ecrans crees (201), actifs par defaut (multipart sans est_actif)',
           r1.status_code == r2.status_code == 201 and r1.json()['est_actif'] is True
           and r2.json()['est_actif'] is True, details(r2))
        r = c.post(A + 'parcours/publier/', **entetes(admin_avec))
        ok('publier avec 2 ecrans -> 400, message clair', r.status_code == 400
           and 'entre 3 et 8' in r.json()['message'], details(r))
        r = c.patch(A + 'reglages/', json.dumps({'parcours_actif': True}), content_type='application/json',
                    **entetes(admin_avec))
        ok('activer le parcours avec 2 ecrans -> 400', r.status_code == 400, details(r))
        r3 = ecran(titre=f'E3 {uid}', ordre=2, bouton_libelle='Coiffure', bouton_categorie=cat_enfant.id)
        r = c.post(A + 'parcours/publier/', **entetes(admin_avec))
        ok('publier avec 3 ecrans -> 200, version + 1', r.status_code == 200
           and r.json().get('version_parcours') == v0 + 1 and r.json().get('nb_ecrans') == 3, details(r))
        r = c.post(A + 'parcours/publier/', **entetes(admin_avec))
        ok('republier -> version + 2', r.json().get('version_parcours') == v0 + 2 and JournalModeration.objects.filter(
            action='poufiret_parcours', acteur=admin_avec).exists())
        d = c.get(DECOUVRIR, **entetes()).json()
        ok('decouvrir inactif : {actif false, version, ecrans []}', d == {'actif': False, 'version': v0 + 2, 'ecrans': []}, d)
        r = c.patch(A + 'reglages/', json.dumps({'parcours_actif': True, 'version_parcours': 999}),
                    content_type='application/json', **entetes(admin_avec))
        ok('activer avec 3 ecrans -> 200 ; version_parcours en lecture seule', r.status_code == 200
           and r.json()['parcours_actif'] is True and r.json()['version_parcours'] == v0 + 2, details(r))
        d = c.get(DECOUVRIR, **entetes()).json()
        ok('decouvrir actif : version, 3 ecrans dans l ordre', d['actif'] is True and d['version'] == v0 + 2
           and [e['titre'] for e in d['ecrans']] == [f'E1 {uid}', f'E2 {uid}', f'E3 {uid}'], d)
        e1, e2 = d['ecrans'][0], d['ecrans'][1]
        ok('ecran sans bouton -> bouton null ; image absolue', e1['bouton'] is None and e1['image'].startswith('http'), e1)
        ok('ecran avec bouton : libelle + categorie (objet tuile)', e2['bouton'] and e2['bouton']['libelle'] == 'Voir la mode'
           and e2['bouton']['categorie']['slug'] == cat_ok.slug, e2)
        Categorie.objects.filter(pk=cat_parente.pk).update(est_active=False)
        d = c.get(DECOUVRIR, **entetes()).json()
        ok('categorie du bouton devenue indisponible -> bouton null, ecran garde', len(d['ecrans']) == 3
           and d['ecrans'][2]['bouton'] is None, d['ecrans'][2])
        lignes = c.get(A + 'ecrans/', **entetes(admin_avec)).json()['ecrans']
        ok('admin : bouton_categorie_disponible false', next(
            x for x in lignes if x['titre'] == f'E3 {uid}')['bouton_categorie_disponible'] is False)
        Categorie.objects.filter(pk=cat_parente.pk).update(est_active=True)
        ids = [r3.json()['id'], r2.json()['id'], r1.json()['id']]
        r = c.post(A + 'ecrans/ordre/', json.dumps({'ids': ids}), content_type='application/json', **entetes(admin_avec))
        ok('ecrans : reordonnancement', r.status_code == 200 and [e['id'] for e in c.get(
            DECOUVRIR, **entetes()).json()['ecrans']] == ids, details(r))
        for i in range(6):
            ecran(titre=f'E+{i} {uid}', ordre=10 + i)
        r = c.post(A + 'parcours/publier/', **entetes(admin_avec))
        ok('publier avec 9 ecrans -> 400', r.status_code == 400 and '(actuellement 9)' in r.json()['message'], details(r))
        dernier = EcranDecouverte.objects.get(titre=f'E+5 {uid}')
        r = c.patch(A + f'ecrans/{dernier.id}/', json.dumps({'est_actif': False}), content_type='application/json',
                    **entetes(admin_avec))
        ok('desactiver un ecran -> 8 actifs, publier -> 200 (version + 3)', r.status_code == 200 and c.post(
            A + 'parcours/publier/', **entetes(admin_avec)).json().get('version_parcours') == v0 + 3)
        ok('DELETE ecran -> 204', c.delete(A + f'ecrans/{dernier.id}/', **entetes(admin_avec)).status_code == 204)

        print('=== 10. REGLAGES ===')
        r = c.get(A + 'reglages/', **entetes(admin_avec))
        ok('GET reglages : champs', set(r.json()) == {'pubs_maison_actives', 'frequence_pub_maison',
                                                      'duree_affichage_secondes', 'parcours_actif',
                                                      'version_parcours', 'modifie_le'}, r.json())
        r = c.patch(A + 'reglages/', json.dumps({'frequence_pub_maison': 0}), content_type='application/json',
                    **entetes(admin_avec))
        ok('frequence 0 -> 400', r.status_code == 400, details(r))
        r = c.patch(A + 'reglages/', json.dumps({'frequence_pub_maison': 2, 'duree_affichage_secondes': 8}),
                    content_type='application/json', **entetes(admin_avec))
        ok('PATCH frequence + duree -> 200 + journal', r.status_code == 200 and r.json()['frequence_pub_maison'] == 2
           and JournalModeration.objects.filter(action='poufiret_reglages', acteur=admin_avec).exists(), details(r))
        d = carrousel(4)
        ok('nouvelle frequence appliquee (N = 2, k = 4 : PPMPPM) et nouvelle duree', types(d) == 'PPMPPM'
           and all(e['duree_affichage_secondes'] == 8 for e in d['elements'] if e['type'] == 'poufiret'), types(d))

        raise Rollback()
except Rollback:
    print('\nRollback effectue (rien persiste).')
finally:
    shutil.rmtree(dossier_media, ignore_errors=True)

print(f'\n=== TOTAL : {NB_OK} OK / {len(KO)} KO ===')
if KO:
    print('KO :', *KO, sep='\n - ')
    raise SystemExit(1)
