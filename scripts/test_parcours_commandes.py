"""Tests : deux parcours de commande selon le type du partenaire.

Parcours « court » (commerces : boulangerie, mode, élevage, pharmacie…) :
nouvelle → acceptee → [en_livraison si livraison] → livree.
Parcours « restauration » (restaurateur, fast_food, grilleur) :
nouvelle → acceptee (= préparation lancée) → prete → [en_livraison] → livree.
Anciennes commandes en en_preparation / prete : terminent leur parcours.
Couvre : transitions autorisées / refusées (400, message clair), étapes et
parcours exposés (client, partenaire, admin), demande de livreur selon le
parcours, notification d'acceptation.

Données propres, rollback à la fin (aucune donnée conservée).
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_parcours_commandes.py
"""
import json
import uuid
from unittest import mock

from django.contrib.gis.geos import Point
from django.db import transaction
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken

from apps.geo.models import Departement
from apps.orders import services
from apps.orders.models import Commande, HistoriqueCommande
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
# Limitation de débit DRF désactivée pour ce script (même mécanisme que les autres scripts).
from unittest import mock as _mock_debit
from rest_framework.views import APIView as _APIViewDebit
_mock_debit.patch.object(_APIViewDebit, 'get_throttles', return_value=[]).start()
NB_OK = 0


class Rollback(Exception):
    pass


def ok(libelle, condition, detail=''):
    global NB_OK
    print(('OK   ' if condition else 'FAIL '), libelle, '' if condition else detail)
    assert condition, f'{libelle} {detail}'
    NB_OK += 1


def entetes(user):
    return {'HTTP_AUTHORIZATION': f'Bearer {AccessToken.for_user(user)}', 'HTTP_HOST': HOST}


def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel


def compte(nom, role='client', staff=False, superuser=False):
    return User.objects.create(telephone=telephone_libre(), username=f'{nom}_{uuid.uuid4().hex[:5]}',
                               role=role, is_staff=staff, is_superuser=superuser, est_verifie=True)


