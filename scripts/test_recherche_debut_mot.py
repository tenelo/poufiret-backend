"""Tests : la recherche (/catalogue/recherche/, mots-clés des catégories,
testeur admin) fait correspondre en DÉBUT DE MOT, sans tenir compte des
minuscules / accents : « oeuf » ne trouve plus « boeuf », « pou » trouve
toujours « poulet ».

Données propres, rollback, limitation de débit désactivée, total OK / KO.
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_recherche_debut_mot.py
"""
import uuid
from urllib.parse import quote

from django.db import transaction
from django.test import Client

from apps.catalog.models import Article, Categorie, PartenaireCategorie
from apps.catalog.recherche import motif_debut_de_mot
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


def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel


try:
    with transaction.atomic():
        u = uuid.uuid4().hex[:6]
        # Jeton propre au test, pour ne regarder que nos données : chaque nom
        # / mot-clé est « <mot> <jeton> » et on cherche « <mot> » en filtrant nos ids.
        plan = PlanAbonnement.objects.get(libelle='Basique')
        betail = Categorie.objects.create(nom=f'Bétail QA{u}', slug=f'betail-qa-{u}', mots_cles=['boeufs', 'moutons'])
        oeufs_cat = Categorie.objects.create(nom=f'Produits fermiers QA{u}', slug=f'fermiers-qa-{u}',
                                             mots_cles=['oeufs frais', 'plaquette'])
        volaille = Categorie.objects.create(nom=f'Volaille QA{u}', slug=f'volaille-qa-{u}',
                                            description='Élevage de poulets fermiers')
        p = ProfilPartenaire.objects.create(
            user=User.objects.create(telephone=telephone_libre(), username=f't_rdm_{u}', role='partenaire'),
            plan=plan, nom_commerce=f'Ferme du Bœuf QA{u}', type_partenaire='commercant', statut='actif',
            est_visible=True, description='Vente de cabris et de taurillons')
        PartenaireCategorie.objects.get_or_create(partenaire=p, categorie=volaille, defaults={'est_principale': True})
        art_boeuf = Article.objects.create(partenaire=p, categorie=volaille, nom=f'Bœuf entier QA{u}',
                                           slug=f'rdm-boeuf-{u}', type='produit', prix=1000, est_actif=True)
        art_poulet = Article.objects.create(partenaire=p, categorie=volaille, nom=f'Poulet braisé QA{u}',
                                            slug=f'rdm-poulet-{u}', type='produit', prix=1000, est_actif=True,
                                            description='Poulet de chair')
        nos_cats = {betail.id, oeufs_cat.id, volaille.id}

        def chercher(terme):
            d = Client().get(f'/api/v1/catalogue/recherche/?q={quote(terme)}', secure=True, HTTP_HOST=HOST).json()
            return ({c['id'] for c in d['categories']} & nos_cats,
                    {x['id'] for x in d['partenaires']} & {p.id},
                    {a['id'] for a in d['articles']} & {art_boeuf.id, art_poulet.id})

        print('=== MOTIF ===')
        ok('motif : \\m + terme echappe', motif_debut_de_mot('c++ x') == r'\mc\+\+\ x', motif_debut_de_mot('c++ x'))

        print('=== PLUS DE CORRESPONDANCE AU MILIEU D UN MOT ===')
        cats, parts, arts = chercher('oeufs')
        ok('« oeufs » : pas Betail (mot-cle « boeufs »), mais Produits fermiers (« oeufs frais »)',
           cats == {oeufs_cat.id}, cats)
        cats, parts, arts = chercher('oeuf')
        ok('« oeuf » : ni l article « Bœuf entier » ni la ferme « du Bœuf »', not arts and not parts, (parts, arts))
        ok('« oeuf » : categorie oeufs seulement', cats == {oeufs_cat.id}, cats)
        cats, parts, arts = chercher('quette')
        ok('« quette » : pas « plaquette » (fin d un mot-cle)', not cats, cats)
        cats, parts, arts = chercher('rillons')
        ok('« rillons » : pas « taurillons » (description partenaire)', not parts, parts)

        print('=== DEBUT DE MOT TOUJOURS TROUVE ===')
        cats, parts, arts = chercher('pou')
        ok('« pou » : article Poulet braise', arts == {art_poulet.id}, arts)
        ok('« pou » : categorie Volaille (description « poulets »)', volaille.id in cats, cats)
        cats, parts, arts = chercher('boeuf')
        ok('« boeuf » : Betail (mot-cle) + article + ferme (œ -> oe)', betail.id in cats
           and art_boeuf.id in arts and parts == {p.id}, (cats, parts, arts))
        cats, parts, arts = chercher('BŒUF')
        ok('majuscules / ligature : « BŒUF » = « boeuf »', art_boeuf.id in arts, arts)
        cats, parts, arts = chercher('elevage')
        ok('accents : « elevage » trouve « Élevage »', volaille.id in cats, cats)
        cats, parts, arts = chercher('betail')
        ok('accents : « betail » trouve « Bétail »', betail.id in cats, cats)
        cats, parts, arts = chercher('poulet bra')
        ok('plusieurs mots : « poulet bra »', arts == {art_poulet.id}, arts)
        cats, parts, arts = chercher('cabri')
        ok('description partenaire, debut de mot : « cabri »', parts == {p.id}, parts)
        cats, parts, arts = chercher('mout')
        ok('mot-cle en 2e position : « mout » -> Betail', betail.id in cats, cats)
        cats, parts, arts = chercher('fra')
        ok('2e mot d un mot-cle : « fra » -> « oeufs frais »', oeufs_cat.id in cats, cats)
        r = Client().get('/api/v1/catalogue/recherche/?q=' + quote('(x'), secure=True, HTTP_HOST=HOST)
        ok('caractere special de regex : 200, pas d erreur', r.status_code == 200, r.status_code)

        raise Rollback()
except Rollback:
    print('\nRollback effectue (rien persiste).')

print(f'\n=== TOTAL : {NB_OK} OK / {len(KO)} KO ===')
if KO:
    print('KO :', *KO, sep='\n - ')
    raise SystemExit(1)
