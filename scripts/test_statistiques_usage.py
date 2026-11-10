"""Tests : statistiques d'usage admin (/administration/statistiques-usage/).

Jeu connu sur une période sans données réelles (mars 2001) et dans deux
départements créés pour le test : calculs exacts de recherches/, entonnoir/,
contacts-partenaires/, activite/, resume/ (+ période précédente), filtres de
période et de département, erreurs 400, permission voir_stats.

Données propres, rollback, limitation de débit désactivée, total OK / KO.
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_statistiques_usage.py
"""
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.test import Client
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import PermissionsAdmin
from apps.analytics.models import EvenementApp, RechercheLog, VueVitrine
from apps.catalog.models import Article, Categorie, VueArticle
from apps.geo.models import Departement, District, Region
from apps.orders.models import Commande, HistoriqueCommande
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


def req(url, user=None):
    kw = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    return Client().get(url, **kw)


def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel


def dt(jour, heure, mois=3):
    """Date-heure locale (Africa/Abidjan) en 2001."""
    return timezone.make_aware(datetime(2001, mois, jour, heure, 0), timezone.get_current_timezone())


def dater(obj, champ, quand):
    type(obj).objects.filter(pk=obj.pk).update(**{champ: quand})


try:
    with transaction.atomic():
        u = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        district = District.objects.create(nom=f'District QA stats {u}')
        region = Region.objects.create(nom=f'Region QA stats {u}', district=district)
        dep_a = Departement.objects.create(nom=f'Dep A stats {u}', region=region)
        dep_b = Departement.objects.create(nom=f'Dep B stats {u}', region=region)
        cat1 = Categorie.objects.create(nom=f'Cat1 stats {u}', slug=f'cat1-stats-{u}')
        cat2 = Categorie.objects.create(nom=f'Cat2 stats {u}', slug=f'cat2-stats-{u}')

        def utilisateur(role='client', dep=None, **kw):
            return User.objects.create(telephone=telephone_libre(), username=f't_stu_{uuid.uuid4().hex[:8]}',
                                       role=role, est_verifie=True, departement=dep, **kw)

        def partenaire(nom, dep):
            return ProfilPartenaire.objects.create(user=utilisateur('partenaire'), plan=plan, departement=dep,
                                                   nom_commerce=f'{nom} {u}', type_partenaire='commercant',
                                                   statut='actif', est_visible=True)

        pa1, pa2, pb = partenaire('A1 Ferme', dep_a), partenaire('A2 Marche', dep_a), partenaire('B1 Boutique', dep_b)
        ua = utilisateur(dep=dep_a, consentement_statistiques=True)
        ub = utilisateur(dep=dep_b, consentement_statistiques=True)

        # ── Recherches ───────────────────────────────────────────────
        def recherche(terme, user, quand, nb_resultats, clic=False):
            r = RechercheLog.objects.create(terme=terme, terme_normalise=terme, utilisateur=user, source='accueil',
                                            nb_resultats=nb_resultats, clique_le=quand if clic else None)
            dater(r, 'cree_le', quand)

        recherche('poulet', ua, dt(5, 10), 4, clic=True)
        recherche('poulet', ua, dt(6, 10), 4)
        recherche('poulet', ub, dt(6, 18), 4, clic=True)
        recherche('garba', ua, dt(7, 10), 0)
        recherche('garba', None, dt(7, 10), 0)
        recherche('poulet', ua, dt(1, 10), 4)            # période précédente
        recherche('poulet', ua, dt(20, 10), 4)           # hors période

        # ── Événements ───────────────────────────────────────────────
        def evt(type_, partenaire_, quand, user=None, cat=None, n=1):
            for _ in range(n):
                e = EvenementApp.objects.create(type=type_, utilisateur=user, partenaire=partenaire_, categorie=cat)
                dater(e, 'cree_le', quand)

        evt('panier_ajout', pa1, dt(5, 10), ua, cat1, n=2)   # 1 panier
        evt('panier_ajout', pa1, dt(6, 10), ua, cat1)        # autre jour : 2e panier
        evt('panier_ajout', pa2, dt(7, 10), None, cat2, n=2)  # anonymes : 2 paniers
        evt('panier_ajout', pb, dt(6, 10), ub, cat1)         # 1 panier (dep B)
        evt('appel_partenaire', pa1, dt(5, 10), ua, n=2)
        evt('whatsapp_partenaire', pa1, dt(8, 18), ua)
        evt('itineraire_partenaire', pa2, dt(8, 18), ua)
        evt('appel_partenaire', pb, dt(8, 10), ub)
        evt('appel_partenaire', pa1, dt(2, 10), ua)          # période précédente

        # ── Commandes ────────────────────────────────────────────────
        def commande(partenaire_, cat, statut, quand, total=1000, **kw):
            c = Commande.objects.create(numero=f'PFR-STU-{uuid.uuid4().hex[:10]}', user=ua, partenaire=partenaire_,
                                        categorie=cat, statut=statut, total=total, **kw)
            dater(c, 'created_at', quand)
            return c

        commande(pa1, cat1, 'livree', dt(5, 12), total=5000)
        c2 = commande(pa1, cat1, 'annulee', dt(6, 12))
        HistoriqueCommande.objects.create(commande=c2, statut='annulee', acteur=ua, acteur_role='client',
                                          commentaire='Trop long')
        c3 = commande(pa2, cat2, 'annulee', dt(7, 12))
        HistoriqueCommande.objects.create(commande=c3, statut='annulee', acteur=pa2.user, acteur_role='partenaire',
                                          commentaire='  trop LONG ')
        commande(pa2, cat2, 'refusee', dt(7, 13), raison_refus='Rupture')
        commande(pb, cat1, 'livree', dt(8, 18), total=3000)
        commande(pa1, cat1, 'livree', dt(2, 12), total=1000)  # période précédente

        # ── Vues ─────────────────────────────────────────────────────
        def vues(partenaire_, quand, n):
            for _ in range(n):
                dater(VueVitrine.objects.create(partenaire=partenaire_), 'cree_le', quand)

        vues(pa1, dt(5, 9), 3)
        vues(pa2, dt(6, 9), 1)
        vues(pb, dt(6, 9), 2)
        vues(pa1, dt(2, 9), 1)  # période précédente
        art = Article.objects.create(partenaire=pa1, categorie=cat1, nom='Art stats', slug=f'art-stats-{u}',
                                     type='produit', prix=1000, est_actif=True)
        for _ in range(2):
            dater(VueArticle.objects.create(article=art), 'date_vue', dt(5, 9))

        # ── Comptes admin ────────────────────────────────────────────
        superadmin = utilisateur('admin', is_staff=True, is_superuser=True)
        admin_stats = utilisateur('admin', is_staff=True)
        PermissionsAdmin.objects.create(admin=admin_stats, voir_stats=True)
        admin_sans = utilisateur('admin', is_staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans)

        B = '/api/v1/administration/statistiques-usage/'
        P = '?du=2001-03-05&au=2001-03-11'
        PA = P + f'&departement={dep_a.id}'

        def get(chemin, params=P, user=admin_stats):
            r = req(f'{B}{chemin}/{params}', user)
            return r.json() if r.status_code == 200 else {'_status': r.status_code, '_contenu': r.content[:300]}

        # ═══════════════════════════════════════════════════════════════
        print('=== PERMISSION ET PARAMETRES ===')
        for chemin in ('recherches', 'entonnoir', 'contacts-partenaires', 'activite', 'resume'):
            ok(f'{chemin} : anonyme 401, sans voir_stats 403, voir_stats 200, super-admin 200', (
                req(f'{B}{chemin}/{P}').status_code, req(f'{B}{chemin}/{P}', admin_sans).status_code,
                req(f'{B}{chemin}/{P}', admin_stats).status_code, req(f'{B}{chemin}/{P}', superadmin).status_code)
               == (401, 403, 200, 200))
        d = get('resume', '')
        aujourd_hui = timezone.localdate()
        ok('defaut : 30 derniers jours', d['periode'] == {'du': (aujourd_hui - timedelta(days=29)).isoformat(),
                                                           'au': aujourd_hui.isoformat(), 'nb_jours': 30,
                                                           'departement': None}, d['periode'])
        for params, raison in (('?du=2001-03-10&au=2001-03-01', 'du > au'), ('?du=2001-13-01', 'date invalide'),
                               ('?du=2000-01-01&au=2001-12-31', 'plus de 366 jours'),
                               ('?departement=abc', 'departement non numerique')):
            r = req(f'{B}resume/{params}', admin_stats)
            ok(f'{raison} -> 400', r.status_code == 400, r.content[:200])

        # ═══════════════════════════════════════════════════════════════
        print('=== 1. RECHERCHES ===')
        d = get('recherches')
        ok('periode exposee', d['periode'] == {'du': '2001-03-05', 'au': '2001-03-11', 'nb_jours': 7,
                                               'departement': None}, d['periode'])
        ok('totaux : 5 / 2 clics / 2 sans resultat / 2 termes', d['totaux'] == {
            'nb': 5, 'nb_avec_clic': 2, 'nb_sans_resultat': 2, 'nb_termes': 2, 'taux_clic': 0.4,
            'taux_sans_resultat': 0.4}, d['totaux'])
        ok('top termes exacts', d['top_termes'] == [
            {'terme_normalise': 'poulet', 'nb': 3, 'nb_avec_clic': 2, 'nb_sans_resultat': 0, 'taux_clic': 0.6667},
            {'terme_normalise': 'garba', 'nb': 2, 'nb_avec_clic': 0, 'nb_sans_resultat': 2, 'taux_clic': 0.0}],
           d['top_termes'])
        ok('top sans resultat', [(t['terme_normalise'], t['nb']) for t in d['top_sans_resultat']] == [('garba', 2)]
           and d['top_sans_resultat'][0]['derniere_recherche'], d['top_sans_resultat'])
        d = get('recherches', PA)
        ok('departement A (utilisateur) : poulet 2, garba 1 (anonyme exclu)', [
            (t['terme_normalise'], t['nb'], t['nb_avec_clic']) for t in d['top_termes']] == [
            ('poulet', 2, 1), ('garba', 1, 0)], d['top_termes'])
        d = get('recherches', '?du=2001-03-06&au=2001-03-06')
        ok('filtre de periode (06/03 seul) : 2 recherches', d['totaux']['nb'] == 2, d['totaux'])

        # ═══════════════════════════════════════════════════════════════
        print('=== 2. ENTONNOIR ===')
        d = get('entonnoir')
        cles = {k: d[k] for k in ('nb_ajouts_panier', 'nb_paniers_avec_ajout', 'nb_commandes', 'nb_livrees',
                                  'nb_annulees', 'nb_refusees', 'nb_expirees', 'montant_livre', 'taux_conversion',
                                  'taux_livraison', 'taux_annulation')}
        ok('chiffres globaux exacts', cles == {
            'nb_ajouts_panier': 6, 'nb_paniers_avec_ajout': 5, 'nb_commandes': 5, 'nb_livrees': 2, 'nb_annulees': 2,
            'nb_refusees': 1, 'nb_expirees': 0, 'montant_livre': 8000, 'taux_conversion': 1.0,
            'taux_livraison': 0.4, 'taux_annulation': 0.4}, cles)
        ok('motifs d annulation regroupes (minuscules, espaces)', d['annulations']['motifs'] == [
            {'motif': 'trop long', 'nb': 2}], d['annulations'])
        ok('annulations par acteur', sorted((x['acteur_role'], x['nb']) for x in d['annulations']['par_acteur'])
           == [('client', 1), ('partenaire', 1)], d['annulations']['par_acteur'])
        ok('motifs de refus', d['refus']['motifs'] == [{'motif': 'rupture', 'nb': 1}], d['refus'])
        pc = {x['categorie_id']: x for x in d['par_categorie']}
        ok('par categorie : cat1', {k: pc[cat1.id][k] for k in ('nb_ajouts_panier', 'nb_paniers', 'nb_commandes',
                                                                 'nb_livrees', 'nb_annulees', 'taux_conversion')}
           == {'nb_ajouts_panier': 4, 'nb_paniers': 3, 'nb_commandes': 3, 'nb_livrees': 2, 'nb_annulees': 1,
               'taux_conversion': 1.0}, pc.get(cat1.id))
        ok('par categorie : cat2', {k: pc[cat2.id][k] for k in ('nb_ajouts_panier', 'nb_paniers', 'nb_commandes',
                                                                 'nb_livrees', 'nb_annulees', 'taux_livraison')}
           == {'nb_ajouts_panier': 2, 'nb_paniers': 2, 'nb_commandes': 2, 'nb_livrees': 0, 'nb_annulees': 1,
               'taux_livraison': 0.0}, pc.get(cat2.id))
        ok('par categorie : nom', pc[cat1.id]['categorie_nom'] == cat1.nom)
        d = get('entonnoir', PA)
        ok('departement A (partenaire) : 5 ajouts, 4 paniers, 4 commandes, 1 livree, 5000',
           (d['nb_ajouts_panier'], d['nb_paniers_avec_ajout'], d['nb_commandes'], d['nb_livrees'], d['montant_livre'])
           == (5, 4, 4, 1, 5000), d)

        # ═══════════════════════════════════════════════════════════════
        print('=== 3. CONTACTS PARTENAIRES ===')
        CH = ('id', 'vues_vitrine', 'appels', 'whatsapp', 'itineraires', 'contacts', 'commandes',
              'taux_contact_commande', 'taux_vue_contact')
        d = get('contacts-partenaires', PA)
        lignes = [tuple(x[k] for k in CH) for x in d['resultats']]
        ok('dep A, tri -contacts : chiffres exacts', lignes == [
            (pa1.id, 3, 2, 1, 0, 3, 2, 0.6667, 1.0), (pa2.id, 1, 0, 0, 1, 1, 2, 2.0, 1.0)], lignes)
        ok('pagination : count 2, page 1', (d['count'], d['page'], d['page_size'], d['tri']) == (2, 1, 20, '-contacts'))
        d = get('contacts-partenaires', PA + '&tri=taux_contact_commande')
        ok('tri croissant taux_contact_commande', [x['id'] for x in d['resultats']] == [pa1.id, pa2.id])
        d = get('contacts-partenaires', PA + '&tri=-taux_contact_commande&page_size=1&page=2')
        ok('page_size=1 page=2', d['count'] == 2 and [x['id'] for x in d['resultats']] == [pa1.id], d)
        d = get('contacts-partenaires')
        ids = [x['id'] for x in d['resultats']]
        ok('sans departement : 3 partenaires (B inclus)', {pa1.id, pa2.id, pb.id} <= set(ids), ids)
        ligne_b = next(x for x in d['resultats'] if x['id'] == pb.id)
        ok('B : 2 vues, 1 appel, 1 commande', (ligne_b['vues_vitrine'], ligne_b['appels'], ligne_b['commandes'])
           == (2, 1, 1), ligne_b)
        ok('tri invalide -> 400', req(f'{B}contacts-partenaires/{P}&tri=prix', admin_stats).status_code == 400)

        # ═══════════════════════════════════════════════════════════════
        print('=== 4. ACTIVITE ===')
        d = get('activite')
        jours = {x['date']: (x['recherches'], x['evenements'], x['commandes'], x['total']) for x in d['par_jour']}
        ok('par jour : 7 jours, zeros compris', len(d['par_jour']) == 7 and d['par_jour'][0]['date'] == '2001-03-05'
           and jours['2001-03-11'] == (0, 0, 0, 0), d['par_jour'])
        ok('par jour : valeurs exactes', [jours[f'2001-03-0{j}'] for j in (5, 6, 7, 8)] == [
            (1, 4, 1, 6), (2, 2, 1, 5), (2, 2, 2, 6), (0, 3, 1, 4)], jours)
        heures = {x['heure']: x for x in d['par_heure']}
        ok('par heure : 24 lignes ; 10h = 4 recherches + 9 evenements', len(d['par_heure']) == 24
           and (heures[10]['recherches'], heures[10]['evenements'], heures[10]['total']) == (4, 9, 13), heures[10])
        ok('heures de pointe [10, 18, 12]', d['heures_de_pointe'] == [10, 18, 12], d['heures_de_pointe'])
        sem = {x['jour']: (x['libelle'], x['total']) for x in d['par_jour_semaine']}
        ok('jours de semaine (05/03/2001 = lundi)', sem[1] == ('Lundi', 6) and sem[2] == ('Mardi', 5)
           and sem[3] == ('Mercredi', 6) and sem[4] == ('Jeudi', 4) and sem[7] == ('Dimanche', 0), sem)
        ok('jour de pointe : Lundi (egalite avec mercredi -> le premier)', d['jour_de_pointe'] == 'Lundi')

        # ═══════════════════════════════════════════════════════════════
        print('=== 5. RESUME ===')
        d = get('resume')
        ok('periode precedente : 26/02 -> 04/03', (d['periode_precedente']['du'], d['periode_precedente']['au'])
           == ('2001-02-26', '2001-03-04'), d['periode_precedente'])
        i = d['indicateurs']
        attendu = {'nb_recherches': (5, 1, 4.0), 'nb_commandes': (5, 1, 4.0), 'nb_contacts_partenaires': (5, 1, 4.0),
                   'nb_vues_vitrine': (6, 1, 5.0), 'montant_livre': (8000, 1000, 7.0), 'nb_vues_article': (2, 0, None),
                   'nb_ajouts_panier': (6, 0, None), 'nb_paniers_avec_ajout': (5, 0, None),
                   'nb_commandes_livrees': (2, 1, 1.0), 'nb_commandes_annulees': (2, 0, None),
                   'nb_recherches_sans_resultat': (2, 0, None), 'nb_evenements': (11, 1, 10.0)}
        faux = {k: (i[k]['valeur'], i[k]['precedente'], i[k]['evolution']) for k in attendu
                if (i[k]['valeur'], i[k]['precedente'], i[k]['evolution']) != attendu[k]}
        ok('valeurs, precedentes et evolutions exactes', not faux, faux)
        ok('taux : clic 0.4, conversion 1.0', (i['taux_clic_recherche']['valeur'], i['taux_conversion']['valeur'])
           == (0.4, 1.0), (i['taux_clic_recherche'], i['taux_conversion']))
        d = get('resume', PA)
        ok('departement A : commandes 4, vues vitrine 4, recherches 3', (
            d['indicateurs']['nb_commandes']['valeur'], d['indicateurs']['nb_vues_vitrine']['valeur'],
            d['indicateurs']['nb_recherches']['valeur']) == (4, 4, 3), d['indicateurs'])
        ok('departement expose dans la periode', d['periode']['departement'] == dep_a.id)
        d = get('resume', f'?du=2001-03-05&au=2001-03-11&departement={dep_b.id}')
        ok('departement B : 1 commande, montant 3000', (d['indicateurs']['nb_commandes']['valeur'],
                                                         d['indicateurs']['montant_livre']['valeur']) == (1, 3000))

        raise Rollback()
except Rollback:
    print('\nRollback effectue (rien persiste).')

print(f'\n=== TOTAL : {NB_OK} OK / {len(KO)} KO ===')
if KO:
    print('KO :', *KO, sep='\n - ')
    raise SystemExit(1)
