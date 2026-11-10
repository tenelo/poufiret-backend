"""Tests : sous-catégories (affichage pastilles | grille) et annuaire agrégé.

- Categorie.affichage_enfants : défaut « pastilles » ; exposé en public.
- Lecture publique : enfants actifs et non archivés (id, nom, slug, icone,
  image, nb_partenaires, nb_enfants), triés par ordre ; enfant masqué exclu ;
  grille d'accueil = racines seulement.
- Annuaire d'une parente : parente + toutes ses sous-catégories (récursif sur
  3 niveaux, sans doublon) ; ?sous_categorie=<id|slug> : cette branche
  seulement ; sous-catégorie étrangère / masquée → 404 ; visibilité inchangée.
- Admin : affichage_enfants en création et édition, valeur invalide → 400.

Données propres, rollback, limitation de débit désactivée, total OK / KO.
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_sous_categories.py
"""
import json, uuid

from django.db import transaction
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken

from apps.catalog.models import Article, Categorie, PartenaireCategorie
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
    if corps is None:
        return getattr(Client(), method)(url, **kw)
    return getattr(Client(), method)(url, json.dumps(corps), content_type='application/json', **kw)


def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel


def utilisateur(role='client', **kw):
    return User.objects.create(telephone=telephone_libre(), username=f't_scat_{uuid.uuid4().hex[:8]}',
                               role=role, est_verifie=True, **kw)


