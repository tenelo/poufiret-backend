"""Tests : recherche (?q=) et pagination optionnelle (?page=) de
GET /api/v1/catalogue/categories/<slug>/partenaires/.

- sans ?page= : liste simple, clés inchangées, ordre faveur > nom > id ;
- avec ?page= : {count, next, previous, results}, 20 par défaut,
  ?page_size= plafonné à 50, pages concaténées = liste simple (même ordre) ;
- ?q= : début de mot, sans casse ni accents (nom, secteur, quartier,
  description), q vide = pas de filtre, milieu de mot non trouvé ;
- q combiné avec sous_categorie et avec page ; partenaire invisible exclu ;
- couverture propre à la catégorie toujours appliquée dans les deux modes.

Données propres (catégories et partenaires créés ici), transaction
annulée, limitation de débit désactivée. Total OK / KO.
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_partenaires_categorie_recherche.py
"""
import sys
import traceback
import uuid
from urllib.parse import urlencode

from django.db import transaction
from django.test import Client

from apps.catalog.models import Categorie, PartenaireCategorie
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
# Limitation de débit DRF désactivée pour ce script : sinon tous les scripts partagent
# le compteur anonyme (60/min, client de test = 127.0.0.1) et la suite complète reçoit des 429.
from unittest import mock as _mock_debit
from rest_framework.views import APIView as _APIViewDebit
_mock_debit.patch.object(_APIViewDebit, 'get_throttles', return_value=[]).start()

CLES_PARTENAIRE = {
    'id', 'nom_commerce', 'description', 'logo', 'photo_couverture', 'departement', 'region',
    'latitude', 'longitude', 'adresse', 'quartier', 'localite_nom', 'quartier_nom', 'secteur',
    'gabarit', 'note_moyenne', 'nb_avis', 'whatsapp_externe',
}


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
        print('FAIL', libelle, str(detail)[:400])


def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel


def utilisateur(role='partenaire'):
    return User.objects.create(telephone=telephone_libre(), username=f't_pcr_{uuid.uuid4().hex[:8]}',
                               role=role, est_verifie=True)


