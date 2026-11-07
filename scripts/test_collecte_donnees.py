"""Tests : collecte de données (analyses / IA) — 4 chantiers.

1. Journal des recherches (RechercheLog) : 3 endpoints de recherche, recherche_id,
   terme normalisé, termes < 2 caractères ignorés, clic (une fois, propriétaire).
2. Événements applicatifs (EvenementApp) : serveur (panier, commande, favori) et
   client (POST /analytics/evenements/ : objet ou liste, types autorisés seulement).
3. Avis (social.Avis) : refus si non livré / autre client, création, unicité,
   recalcul note_moyenne / nb_avis, modification 7 jours, réponse partenaire,
   masquage admin (journal), peut_noter / mon_avis, liste publique.
4. Consentements : dates automatiques, anonymisation des journaux sans consentement.

Autonome : crée ses propres données ; limitation de débit désactivée ; tout dans
une transaction annulée. Affiche un total OK / KO (ne s'arrête pas au premier KO).

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_collecte_donnees.py
"""
import json, uuid
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.db import transaction
from django.test import Client
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.analytics.models import EvenementApp, RechercheLog
from apps.catalog.models import Article, ArticleImage, Categorie, RechercheSansResultat
from apps.messaging.models import DemandeIntervention
from apps.orders.models import Commande
from apps.reservations.models import DemandeReservation
from apps.social.models import Avis
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


def req(method, url, user=None, corps=None, **entetes):
    kw = {'secure': True, 'HTTP_HOST': HOST, **entetes}
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