avant = Commande.objects.count()
try:
    with transaction.atomic():
        c = Client()
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.first()
        departement = Departement.objects.order_by('id').first()   # requis par une course livreur

        def partenaire(type_, nom):
            return ProfilPartenaire.objects.create(
                user=compte(f't_parc_{type_}', 'partenaire'), plan=plan, nom_commerce=f'{nom} {uid}',
                type_partenaire=type_, statut='actif', est_visible=True, departement=departement,
                localisation=Point(-5.2, 9.6, srid=4326))

        boulanger = partenaire('boulanger', 'Boulangerie')
        mode = partenaire('boutique_mode', 'Chaussures')
        resto = partenaire('restaurateur', 'Maquis')
        grilleur = partenaire('grilleur', 'Grillades')
        client = compte('t_parc_client')
        super_ = compte('t_parc_super', 'admin', staff=True, superuser=True)
        n = [0]

        def commande(p, mode_livraison='emporter', statut='nouvelle'):
            n[0] += 1
            return Commande.objects.create(
                numero=f'PFR-PARC-{uid}-{n[0]}', user=client, partenaire=p, mode_livraison=mode_livraison,
                statut=statut, sous_total=1000, frais_livraison=500 if mode_livraison == 'livraison' else 0,
                total=1500 if mode_livraison == 'livraison' else 1000,
                localisation_livraison=Point(-5.21, 9.61, srid=4326) if mode_livraison == 'livraison' else None)

        def transition(cmd, statut, user=None):
            user = user or cmd.partenaire.user
            return c.post(f'/api/v1/orders/commandes/{cmd.id}/transition/', json.dumps({'statut': statut}),
                          content_type='application/json', secure=True, **entetes(user))

        def parcours_complet(cmd, statuts):
            for s in statuts:
                r = transition(cmd, s)
                if r.status_code != 200:
                    return r
            return r

        def actions(cmd):
            cmd.refresh_from_db()
            return [str(x) for x in services.transitions_pour(cmd)]

        print('=== 1. PARCOURS COURT : PAIN A EMPORTER (2 transitions) ===')
        pain = commande(boulanger)
        ok('boulanger -> parcours court', services.parcours_de(pain) == 'court')
        ok('etapes court + retrait', [str(e) for e in services.etapes_pour(pain)] == ['nouvelle', 'acceptee', 'livree'])
        r = parcours_complet(pain, ['acceptee', 'livree'])
        pain.refresh_from_db()
        ok('nouvelle -> acceptee -> livree (2 clics)', r.status_code == 200 and pain.statut == 'livree'
           and pain.acceptee_le and pain.livree_le, r.content)
        ok('historique : 2 transitions partenaire', list(HistoriqueCommande.objects.filter(commande=pain)
           .values_list('statut', flat=True)) == ['acceptee', 'livree'])
        pain2 = commande(boulanger)
        transition(pain2, 'acceptee')
        ok('court acceptee (retrait) : livree, expiree, annulee', actions(pain2) == ['livree', 'expiree', 'annulee'],
           actions(pain2))
        r = transition(pain2, 'en_livraison')
        ok('en_livraison refuse en retrait -> 400 + message clair', r.status_code == 400
           and r.json()['message'].startswith('Transition acceptee → en_livraison non autorisée')
           and 'Livrée' in r.json()['message'], r.content)
        ok('en_preparation refuse au parcours court', transition(pain2, 'en_preparation').status_code == 400)
        ok('prete refuse au parcours court', transition(pain2, 'prete').status_code == 400)

        print('=== 2. PARCOURS COURT : CHAUSSURE EN LIVRAISON ===')
        chaussure = commande(mode, 'livraison')
        ok('etapes court + livraison', [str(e) for e in services.etapes_pour(chaussure)]
           == ['nouvelle', 'acceptee', 'en_livraison', 'livree'])
        transition(chaussure, 'acceptee')
        ok('court acceptee (livraison) : en_livraison en premier', actions(chaussure)
           == ['en_livraison', 'livree', 'expiree', 'annulee'], actions(chaussure))
        r = parcours_complet(chaussure, ['en_livraison', 'livree'])
        chaussure.refresh_from_db()
        ok('acceptee -> en_livraison -> livree', r.status_code == 200 and chaussure.statut == 'livree', r.content)

        print('=== 3. PARCOURS RESTAURATION ===')
        plat = commande(resto)
        ok('restaurateur -> restauration ; grilleur aussi', services.parcours_de(plat) == 'restauration'
           and services.parcours_de(commande(grilleur)) == 'restauration')
        ok('etapes restauration + retrait', [str(e) for e in services.etapes_pour(plat)]
           == ['nouvelle', 'acceptee', 'prete', 'livree'])
        transition(plat, 'acceptee')
        ok('restauration acceptee : prete, annulee', actions(plat) == ['prete', 'annulee'], actions(plat))
        r = transition(plat, 'en_preparation')
        ok('en_preparation refuse depuis acceptee -> 400', r.status_code == 400
           and 'En préparation' in r.json()['message'], r.content)
        ok('livree directe refusee depuis acceptee', transition(plat, 'livree').status_code == 400)
        r = parcours_complet(plat, ['prete', 'livree'])
        plat.refresh_from_db()
        ok('acceptee -> prete -> livree', r.status_code == 200 and plat.statut == 'livree' and plat.prete_le, r.content)
        plat_liv = commande(resto, 'livraison')
        ok('etapes restauration + livraison', [str(e) for e in services.etapes_pour(plat_liv)]
           == ['nouvelle', 'acceptee', 'prete', 'en_livraison', 'livree'])
        parcours_complet(plat_liv, ['acceptee', 'prete'])
        ok('restauration prete (livraison) : en_livraison, livree, expiree',
           actions(plat_liv) == ['en_livraison', 'livree', 'expiree'], actions(plat_liv))
        plat_ret = commande(resto)
        parcours_complet(plat_ret, ['acceptee', 'prete'])
        ok('restauration prete (retrait) : pas de en_livraison', actions(plat_ret) == ['livree', 'expiree'])

        print('=== 4. ANCIENNES COMMANDES (compatibilite) ===')
        ancienne = commande(boulanger, statut='en_preparation')
        ok('court en_preparation : prete, annulee', actions(ancienne) == ['prete', 'annulee'])
        r = parcours_complet(ancienne, ['prete', 'livree'])
        ancienne.refresh_from_db()
        ok('court en_preparation -> prete -> livree', r.status_code == 200 and ancienne.statut == 'livree', r.content)
        ancienne_r = commande(resto, 'livraison', statut='en_preparation')
        r = parcours_complet(ancienne_r, ['prete', 'en_livraison', 'livree'])
        ancienne_r.refresh_from_db()
        ok('restauration en_preparation -> prete -> en_livraison -> livree', r.status_code == 200
           and ancienne_r.statut == 'livree', r.content)
        ok('ancienne en_preparation annulable', transition(commande(mode, statut='en_preparation'), 'annulee')
           .status_code == 200)
        ok('ancienne prete (court) expirable', transition(commande(mode, statut='prete'), 'expiree').status_code == 200)

        print('=== 5. DEMANDE DE LIVREUR ===')
        court_liv = commande(mode, 'livraison')
        ok('court nouvelle : pas eligible', services.commande_eligible_livreur(court_liv) is False)
        transition(court_liv, 'acceptee')
        court_liv.refresh_from_db()
        ok('court acceptee en livraison : eligible', services.commande_eligible_livreur(court_liv) is True)
        court_ret = commande(mode)
        transition(court_ret, 'acceptee')
        court_ret.refresh_from_db()
        ok('court acceptee en retrait : pas eligible', services.commande_eligible_livreur(court_ret) is False)
        ok('court ancienne prete en livraison : eligible',
           services.commande_eligible_livreur(commande(mode, 'livraison', statut='prete')) is True)
        r = c.post(f'/api/v1/orders/commandes/{court_liv.id}/livreur/', secure=True, **entetes(mode.user))
        court_liv.refresh_from_db()
        ok('partenaire court : demande de livreur sur acceptee -> 201, en_livraison', r.status_code == 201
           and court_liv.statut == 'en_livraison', r.content)
        resto_liv = commande(resto, 'livraison')
        transition(resto_liv, 'acceptee')
        resto_liv.refresh_from_db()
        ok('restauration acceptee : pas eligible', services.commande_eligible_livreur(resto_liv) is False)
        r = c.post(f'/api/v1/orders/commandes/{resto_liv.id}/livreur/', secure=True, **entetes(resto.user))
        ok('restauration acceptee : demande refusee 400 « doit etre prete »', r.status_code == 400
           and 'prête' in r.json()['message'], r.content)
        transition(resto_liv, 'prete')
        resto_liv.refresh_from_db()
        ok('restauration prete : eligible', services.commande_eligible_livreur(resto_liv) is True)
        r = c.post(f'/api/v1/orders/admin/commandes/{resto_liv.id}/demander-livreur/', json.dumps({}),
                   content_type='application/json', secure=True, **entetes(super_))
        ok('admin : demande de livreur sur restauration prete -> 201', r.status_code == 201, r.content)
        court_nouv = commande(mode, 'livraison')
        r = c.post(f'/api/v1/orders/commandes/{court_nouv.id}/livreur/', secure=True, **entetes(mode.user))
        ok('court nouvelle : refus 400 « doit etre acceptee »', r.status_code == 400
           and 'acceptée' in r.json()['message'], r.content)

        print('=== 6. CHAMPS EXPOSES (client, partenaire, admin) ===')
        cmd = commande(mode, 'livraison')
        r = c.get('/api/v1/orders/commandes/partenaire/', secure=True, **entetes(mode.user))
        ligne = next(x for x in r.json() if x['id'] == cmd.id)
        ok('partenaire : parcours, etapes, transitions_possibles', ligne['parcours'] == 'court'
           and ligne['etapes'] == ['nouvelle', 'acceptee', 'en_livraison', 'livree']
           and [t['action'] for t in ligne['transitions_possibles']] == ['acceptee', 'refusee', 'annulee'], ligne)
        ok('partenaire : format {action, libelle, commentaire_obligatoire}, libelles inchanges',
           ligne['transitions_possibles'][0] == {'action': 'acceptee', 'libelle': 'Accepter',
                                                  'commentaire_obligatoire': False}, ligne['transitions_possibles'])
        ok('partenaire : anciens champs conserves', {'id', 'numero', 'statut', 'lignes', 'total', 'acceptee_le',
                                                     'prete_le', 'livree_le', 'mode_livraison'} <= set(ligne))
        r = c.get('/api/v1/orders/commandes/', secure=True, **entetes(client))
        vue_client = next(x for x in r.json() if x['id'] == cmd.id)
        ok('client : parcours + etapes ; seule action = annuler', vue_client['parcours'] == 'court'
           and vue_client['etapes'] == ligne['etapes']
           and [t['action'] for t in vue_client['transitions_possibles']] == ['annulee'], vue_client)
        transition(cmd, 'acceptee')
        r = c.get(f'/api/v1/orders/commandes/{cmd.id}/', secure=True, **entetes(client))
        ok('client : commande acceptee -> aucune action', r.json()['transitions_possibles'] == [], r.json())
        r = c.get(f'/api/v1/orders/commandes/{cmd.id}/', secure=True, **entetes(mode.user))
        ok('partenaire (detail) : actions du parcours court', [t['action'] for t in r.json()['transitions_possibles']]
           == ['en_livraison', 'livree', 'expiree', 'annulee'], r.json())
        r = c.get(f'/api/v1/orders/admin/commandes/{plat_liv.id}/', secure=True, **entetes(super_))
        d = r.json()
        ok('admin detail : parcours, etapes, transitions (motif obligatoire pour annuler)',
           d['parcours'] == 'restauration' and d['etapes'] == ['nouvelle', 'acceptee', 'prete', 'en_livraison', 'livree']
           and [t['action'] for t in d['transitions_possibles']] == ['en_livraison', 'livree', 'expiree'], d)
        r = c.get(f'/api/v1/orders/admin/commandes/{commande(resto).id}/', secure=True, **entetes(super_))
        ok('admin : commentaire_obligatoire inchange (annulee=True)',
           {t['action']: t['commentaire_obligatoire'] for t in r.json()['transitions_possibles']}['annulee'] is True)
        r = c.get(f'/api/v1/orders/admin/commandes/?partenaire={boulanger.id}', secure=True, **entetes(super_))
        lignes = r.json()['results']
        ok('admin liste : parcours + etapes', lignes and all(x['parcours'] == 'court'
           and x['etapes'][0] == 'nouvelle' for x in lignes), lignes[:1])
        r = c.post(f'/api/v1/orders/admin/commandes/{commande(resto).id}/transition/', json.dumps(
            {'action': 'en_preparation'}), content_type='application/json', secure=True, **entetes(super_))
        ok('admin : transition interdite -> 400 message clair', r.status_code == 400
           and 'non autorisée' in r.json()['message'], r.content)

        print('=== 7. NOTIFICATION D ACCEPTATION ===')
        with mock.patch('apps.orders.services.notifier_utilisateur') as notif:
            transition(commande(resto), 'acceptee')
            transition(commande(boulanger), 'acceptee')
        messages = [call.args[2] for call in notif.call_args_list]
        ok('restauration : « acceptee et est en preparation »',
           any(m.endswith('a ete acceptee et est en preparation.') for m in messages), messages)
        ok('court : « a ete acceptee » (inchange)', any(m.endswith('a ete acceptee.') for m in messages), messages)

        print('=== 8. CLIENT : ANNULATION SEULEMENT SI NOUVELLE (inchange) ===')
        cmd2 = commande(boulanger)
        ok('client annule une commande nouvelle -> 200', transition(cmd2, 'annulee', client).status_code == 200)
        cmd3 = commande(boulanger)
        transition(cmd3, 'acceptee')
        ok('client ne peut pas livrer -> 403', transition(cmd3, 'livree', client).status_code == 403)

        print(f'\n=== {NB_OK} verifications reussies ===')
        raise Rollback('annulation volontaire')
except Rollback as e:
    print('Rollback effectue :', e)

assert Commande.objects.count() == avant, 'des commandes de test ont persiste !'
print('Aucune donnee persistee (commandes : %d avant/apres).' % avant)