try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')

        def categorie(nom, parent=None):
            return Categorie.objects.create(nom=f'{nom} {uid}', slug=f'pcr-{nom.lower()}-{uid}',
                                            parent=parent, icone='icone')

        racine = categorie('Elevage')
        porcs = categorie('Porcs', racine)
        volailles = categorie('Volailles', racine)

        def partenaire(nom, cat, **kw):
            kw.setdefault('statut', 'actif')
            kw.setdefault('est_visible', True)
            p = ProfilPartenaire.objects.create(user=utilisateur(), plan=plan, nom_commerce=nom,
                                                type_partenaire='commercant', **kw)
            PartenaireCategorie.objects.get_or_create(partenaire=p, categorie=cat,
                                                      defaults={'est_principale': False})
            return p

        alfred = partenaire(f"Ferme d'Alfred {uid}", porcs)
        bado = partenaire(f'Ferme de Bado {uid}', volailles, est_faveur=True)
        yao = partenaire(f'Boucherie Yao {uid}', porcs, description='Viande de ferme, livraison rapide.')
        koko = partenaire(f'Porcherie Zran {uid}', porcs, secteur='Koko')
        plateau = partenaire(f'Poulailler Nord {uid}', volailles, quartier='Résidence Plateau')
        invisible = partenaire(f'Ferme cachée {uid}', porcs, est_visible=False)
        # 50 partenaires de remplissage, dont des homonymes (départage par id).
        remplissage = [partenaire(f'Zz Partenaire {i // 2:02d} {uid}', porcs) for i in range(50)]
        PartenaireCategorie.objects.filter(partenaire=alfred, categorie=porcs).update(
            image_couverture='qa/couverture_alfred.jpg')

        visibles = [alfred, bado, yao, koko, plateau] + remplissage
        attendu = list(ProfilPartenaire.objects.filter(id__in=[p.id for p in visibles])
                       .order_by('-est_faveur', 'nom_commerce', 'id').values_list('id', flat=True))

        def get(slug, **params):
            url = f'/api/v1/catalogue/categories/{slug}/partenaires/'
            if params:
                url += '?' + urlencode(params)
            return Client().get(url, secure=True, HTTP_HOST=HOST)

        def ids(r):
            d = r.json()
            return [x['id'] for x in (d['results'] if isinstance(d, dict) else d)]

        print('=== 1. SANS ?page= : LISTE SIMPLE (INCHANGEE) ===')
        r = get(racine.slug)
        d = r.json()
        ok('200 + liste simple (pas d enveloppe)', r.status_code == 200 and isinstance(d, list), type(d))
        ok('tous les visibles (55), invisible exclu', len(d) == 55 and invisible.id not in ids(r), len(d))
        ok('ordre : faveur, nom, id (homonymes departages par id)', ids(r) == attendu)
        ok('cles d un partenaire inchangees', d and CLES_PARTENAIRE <= set(d[0]), set(d[0]) if d else None)
        ok('couverture propre a la categorie appliquee',
           next(x for x in d if x['id'] == alfred.id)['photo_couverture'].endswith('qa/couverture_alfred.jpg'))
        ok('?q= vide : pas de filtre', ids(get(racine.slug, q='')) == attendu)

        print('=== 2. AVEC ?page= : FORMAT PAGINE ===')
        r = get(racine.slug, page=1)
        d = r.json()
        ok('enveloppe {count, next, previous, results}', r.status_code == 200 and isinstance(d, dict)
           and set(d) == {'count', 'next', 'previous', 'results'}, d if not isinstance(d, dict) else set(d))
        ok('count 55, 20 par defaut, previous null, next page=2', d.get('count') == 55
           and len(d.get('results', [])) == 20 and d.get('previous') is None and 'page=2' in (d.get('next') or ''), d)
        ok('cles des resultats identiques au mode liste', set(d['results'][0]) == set(get(racine.slug).json()[0]))
        pages = []
        for n in (1, 2, 3):
            pages += ids(get(racine.slug, page=n))
        ok('pages 1..3 concatenees = liste simple (meme ordre)', pages == attendu, (len(pages), len(attendu)))
        d3 = get(racine.slug, page=3).json()
        ok('page 3 : 15 resultats, next null', len(d3['results']) == 15 and d3['next'] is None, d3.get('next'))
        ok('page_size=100 plafonne a 50', len(get(racine.slug, page=1, page_size=100).json()['results']) == 50)
        ok('page_size=5', len(get(racine.slug, page=1, page_size=5).json()['results']) == 5)
        ok('page hors limites -> 404', get(racine.slug, page=99).status_code == 404)
        d = get(racine.slug, page=1, q='alfred').json()
        ok('couverture appliquee aussi en mode pagine',
           d['results'] and d['results'][0]['photo_couverture'].endswith('qa/couverture_alfred.jpg'), d)

        print('=== 3. ?q= : DEBUT DE MOT, SANS CASSE NI ACCENTS ===')
        ok('« ferme » : nom (2) + description (Yao), invisible exclu',
           set(ids(get(racine.slug, q='ferme'))) == {alfred.id, bado.id, yao.id})
        ok('« FERMÉ » (majuscules + accent) : meme resultat',
           set(ids(get(racine.slug, q='FERMÉ'))) == {alfred.id, bado.id, yao.id})
        ok('« bado » trouve « Ferme de Bado »', ids(get(racine.slug, q='bado')) == [bado.id])
        ok('« alfred » trouve « Ferme d Alfred »', ids(get(racine.slug, q='Alfred')) == [alfred.id])
        ok('secteur : « koko »', ids(get(racine.slug, q='koko')) == [koko.id])
        ok('quartier sans accent : « residence » trouve « Résidence Plateau »',
           ids(get(racine.slug, q='residence')) == [plateau.id])
        ok('milieu de mot non trouve (« erme »)', ids(get(racine.slug, q='erme')) == [])
        ok('ordre conserve avec q (faveur Bado en tete)', ids(get(racine.slug, q='ferme'))[0] == bado.id)

        print('=== 4. COMBINAISONS ===')
        ok('q + sous_categorie Porcs', set(ids(get(racine.slug, q='ferme', sous_categorie=porcs.slug)))
           == {alfred.id, yao.id})
        ok('q + sous_categorie Volailles (id)', ids(get(racine.slug, q='ferme', sous_categorie=volailles.id))
           == [bado.id])
        d = get(racine.slug, q='ferme', page=1).json()
        ok('q + page : count 3', d.get('count') == 3 and len(d['results']) == 3, d)
        d = get(racine.slug, q='zz', sous_categorie=porcs.slug, page=2, page_size=20).json()
        ok('q + sous_categorie + page : count 50, page 2 = 20', d.get('count') == 50 and len(d['results']) == 20, d)
        ok('sous_categorie hors branche -> 404 (inchange)',
           get(racine.slug, q='ferme', sous_categorie=f'zzz-{uid}').status_code == 404)
        ok('type_etablissement inconnu -> 400 (inchange)',
           get(racine.slug, page=1, type_etablissement='inconnu').status_code == 400)
        ok('?localites=all + q', set(ids(get(racine.slug, q='ferme', localites='all')))
           == {alfred.id, bado.id, yao.id})

        raise Rollback()
except Rollback:
    print('\nRollback effectue (rien persiste).')
except Exception:
    traceback.print_exc(file=sys.stdout)
    KO.append('exception inattendue (trace ci-dessus)')

print(f'\n=== TOTAL : {NB_OK} OK / {len(KO)} KO ===')
if KO:
    print('KO :', *KO, sep='\n - ')
    raise SystemExit(1)