try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        categorie = Categorie.objects.create(nom=f'Collecte QA {uid}', slug=f'collecte-qa-{uid}')
        maintenant = timezone.now()

        def utilisateur(role='client', prenom='', nom='', **kw):
            return User.objects.create(telephone=telephone_libre(), username=f't_col_{uuid.uuid4().hex[:8]}',
                                       role=role, est_verifie=True, first_name=prenom, last_name=nom, **kw)

        def partenaire(nom, type_partenaire='commercant'):
            return ProfilPartenaire.objects.create(
                user=utilisateur('partenaire'), plan=plan, nom_commerce=f'{nom} {uid}',
                type_partenaire=type_partenaire, statut='actif', est_visible=True)

        boutique = partenaire('Boutique Collecte QA')
        autre_boutique = partenaire('Autre Boutique QA')
        resto = partenaire('Resto Collecte QA', 'restaurateur')
        mot = f'zorbaqa{uid}'
        article = Article.objects.create(partenaire=boutique, categorie=categorie, nom=f'Crème {mot}',
                                         slug=f'col-{uuid.uuid4().hex[:8]}', type='produit', prix=1500, est_actif=True)
        ArticleImage.objects.create(article=article, image='articles/col.png', est_principale=True)
        Article.objects.create(partenaire=resto, categorie=categorie, nom=f'Plat {mot}',
                               slug=f'col-{uuid.uuid4().hex[:8]}', type='plat', prix=2000, est_actif=True)

        client = utilisateur(prenom='Awa', nom='Kone', consentement_statistiques=True)  # consent
        client_sans = utilisateur(prenom='Yao', nom='Brou')                               # pas de consentement
        autre_client = utilisateur(prenom='Ali', nom='Sow', consentement_statistiques=True)
        admin_avis = utilisateur('admin', is_staff=True)
        PermissionsAdmin.objects.create(admin=admin_avis, gerer_avis=True)
        admin_sans = utilisateur('admin', is_staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans)

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 1. JOURNAL DES RECHERCHES ===')
        r = req('get', f'/api/v1/catalogue/recherche/?q=Crème  {mot.upper()}', client, HTTP_X_PLATEFORME='android')
        log_id = r.json().get('recherche_id')
        ok('recherche unifiee -> 200 + recherche_id (format inchange)', r.status_code == 200 and log_id
           and {'categories', 'partenaires', 'articles'} <= set(r.json()), r.json().keys())
        log = RechercheLog.objects.filter(pk=log_id).first()
        ok('ligne creee : source accueil, utilisateur (consentement), plateforme',
           log and log.source == 'accueil' and log.utilisateur_id == client.id and log.plateforme == 'android',
           log and (log.source, log.utilisateur_id, log.plateforme))
        ok('terme normalise (minuscules, sans accents, espaces reduits)',
           log and log.terme_normalise == f'creme {mot}', log and log.terme_normalise)
        ok('nb_resultats = categories + partenaires + articles',
           log and log.nb_resultats == sum(len(r.json()[k]) for k in ('categories', 'partenaires', 'articles')))
        avant = RechercheLog.objects.count()
        r = req('get', '/api/v1/catalogue/recherche/?q=a', client)
        ok('terme < 2 caracteres : pas de ligne, pas de recherche_id',
           RechercheLog.objects.count() == avant and 'recherche_id' not in r.json())
        r = req('get', f'/api/v1/catalogue/recherche/?q={mot}', client_sans)
        ok('sans consentement : ligne anonyme',
           RechercheLog.objects.get(pk=r.json()['recherche_id']).utilisateur_id is None)
        r = req('get', f'/api/v1/catalogue/recherche/?q={mot}')
        log_anonyme = r.json().get('recherche_id')
        ok('anonyme : ligne sans utilisateur', RechercheLog.objects.get(pk=log_anonyme).utilisateur_id is None)
        terme_vide = f'introuvable{uid}'
        r = req('get', f'/api/v1/catalogue/recherche/?q={terme_vide}', client)
        ok('sans resultat : RechercheSansResultat toujours alimente + log nb_resultats=0',
           RechercheSansResultat.objects.filter(terme=terme_vide).exists()
           and RechercheLog.objects.get(pk=r.json()['recherche_id']).nb_resultats == 0)

        r = req('get', f'/api/v1/catalogue/articles/?recherche={mot}&categorie={categorie.id}', client)
        d = r.json()
        ok('catalogue articles : recherche_id a la racine, liste inchangee', r.status_code == 200
           and d.get('recherche_id') and 'results' in d, list(d)[:6])
        l2 = RechercheLog.objects.filter(pk=d.get('recherche_id')).first()
        ok('catalogue : source, categorie filtree, nb_resultats = count',
           l2 and l2.source == 'catalogue' and l2.categorie_id == categorie.id and l2.nb_resultats == d['count'],
           l2 and (l2.source, l2.categorie_id, l2.nb_resultats, d.get('count')))
        r = req('get', f'/api/v1/catalogue/articles/?categorie={categorie.id}', client)
        ok('catalogue sans recherche : pas de recherche_id', 'recherche_id' not in r.json())
        r = req('get', f'/api/v1/restaurants/{resto.id}/produits/?q={mot}')
        d = r.json()
        ok('produits etablissement : recherche_id a la racine (pagine)', r.status_code == 200
           and d.get('recherche_id') and {'count', 'results'} <= set(d), r.content[:200])
        ok('produits : source restaurants, nb_resultats',
           RechercheLog.objects.get(pk=d['recherche_id']).source == 'restaurants'
           and RechercheLog.objects.get(pk=d['recherche_id']).nb_resultats == d['count'])

        print('--- clic ---')
        url_clic = f'/api/v1/analytics/recherches/{log_id}/clic/'
        ok('clic par un autre utilisateur -> 403',
           req('post', url_clic, autre_client, {'resultat_type': 'article', 'resultat_id': article.id}).status_code == 403)
        ok('clic type invalide -> 400',
           req('post', url_clic, client, {'resultat_type': 'categorie', 'resultat_id': 1}).status_code == 400)
        r = req('post', url_clic, client, {'resultat_type': 'article', 'resultat_id': article.id})
        log.refresh_from_db()
        ok('clic -> 200, resultat enregistre', r.status_code == 200 and log.resultat_type == 'article'
           and log.resultat_id == str(article.id) and log.clique_le is not None, r.content)
        ok('2e clic -> 409 (une seule fois)',
           req('post', url_clic, client, {'resultat_type': 'partenaire', 'resultat_id': 1}).status_code == 409)
        ok('clic sur une recherche anonyme (par n importe qui) -> 200',
           req('post', f'/api/v1/analytics/recherches/{log_anonyme}/clic/', None,
               {'resultat_type': 'partenaire', 'resultat_id': boutique.id}).status_code == 200)
        ok('clic recherche introuvable -> 404',
           req('post', '/api/v1/analytics/recherches/999999999/clic/', client,
               {'resultat_type': 'article', 'resultat_id': 1}).status_code == 404)

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 2. EVENEMENTS ===')

        def evts(type_evt, **filtres):
            return EvenementApp.objects.filter(type=type_evt, **filtres)

        r = req('post', '/api/v1/orders/paniers/ajouter/', client, {'article': article.id, 'quantite': 2},
                HTTP_X_PLATEFORME='ios', HTTP_X_VERSION_APP='2.4.1')
        e = evts('panier_ajout', objet_id=str(article.id)).first()
        ok('panier_ajout : partenaire, valeur, utilisateur, plateforme, version',
           r.status_code == 201 and e and e.partenaire_id == boutique.id and e.valeur == Decimal('3000')
           and e.utilisateur_id == client.id and e.plateforme == 'ios' and e.version_app == '2.4.1',
           e and (e.partenaire_id, e.valeur, e.utilisateur_id, e.plateforme))
        ligne_id = r.json()['lignes'][0]['id']
        r = req('delete', f'/api/v1/orders/lignes/{ligne_id}/', client)
        ok('panier_retrait', r.status_code == 200 and evts('panier_retrait', objet_id=str(article.id)).exists())
        r = req('post', '/api/v1/orders/paniers/ajouter/', client_sans, {'article': article.id, 'quantite': 1})
        panier_sans = r.json()['id']
        ok('evenement sans consentement : utilisateur null',
           evts('panier_ajout', partenaire=boutique).filter(utilisateur__isnull=True).exists())
        r = req('delete', f'/api/v1/orders/paniers/{panier_sans}/', client_sans)
        ok('panier_vide', r.status_code == 200
           and evts('panier_vide', objet_id=str(panier_sans)).filter(donnees__nb_lignes=1).exists())

        with mock.patch('apps.analytics.models.EvenementApp.objects.create', side_effect=RuntimeError('panne')):
            r = req('post', '/api/v1/orders/paniers/ajouter/', client, {'article': article.id, 'quantite': 1})
        ok('collecte en panne : l action principale reussit quand meme (201)', r.status_code == 201, r.content[:200])
        r = req('post', f'/api/v1/orders/paniers/{r.json()["id"]}/valider/', client, {})
        commande_id = r.json().get('id')
        e = evts('commande_creee', objet_id=str(commande_id)).first()
        ok('commande_creee : valeur = total', r.status_code == 201 and e
           and e.valeur == Decimal(str(r.json()['total'])), (r.status_code, e and e.valeur))
        r2 = req('post', '/api/v1/orders/paniers/ajouter/', client, {'article': article.id, 'quantite': 1})
        r2 = req('post', f'/api/v1/orders/paniers/{r2.json()["id"]}/valider/', client, {})
        commande_annulee_id = r2.json()['id']
        r = req('post', f'/api/v1/orders/commandes/{commande_annulee_id}/transition/', client,
                {'statut': 'annulee', 'raison_refus': 'Trop long'})
        e = evts('commande_annulee', objet_id=str(commande_annulee_id)).first()
        ok('commande_annulee : motif + acteur dans donnees', r.status_code == 200 and e
           and e.donnees.get('motif') == 'Trop long' and e.donnees.get('acteur_role') == 'client',
           (r.status_code, e and e.donnees))

        r = req('post', f'/api/v1/social/articles/{article.id}/favori/', client)
        r = req('post', f'/api/v1/social/articles/{article.id}/favori/', client)
        ok('favori_ajout puis favori_retrait', evts('favori_ajout', objet_id=str(article.id)).exists()
           and evts('favori_retrait', objet_id=str(article.id)).exists())
        req('post', f'/api/v1/social/partenaires/{boutique.id}/favori/', client)
        ok('favori partenaire', evts('favori_ajout', objet_type='partenaire', partenaire=boutique).exists())

        print('--- evenements client ---')
        URL_E = '/api/v1/analytics/evenements/'
        avant = EvenementApp.objects.count()
        r = req('post', URL_E, client, [
            {'type': 'appel_partenaire', 'partenaire_id': boutique.id, 'plateforme': 'android'},
            {'type': 'partage_article', 'objet_type': 'article', 'objet_id': str(article.id),
             'donnees': {'canal': 'whatsapp'}},
        ])
        ok('liste valide -> 201, 2 enregistres', r.status_code == 201 and r.json() == {'nb_enregistres': 2}
           and EvenementApp.objects.count() == avant + 2, r.content)
        ok('evenement client : plateforme du corps', evts('appel_partenaire', partenaire=boutique)
           .filter(plateforme='android', utilisateur=client).exists())
        r = req('post', URL_E, None, {'type': 'itineraire_partenaire', 'partenaire_id': boutique.id})
        ok('objet seul, anonyme -> 201', r.status_code == 201
           and evts('itineraire_partenaire', partenaire=boutique, utilisateur__isnull=True).exists())
        avant = EvenementApp.objects.count()
        r = req('post', URL_E, client, [{'type': 'whatsapp_partenaire'}, {'type': 'panier_ajout'}])
        ok('type interdit (serveur seulement) -> 400, rien enregistre (tout ou rien)',
           r.status_code == 400 and EvenementApp.objects.count() == avant and '1' in r.json()['details'], r.content)
        ok('type inconnu -> 400', req('post', URL_E, client, {'type': 'achat'}).status_code == 400)
        ok('partenaire inexistant -> 400',
           req('post', URL_E, client, {'type': 'appel_partenaire', 'partenaire_id': 999999999}).status_code == 400)
        ok('plus de 50 -> 400',
           req('post', URL_E, client, [{'type': 'appel_partenaire'}] * 51).status_code == 400)
        ok('corps ni objet ni liste -> 400', req('post', URL_E, client, 'texte').status_code == 400)

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 3. AVIS ===')
        commande = Commande.objects.get(pk=commande_id)
        URL_A = '/api/v1/avis/'
        r = req('post', URL_A, client, {'objet_type': 'commande', 'objet_id': commande.id, 'note': 4})
        ok('commande non livree -> 400, message clair', r.status_code == 400
           and 'livrée' in r.json()['message'], r.content)
        r = req('get', f'/api/v1/orders/commandes/{commande.id}/', client)
        ok('detail commande (non livree) : peut_noter false, mon_avis null',
           r.json().get('peut_noter') is False and r.json().get('mon_avis') is None, r.json().get('peut_noter'))
        Commande.objects.filter(pk=commande.pk).update(statut='livree')
        r = req('get', f'/api/v1/orders/commandes/{commande.id}/', client)
        ok('detail commande livree : peut_noter true', r.json().get('peut_noter') is True)
        r = req('get', f'/api/v1/orders/commandes/{commande.id}/', boutique.user)
        ok('detail cote partenaire : pas de peut_noter', 'peut_noter' not in r.json())
        r = req('post', URL_A, autre_client, {'objet_type': 'commande', 'objet_id': commande.id, 'note': 1})
        ok('autre client -> 403', r.status_code == 403, r.content)
        ok('note hors 1-5 -> 400',
           req('post', URL_A, client, {'objet_type': 'commande', 'objet_id': commande.id, 'note': 6}).status_code == 400)
        ok('objet_type invalide -> 400',
           req('post', URL_A, client, {'objet_type': 'article', 'objet_id': 1, 'note': 3}).status_code == 400)
        ok('objet introuvable -> 404',
           req('post', URL_A, client, {'objet_type': 'commande', 'objet_id': 999999999, 'note': 3}).status_code == 404)
        r = req('post', URL_A, client, {'objet_type': 'commande', 'objet_id': commande.id, 'note': 4,
                                        'commentaire': 'Très bon accueil'})
        avis_id = r.json().get('id')
        boutique.refresh_from_db()
        ok('creation -> 201, partenaire rattache', r.status_code == 201 and r.json()['partenaire'] == boutique.id,
           r.content)
        ok('note_moyenne = 4.00, nb_avis = 1', boutique.note_moyenne == Decimal('4.00') and boutique.nb_avis == 1,
           (boutique.note_moyenne, boutique.nb_avis))
        ok('unicite -> 409', req('post', URL_A, client, {'objet_type': 'commande', 'objet_id': commande.id,
                                                         'note': 5}).status_code == 409)
        r = req('get', f'/api/v1/orders/commandes/{commande.id}/', client)
        ok('detail : peut_noter false, mon_avis = id', r.json().get('peut_noter') is False
           and r.json().get('mon_avis') == avis_id)

        commande2 = Commande.objects.create(numero=f'PFR-COL-{uid}', user=autre_client, partenaire=boutique,
                                            statut='livree', total=1000)
        req('post', URL_A, autre_client, {'objet_type': 'commande', 'objet_id': commande2.id, 'note': 2})
        boutique.refresh_from_db()
        ok('2e avis : moyenne 3.00, nb 2', boutique.note_moyenne == Decimal('3.00') and boutique.nb_avis == 2,
           (boutique.note_moyenne, boutique.nb_avis))
        r = req('patch', f'{URL_A}{avis_id}/', client, {'note': 5})
        boutique.refresh_from_db()
        ok('PATCH auteur -> 200, moyenne recalculee 3.50', r.status_code == 200
           and boutique.note_moyenne == Decimal('3.50'), (r.status_code, boutique.note_moyenne))
        ok('PATCH par un autre -> 403', req('patch', f'{URL_A}{avis_id}/', autre_client, {'note': 1}).status_code == 403)
        Avis.objects.filter(pk=avis_id).update(cree_le=maintenant - timedelta(days=8))
        r = req('patch', f'{URL_A}{avis_id}/', client, {'note': 3})
        ok('PATCH apres 7 jours -> 400', r.status_code == 400 and '7 jours' in r.json()['message'], r.content)

        print('--- reponse partenaire ---')
        R = f'{URL_A}{avis_id}/repondre/'
        ok('autre partenaire -> 403', req('post', R, autre_boutique.user, {'reponse': 'Merci'}).status_code == 403)
        ok('client -> 403', req('post', R, client, {'reponse': 'Merci'}).status_code == 403)
        r = req('post', R, boutique.user, {'reponse': 'Merci pour votre visite !'})
        ok('reponse -> 200', r.status_code == 200 and r.json()['reponse_partenaire'] and r.json()['repondu_le'])
        ok('2e reponse -> 409', req('post', R, boutique.user, {'reponse': 'Encore'}).status_code == 409)

        print('--- public, mes avis, admin ---')
        r = req('get', f'/api/v1/partenaires/{boutique.id}/avis/')
        d = r.json()
        ok('public : pagine, visibles, resume note', r.status_code == 200 and d['count'] == 2
           and Decimal(str(d['note_moyenne'])) == Decimal('3.50') and d['nb_avis'] == 2, d)
        ok('public : sans telephone, nom affiche « Prenom I. »',
           all('auteur' not in a for a in d['results']) and any(a['auteur_nom'] == 'Awa K.' for a in d['results']),
           d['results'])
        r = req('get', f'/api/v1/auth/partenaires/{boutique.id}/')
        ok('vitrine : note_moyenne + nb_avis', r.json().get('nb_avis') == 2 and r.json().get('note_moyenne'))
        r = req('patch', f'{URL_A}admin/{avis_id}/', admin_sans, {'est_visible': False})
        ok('admin sans gerer_avis -> 403', r.status_code == 403)
        r = req('patch', f'{URL_A}admin/{avis_id}/', admin_avis, {'est_visible': False, 'motif': 'Propos hors sujet'})
        boutique.refresh_from_db()
        ok('masquage -> 200, note recalculee (2.00, nb 1)', r.status_code == 200 and r.json()['est_visible'] is False
           and boutique.note_moyenne == Decimal('2.00') and boutique.nb_avis == 1, (boutique.note_moyenne, boutique.nb_avis))
        ok('masquage trace dans JournalModeration', JournalModeration.objects.filter(
            acteur=admin_avis, action='avis_masque', motif__contains='Propos hors sujet').exists())
        ok('public : avis masque absent', req('get', f'/api/v1/partenaires/{boutique.id}/avis/').json()['count'] == 1)
        ok('mes-avis : l auteur voit encore son avis masque',
           any(a['id'] == avis_id and a['est_visible'] is False
               for a in req('get', f'{URL_A}mes-avis/', client).json()['results']))
        r = req('get', f'{URL_A}admin/?partenaire={boutique.id}&visible=0', admin_avis)
        ok('admin liste filtree (visible=0)', r.status_code == 200
           and [a['id'] for a in r.json()['results']] == [avis_id], r.content[:200])
        ok('admin liste ?note=2', [a['note'] for a in req('get', f'{URL_A}admin/?partenaire={boutique.id}&note=2',
                                                          admin_avis).json()['results']] == [2])
        req('patch', f'{URL_A}admin/{avis_id}/', admin_avis, {'est_visible': True})
        boutique.refresh_from_db()
        ok('reaffichage : journal avis_affiche, nb_avis 2', boutique.nb_avis == 2 and JournalModeration.objects.filter(
            acteur=admin_avis, action='avis_affiche').exists())
        caps = req('get', '/api/v1/administration/mes-permissions/', admin_avis).json()['capacites']
        ok('mes-permissions : gerer_avis expose', caps.get('gerer_avis') is True)

        print('--- intervention et reservation ---')
        intervention = DemandeIntervention.objects.create(
            numero=f'INT-COL-{uid}', user=client, artisan=autre_boutique, description='Fuite', statut='en_cours')
        ok('intervention non terminee -> 400', req('post', URL_A, client, {
            'objet_type': 'intervention', 'objet_id': intervention.id, 'note': 5}).status_code == 400)
        DemandeIntervention.objects.filter(pk=intervention.pk).update(statut='terminee')
        r = req('get', f'/api/v1/messaging/interventions/{intervention.id}/', client)
        ok('detail intervention terminee : peut_noter true', r.json().get('peut_noter') is True, r.content[:200])
        r = req('post', URL_A, client, {'objet_type': 'intervention', 'objet_id': intervention.id, 'note': 5})
        ok('avis intervention -> 201, artisan note', r.status_code == 201 and r.json()['partenaire'] == autre_boutique.id)
        bien = Article.objects.create(partenaire=autre_boutique, categorie=categorie, nom=f'Bien {uid}',
                                      slug=f'col-{uuid.uuid4().hex[:8]}', type='logement', prix=50000)
        reservation = DemandeReservation.objects.create(
            numero=f'RES-COL-{uid}', client=client, partenaire=autre_boutique, objet=bien,
            nature='reservation', statut='terminee')
        r = req('get', '/api/v1/reservations/mes-demandes/', client)
        lignes = r.json()['results'] if isinstance(r.json(), dict) else r.json()
        ligne = next(x for x in lignes if x['id'] == reservation.id)
        ok('mes-demandes : peut_noter true, mon_avis null', ligne.get('peut_noter') is True and ligne.get('mon_avis') is None,
           ligne)
        r = req('post', URL_A, client, {'objet_type': 'reservation', 'objet_id': reservation.id, 'note': 3})
        autre_boutique.refresh_from_db()
        ok('avis reservation -> 201, moyenne artisan (5+3)/2 = 4.00', r.status_code == 201
           and autre_boutique.note_moyenne == Decimal('4.00') and autre_boutique.nb_avis == 2,
           (r.status_code, autre_boutique.note_moyenne))

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 4. CONSENTEMENTS ===')
        U = '/api/v1/auth/moi/consentements/'
        r = req('get', U, client_sans)
        ok('GET : valeurs par defaut', r.status_code == 200 and r.json()['consentement_statistiques'] is False
           and r.json()['consentement_ia'] is False and r.json()['consentement_statistiques_le'] is None, r.content)
        r = req('patch', U, client_sans, {'consentement_statistiques': True, 'consentement_version': '2026-11'})
        client_sans.refresh_from_db()
        date_stats = client_sans.consentement_statistiques_le
        ok('PATCH statistiques : date posee, version', r.status_code == 200 and client_sans.consentement_statistiques
           and date_stats is not None and client_sans.consentement_version == '2026-11'
           and client_sans.consentement_ia_le is None, r.content)
        req('patch', U, client_sans, {'consentement_statistiques': True, 'consentement_ia': True})
        client_sans.refresh_from_db()
        ok('meme valeur : date inchangee ; IA : date posee',
           client_sans.consentement_statistiques_le == date_stats and client_sans.consentement_ia_le is not None)
        ok('dates non modifiables a la main', req('patch', U, client_sans, {
            'consentement_ia_le': '2000-01-01T00:00:00Z'}).json()['consentement_ia_le'] != '2000-01-01T00:00:00Z')
        r = req('get', f'/api/v1/catalogue/recherche/?q={mot}', client_sans)
        ok('apres consentement : recherche rattachee a l utilisateur',
           RechercheLog.objects.get(pk=r.json()['recherche_id']).utilisateur_id == client_sans.id)
        req('patch', U, client_sans, {'consentement_statistiques': False})
        client_sans.refresh_from_db()
        ok('retrait : date mise a jour', client_sans.consentement_statistiques_le > date_stats)
        r = req('get', f'/api/v1/catalogue/recherche/?q={mot}', client_sans)
        ok('retrait : recherches de nouveau anonymes',
           RechercheLog.objects.get(pk=r.json()['recherche_id']).utilisateur_id is None)
        r = req('get', '/api/v1/auth/moi/', client)
        ok('profil /auth/moi/ : 2 booleens exposes', r.json().get('consentement_statistiques') is True
           and r.json().get('consentement_ia') is False, r.content[:200])
        req('patch', '/api/v1/auth/moi/', client, {'consentement_statistiques': False})
        client.refresh_from_db()
        ok('profil : consentements en lecture seule (modif via /consentements/)', client.consentement_statistiques is True)
        ok('consentements : non connecte -> 401', req('get', U).status_code == 401)

        raise Rollback()
except Rollback:
    print('\nRollback effectue (rien persiste).')

print(f'\n=== TOTAL : {NB_OK} OK / {len(KO)} KO ===')
if KO:
    print('KO :', *KO, sep='\n - ')
    raise SystemExit(1)