try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')

        def categorie(nom, parent=None, ordre=0, **kw):
            return Categorie.objects.create(nom=f'{nom} {uid}', slug=f'scat-{nom.lower()}-{uid}', parent=parent,
                                            ordre=ordre, icone='icone', **kw)

        # Arbre : Betail > Volailles (ordre 2) > Poulets (3e niveau) ; Betail > Porcs (ordre 1) ;
        # Betail > Masquee (inactive) ; Betail > Archivee.
        betail = categorie('Betail', ordre=-100000)
        volailles = categorie('Volailles', betail, ordre=2)
        poulets = categorie('Poulets', volailles, ordre=1)
        porcs = categorie('Porcs', betail, ordre=1)
        masquee = categorie('Masquee', betail, ordre=3, est_active=False)
        archivee = categorie('Archivee', betail, ordre=4, est_archivee=True)
        sous_masquee = categorie('SousMasquee', masquee)
        autre = categorie('Autre', ordre=-99999)

        def partenaire(nom, *cats, statut='actif', est_visible=True, via_article=False):
            p = ProfilPartenaire.objects.create(user=utilisateur('partenaire'), plan=plan,
                                                nom_commerce=f'{nom} {uid}', type_partenaire='commercant',
                                                statut=statut, est_visible=est_visible)
            for c in cats:
                if via_article:
                    Article.objects.create(partenaire=p, categorie=c, nom=f'Art {nom}', slug=f'scat-{uuid.uuid4().hex[:10]}',
                                           type='produit', prix=1000, est_actif=True)
                else:
                    PartenaireCategorie.objects.get_or_create(partenaire=p, categorie=c,
                                                              defaults={'est_principale': True})
            return p

        p_betail = partenaire('Ferme generale', betail)
        p_porcs = partenaire('Porcherie', porcs)
        p_volailles = partenaire('Volailler', volailles, via_article=True)
        p_poulets = partenaire('Poulailler', poulets)
        p_double = partenaire('Double', porcs, poulets)          # deux branches : une seule fois
        p_masquee = partenaire('Cache', masquee)                  # sous-catégorie masquée
        p_sous_masquee = partenaire('SousCache', sous_masquee)    # descendante d'une masquée
        p_archivee = partenaire('Archive', archivee)
        p_invisible = partenaire('Invisible', porcs, est_visible=False)
        p_autre = partenaire('Ailleurs', autre)
        superadmin = utilisateur('admin', is_staff=True, is_superuser=True)

        print('=== 1. DEFAUT ET EXPOSITION ===')
        ok('defaut : pastilles', Categorie.objects.get(pk=betail.pk).affichage_enfants == 'pastilles')
        d = req('get', f'/api/v1/catalogue/categories/{betail.slug}/').json()
        ok('detail : affichage_enfants pastilles', d.get('affichage_enfants') == 'pastilles', d.get('affichage_enfants'))
        ok('detail : nb_enfants = 2 (actifs, non archives)', d.get('nb_enfants') == 2, d.get('nb_enfants'))
        enfants = d['enfants']
        ok('enfants : Porcs puis Volailles (tri par ordre), masquee/archivee exclues',
           [e['id'] for e in enfants] == [porcs.id, volailles.id], [e['nom'] for e in enfants])
        ok('enfant : id, nom, slug, icone, image, nb_partenaires, nb_enfants', all(
            {'id', 'nom', 'slug', 'icone', 'image', 'nb_partenaires', 'nb_enfants', 'affichage_enfants'} <= set(e)
            for e in enfants), set(enfants[0]))
        e_vol = enfants[1]
        ok('Volailles : nb_enfants 1, petit-enfant Poulets expose', e_vol['nb_enfants'] == 1
           and [x['id'] for x in e_vol['enfants']] == [poulets.id], e_vol)
        e_porcs = enfants[0]
        ok('Porcs : nb_partenaires 2 (invisible exclu), nb_enfants 0',
           e_porcs['nb_partenaires'] == 2 and e_porcs['nb_enfants'] == 0, e_porcs)
        grille = req('get', '/api/v1/catalogue/categories/?page_size=200').json()
        grille = grille.get('results', grille)
        ids_grille = {c['id'] for c in grille}
        ok('grille d accueil : racines seulement', betail.id in ids_grille and autre.id in ids_grille
           and not ({volailles.id, porcs.id, poulets.id} & ids_grille))
        ok('grille : affichage_enfants expose', next(c for c in grille if c['id'] == betail.id)['affichage_enfants']
           == 'pastilles')

        print('=== 2. ANNUAIRE AGREGE ===')
        AN = f'/api/v1/catalogue/categories/{betail.slug}/partenaires/'
        r = req('get', AN)
        ids = [x['id'] for x in r.json()]
        ok('parente : elle + toutes ses sous-categories (3 niveaux)', set(ids) == {
            p_betail.id, p_porcs.id, p_volailles.id, p_poulets.id, p_double.id}, set(ids))
        ok('sans doublon', len(ids) == len(set(ids)), ids)
        ok('masquee, descendante de masquee, archivee, invisible, autre racine : exclus', not (set(ids) & {
            p_masquee.id, p_sous_masquee.id, p_archivee.id, p_invisible.id, p_autre.id}))

        print('=== 3. FILTRE ?sous_categorie= ===')
        ids = {x['id'] for x in req('get', f'{AN}?sous_categorie={volailles.id}').json()}
        ok('?sous_categorie=<id> Volailles : Volailles + Poulets', ids == {p_volailles.id, p_poulets.id, p_double.id}, ids)
        ids = {x['id'] for x in req('get', f'{AN}?sous_categorie={porcs.slug}').json()}
        ok('?sous_categorie=<slug> Porcs', ids == {p_porcs.id, p_double.id}, ids)
        ids = {x['id'] for x in req('get', f'{AN}?sous_categorie={poulets.slug}').json()}
        ok('?sous_categorie= petit-enfant (3e niveau)', ids == {p_poulets.id, p_double.id}, ids)
        ok('sous-categorie masquee -> 404', req('get', f'{AN}?sous_categorie={masquee.id}').status_code == 404)
        ok('categorie hors branche -> 404', req('get', f'{AN}?sous_categorie={autre.slug}').status_code == 404)
        ok('la parente elle-meme -> 404', req('get', f'{AN}?sous_categorie={betail.id}').status_code == 404)
        ok('inconnue -> 404', req('get', f'{AN}?sous_categorie=zzz-{uid}').status_code == 404)
        ids = {x['id'] for x in req('get', f'/api/v1/catalogue/categories/{porcs.slug}/partenaires/').json()}
        ok('annuaire d une feuille inchange', ids == {p_porcs.id, p_double.id}, ids)

        print('=== 4. ADMIN ===')
        A = '/api/v1/administration/categories/'
        r = req('post', A, superadmin, {'nom': f'QA Grille {uid}', 'affichage_enfants': 'grille'})
        ok('creation avec affichage_enfants grille -> 201', r.status_code == 201
           and r.json()['affichage_enfants'] == 'grille', r.content[:300])
        r = req('post', A, superadmin, {'nom': f'QA Defaut {uid}'})
        ok('creation sans le champ -> pastilles', r.status_code == 201 and r.json()['affichage_enfants'] == 'pastilles',
           r.content[:300])
        r = req('patch', f'{A}{betail.id}/', superadmin, {'affichage_enfants': 'grille'})
        ok('edition -> grille', r.status_code == 200 and r.json()['affichage_enfants'] == 'grille', r.content[:300])
        ok('public reflete grille', req('get', f'/api/v1/catalogue/categories/{betail.slug}/').json()
           ['affichage_enfants'] == 'grille')
        ok('valeur invalide -> 400', req('patch', f'{A}{betail.id}/', superadmin,
                                         {'affichage_enfants': 'carrousel'}).status_code == 400)
        r = req('get', A, superadmin)
        ligne = next((x for x in r.json()['resultats'] if x['id'] == betail.id), {})
        ok('liste admin : affichage_enfants', ligne.get('affichage_enfants') == 'grille', ligne)

        raise Rollback()
except Rollback:
    print('\nRollback effectue (rien persiste).')

print(f'\n=== TOTAL : {NB_OK} OK / {len(KO)} KO ===')
if KO:
    print('KO :', *KO, sep='\n - ')
    raise SystemExit(1)
