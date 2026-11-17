"""Tests : Web Push de l'admin web (VAPID) — envoi SIMULÉ, aucun appel réseau.

- endpoints push-web/ : clé publique, abonnement (multi-appareils, mise à
  jour, rattachement à un autre compte, désabonnement limité à son compte,
  validations), test ; droits (anonyme 401, client 403) ;
- admins : diffuser_compteurs_admin(..., push=...) et un vrai point
  d'émission (commande) ; partenaires : notifier_utilisateur (sans fcm_actif) ;
  admin via notifier_utilisateur : pas de doublon ;
- payload ngsw (notification, tag par canal, renotify, onActionClick),
  URL /notifications/ouvrir?ecran=&id= (et sans cible), texte regroupé ;
- nettoyage : 410 / 404 supprimés, 5 échecs consécutifs, succès -> remise à 0 ;
- flag éteint ou clés absentes : rien n'est envoyé ;
- trois cloches : tag restaurant / service / general et regroupement par
  canal, vrais points d'émission (commande boulanger, réservation,
  intervention, pub, changement de numéro).

Le réseau (pywebpush) et le pool de threads sont simulés (exécution
synchrone) ; les callbacks on_commit sont exécutés explicitement.
Transaction annulée (rien ne persiste), limitation de débit désactivée.
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_push_web.py
"""
import json
import sys
import traceback
import uuid
from types import SimpleNamespace
from unittest import mock

from django.db import transaction
from django.test import Client, TestCase
from django.test.utils import override_settings
from rest_framework_simplejwt.tokens import AccessToken

from apps.moderation.models import Notification
from apps.notifications import push_web
from apps.notifications.fcm import notifier_utilisateur
from apps.notifications.models import AbonnementPushWeb
from apps.notifications.temps_reel import diffuser_compteurs_admin
from apps.orders.models import Commande
from apps.orders.services import _notifier_admins_commande
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
# Limitation de débit DRF désactivée pour ce script : sinon tous les scripts partagent
# le compteur anonyme (60/min, client de test = 127.0.0.1) et la suite complète reçoit des 429.
from rest_framework.views import APIView as _APIViewDebit
mock.patch.object(_APIViewDebit, 'get_throttles', return_value=[]).start()

URL = '/api/v1/notifications/push-web/'
CLES = {'VAPID_PUBLIC_KEY': 'CLE-PUBLIQUE-TEST', 'VAPID_PRIVATE_KEY': 'CLE-PRIVEE-TEST',
        'VAPID_SUBJECT': 'mailto:test@example.invalid'}


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
    return User.objects.create(telephone=telephone_libre(), username=f't_push_{uuid.uuid4().hex[:8]}',
                               role=role, est_verifie=True, **kw)


def req(method, url, user=None, corps=None):
    kw = {'secure': True, 'HTTP_HOST': HOST, 'HTTP_USER_AGENT': 'Chrome QA'}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    if corps is None:
        return getattr(Client(), method)(url, **kw)
    return getattr(Client(), method)(url, json.dumps(corps), content_type='application/json', **kw)


class FauxEchec(Exception):
    """Réponse d'erreur du service push (comme WebPushException.response)."""
    def __init__(self, code):
        super().__init__(f'HTTP {code}')
        self.response = SimpleNamespace(status_code=code)


ENVOIS, ECHECS = [], {}  # ECHECS : endpoint -> code HTTP à simuler


def faux_webpush(abonnement, payload):
    code = ECHECS.get(abonnement['endpoint'])
    if code:
        raise FauxEchec(code)
    ENVOIS.append((abonnement['endpoint'], payload))


FLAG = {'actif': True}


def executer(fn):
    """Exécute fn puis les callbacks on_commit qu'elle a planifiés (push
    compris) ; renvoie les envois simulés vers les endpoints du test."""
    ENVOIS.clear()
    with TestCase.captureOnCommitCallbacks(execute=True):
        resultat = fn()
    return resultat


def envois_vers(*endpoints):
    return [(e, p) for e, p in ENVOIS if e in endpoints]


mock.patch.object(push_web, '_webpush', side_effect=faux_webpush).start()
mock.patch.object(push_web, '_flag_global', side_effect=lambda nom: FLAG['actif'] and nom == 'push_web_actif').start()
mock.patch.object(push_web._executeur, 'submit', side_effect=lambda fn, *a: fn(*a)).start()

try:
    with override_settings(**CLES), transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        admin = utilisateur('admin', is_staff=True, is_superuser=True)
        p_user = utilisateur('partenaire')
        partenaire = ProfilPartenaire.objects.create(
            user=p_user, plan=PlanAbonnement.objects.get(libelle='Basique'), nom_commerce=f'Boutique Push {uid}',
            type_partenaire='commercant', statut='actif', est_visible=True)
        client = utilisateur('client')
        E = {k: f'https://fcm.googleapis.com/fcm/send/qa-{uid}-{k}' for k in ('a1', 'a2', 'p1', 'x')}

        def abonner(user, endpoint, **autres):
            return req('post', URL + 'abonnement/', user, {
                'endpoint': endpoint, 'keys': {'p256dh': f'P256-{endpoint[-6:]}', 'auth': 'AUTH'}, **autres})

        print('=== 1. ENDPOINTS ET DROITS ===')
        ok('cle-publique : anonyme -> 401', req('get', URL + 'cle-publique/').status_code == 401)
        ok('cle-publique : client -> 403', req('get', URL + 'cle-publique/', client).status_code == 403)
        r = req('get', URL + 'cle-publique/', admin)
        ok('cle-publique : admin -> cle + actif', r.status_code == 200 and r.json() == {
            'cle_publique': 'CLE-PUBLIQUE-TEST', 'actif': True}, r.content)
        ok('cle-publique : partenaire -> 200', req('get', URL + 'cle-publique/', p_user).status_code == 200)
        r = abonner(admin, E['a1'])
        ok('abonnement admin (appareil 1) -> 201', r.status_code == 201 and r.json()['nb_abonnements'] == 1, r.content)
        r = abonner(admin, E['a1'])
        ok('meme navigateur -> 200, pas de doublon', r.status_code == 200
           and AbonnementPushWeb.objects.filter(endpoint=E['a1']).count() == 1, r.content)
        r = abonner(admin, E['a2'])
        ok('appareil 2 -> 201, 2 abonnements actifs', r.status_code == 201 and r.json()['nb_abonnements'] == 2)
        ok('user_agent enregistre', AbonnementPushWeb.objects.get(endpoint=E['a2']).user_agent == 'Chrome QA')
        ok('endpoint http -> 400', abonner(admin, 'http://exemple.invalid/x').status_code == 400)
        r = req('post', URL + 'abonnement/', admin, {'endpoint': E['x']})
        ok('cles absentes -> 400', r.status_code == 400, r.content)
        ok('client -> 403', abonner(client, E['x']).status_code == 403)
        ok('anonyme -> 401', abonner(None, E['x']).status_code == 401)
        ok('abonnement partenaire -> 201', abonner(p_user, E['p1']).status_code == 201)
        r = abonner(p_user, E['a2'])
        ok('navigateur repris par un autre compte -> rattache (200)', r.status_code == 200
           and AbonnementPushWeb.objects.get(endpoint=E['a2']).user_id == p_user.id
           and AbonnementPushWeb.objects.filter(user=admin).count() == 1)
        abonner(admin, E['a2'])
        r = req('delete', URL + 'abonnement/', p_user, {'endpoint': E['a1']})
        ok('desabonnement d un navigateur d un autre compte : sans effet', r.status_code == 204
           and AbonnementPushWeb.objects.filter(endpoint=E['a1'], user=admin).exists())
        r = req('delete', URL + 'abonnement/', admin, {'endpoint': E['a2']})
        ok('desabonnement -> 204, supprime', r.status_code == 204
           and not AbonnementPushWeb.objects.filter(endpoint=E['a2']).exists())
        ok('desabonnement sans endpoint -> 400', req('delete', URL + 'abonnement/', admin, {}).status_code == 400)
        abonner(admin, E['a2'])

        print('=== 2. ADMINS ===')
        for i in range(3):
            Notification.objects.create(user=admin, type='commande_nouvelle', titre='x', contenu='x',
                                        data={}, canal='general')
        executer(lambda: diffuser_compteurs_admin([admin], True, push=(
            'Nouvelle commande', 'PFR-1 — Boutique', {'commande_id': 12, 'canal': 'general'})))
        recus = envois_vers(E['a1'], E['a2'])
        ok('admin : envoye a ses 2 appareils', sorted(e for e, _ in recus) == sorted([E['a1'], E['a2']]), ENVOIS)
        n = recus[0][1]['notification'] if recus else {}
        url = '/notifications/ouvrir?ecran=commandes&id=12'
        ok('payload ngsw : title, body regroupe (3 non lues), tag general, renotify, icone', (
            n.get('title'), n.get('body'), n.get('tag'), n.get('renotify'), bool(n.get('icon'))) == (
            'Nouvelle commande', '3 nouvelles notifications (dernière : PFR-1 — Boutique)', 'general', True, True), n)
        ok('payload ngsw : data.url et onActionClick -> /notifications/ouvrir?ecran=commandes&id=12',
           n.get('data') == {'url': url, 'onActionClick': {'default': {
               'operation': 'navigateLastFocusedOrOpen', 'url': url}}}, n.get('data'))
        executer(lambda: diffuser_compteurs_admin([admin], True, push=(
            'Réservation', 'Demande D-7', {'demande_id': 7, 'canal': 'service'})))
        n = (envois_vers(E['a1']) or [(None, {'notification': {}})])[0][1]['notification']
        ok('canal service sans non lue : texte simple, tag service, ecran demandes_location', (
            n.get('body'), n.get('tag'), n.get('data', {}).get('url')) == (
            'Demande D-7', 'service', '/notifications/ouvrir?ecran=demandes_location&id=7'), n)
        executer(lambda: diffuser_compteurs_admin([admin], False))
        ok('diffusion sans push (lecture) : aucune notification systeme', not envois_vers(E['a1'], E['a2']))
        commande = Commande.objects.create(numero=f'PFR-PUSH-{uid}', user=client, partenaire=partenaire,
                                           statut='nouvelle', sous_total=1000, total=1000)
        executer(lambda: _notifier_admins_commande(commande, 'commande_nouvelle', 'Nouvelle commande',
                                                   f'{commande.numero} — Boutique Push'))
        recus = envois_vers(E['a1'], E['a2'])
        ok('vrai point d emission (commande) : push admin avec lien vers la commande', len(recus) == 2 and all(
            p['notification']['data']['url'] == f'/notifications/ouvrir?ecran=commandes&id={commande.id}'
            and p['notification']['title'] == 'Nouvelle commande' for _, p in recus), ENVOIS)
        ok('commande commercant : tag general', recus and all(p['notification']['tag'] == 'general' for _, p in recus))

        print('=== 2b. TROIS CLOCHES ===')
        Notification.objects.filter(user=admin).update(lu=True)
        for canal_, nb_ in (('restaurant', 2), ('service', 3)):
            for _ in range(nb_):
                Notification.objects.create(user=admin, type='systeme', titre='x', contenu='x', canal=canal_)
        for canal_, attendu in (('restaurant', '2 nouvelles notifications (dernière : C)'),
                                ('service', '3 nouvelles notifications (dernière : C)'),
                                ('general', 'C')):
            executer(lambda: diffuser_compteurs_admin([admin], True, push=('T', 'C', {'canal': canal_})))
            n = (envois_vers(E['a1']) or [(None, {'notification': {}})])[0][1]['notification']
            ok(f'canal {canal_} : tag {canal_}, regroupement sur les seules non lues du canal',
               (n.get('tag'), n.get('body')) == (canal_, attendu), n)
        Notification.objects.filter(user=admin).update(lu=True)

        def tag_du_push(fn):
            executer(fn)
            recus = envois_vers(E['a1'])
            return recus[0][1]['notification'].get('tag') if recus else None
        from apps.administration.views_telephone import _notifier_changement_telephone
        from apps.messaging.services import notifier_admins_intervention_nouvelle
        from apps.publicites.services import _notifier_admins_pub
        from apps.reservations.services import _notifier_admins_demande
        boul = ProfilPartenaire.objects.create(
            user=utilisateur('partenaire'), plan=PlanAbonnement.objects.get(libelle='Basique'),
            nom_commerce=f'Boulangerie Push {uid}', type_partenaire='boulanger', statut='actif', est_visible=True)
        c_boul = Commande.objects.create(numero=f'PFR-PUSHB-{uid}', user=client, partenaire=boul,
                                         statut='nouvelle', sous_total=1000, total=1000)
        ok('commande boulanger -> tag restaurant', tag_du_push(lambda: _notifier_admins_commande(
            c_boul, 'commande_nouvelle', 'Nouvelle commande', 'Boulangerie')) == 'restaurant')
        ok('reservation -> tag service', tag_du_push(lambda: _notifier_admins_demande(
            SimpleNamespace(id=987661, pk=987661, statut='en_attente'),
            'reservation_nouvelle', 'Nouvelle demande', 'QA')) == 'service')
        interv = SimpleNamespace(
            id=987662, pk=987662, statut='en_attente', numero='INT-QA',
            artisan=SimpleNamespace(nom_commerce='Artisan QA'),
            user=SimpleNamespace(get_full_name=lambda: 'Client QA', telephone='+2250000000000'),
            get_type_intervention_display=lambda: 'Depannage', get_urgence_display=lambda: 'Urgent')
        ok('intervention -> tag service', tag_du_push(lambda: notifier_admins_intervention_nouvelle(interv)) == 'service')
        pid = str(uuid.uuid4())
        ok('pub soumise -> tag general', tag_du_push(lambda: _notifier_admins_pub(
            SimpleNamespace(id=pid, pk=pid, statut='en_attente'), 'pub_soumise', 'Pub', 'QA')) == 'general')
        ok('changement de numero -> tag general', tag_du_push(lambda: _notifier_changement_telephone(
            admin, '+2250700000097', 'QA')) == 'general')
        Notification.objects.filter(user=admin).update(lu=True)

        print('=== 3. PARTENAIRES ===')
        executer(lambda: notifier_utilisateur(p_user, 'Commande annulee', 'La commande PFR-9 a ete annulee.',
                                              data={'type': 'commande', 'commande_id': '42', 'statut': 'annulee'}))
        recus = envois_vers(E['p1'])
        n = recus[0][1]['notification'] if recus else {}
        ok('partenaire : web push sans fcm_actif (flag FCM eteint)', len(recus) == 1, ENVOIS)
        ok('partenaire : texte simple, tag general, lien commande 42', (
            n.get('title'), n.get('body'), n.get('tag'), n.get('data', {}).get('url')) == (
            'Commande annulee', 'La commande PFR-9 a ete annulee.', 'general',
            '/notifications/ouvrir?ecran=commandes&id=42'), n)
        executer(lambda: notifier_utilisateur(p_user, 'Info', 'Sans cible', data={'type': 'compte'}))
        n = (envois_vers(E['p1']) or [(None, {'notification': {}})])[0][1]['notification']
        ok('sans cible : URL /notifications/ouvrir', n.get('data', {}).get('url') == '/notifications/ouvrir', n)
        executer(lambda: notifier_utilisateur(admin, 'Info admin', 'x', data={}))
        ok('admin via notifier_utilisateur : pas de doublon web', not envois_vers(E['a1'], E['a2']), ENVOIS)

        print('=== 4. NETTOYAGE ===')
        AbonnementPushWeb.objects.filter(endpoint=E['p1']).update(nb_echecs=3)
        executer(lambda: notifier_utilisateur(p_user, 'Ok', 'Ok', data={}))
        a = AbonnementPushWeb.objects.get(endpoint=E['p1'])
        ok('succes : nb_echecs remis a 0, dernier_envoi_ok renseigne', a.nb_echecs == 0 and a.dernier_envoi_ok)
        ECHECS[E['a1']] = 410
        executer(lambda: diffuser_compteurs_admin([admin], True, push=('T', 'C', {'canal': 'general'})))
        ok('410 : abonnement supprime', not AbonnementPushWeb.objects.filter(endpoint=E['a1']).exists())
        abonner(admin, E['a1'])
        ECHECS[E['a1']] = 404
        executer(lambda: diffuser_compteurs_admin([admin], True, push=('T', 'C', {'canal': 'general'})))
        ok('404 : abonnement supprime', not AbonnementPushWeb.objects.filter(endpoint=E['a1']).exists())
        ECHECS.clear()
        ECHECS[E['a2']] = 500
        for _ in range(4):
            executer(lambda: diffuser_compteurs_admin([admin], True, push=('T', 'C', {'canal': 'general'})))
        a = AbonnementPushWeb.objects.filter(endpoint=E['a2']).first()
        ok('4 echecs (500) : abonnement garde, nb_echecs 4', a is not None and a.nb_echecs == 4,
           getattr(a, 'nb_echecs', None))
        executer(lambda: diffuser_compteurs_admin([admin], True, push=('T', 'C', {'canal': 'general'})))
        ok('5e echec : abonnement supprime', not AbonnementPushWeb.objects.filter(endpoint=E['a2']).exists())
        ECHECS.clear()

        print('=== 5. FLAG ET CLES ===')
        abonner(admin, E['a1'])
        FLAG['actif'] = False
        executer(lambda: diffuser_compteurs_admin([admin], True, push=('T', 'C', {'canal': 'general'})))
        executer(lambda: notifier_utilisateur(p_user, 'T', 'C', data={}))
        ok('flag push_web_actif eteint : rien n est envoye', not envois_vers(E['a1'], E['p1']))
        ok('flag eteint : cle-publique actif false', req('get', URL + 'cle-publique/', admin).json()['actif'] is False)
        ok('flag eteint : test -> 400', req('post', URL + 'test/', admin).status_code == 400)
        FLAG['actif'] = True
        with override_settings(VAPID_PRIVATE_KEY=''):
            executer(lambda: diffuser_compteurs_admin([admin], True, push=('T', 'C', {'canal': 'general'})))
            ok('cle privee absente : rien n est envoye', not envois_vers(E['a1']))
            ok('cle absente : actif false', req('get', URL + 'cle-publique/', admin).json()['actif'] is False)

        print('=== 6. TEST ===')
        r = executer(lambda: req('post', URL + 'test/', admin))
        ok('test -> 202, notification de test envoyee', r.status_code == 202 and r.json()['nb_abonnements'] == 1
           and [p['notification']['title'] for _, p in envois_vers(E['a1'])] == ['Notification de test'], r.content)
        sans = utilisateur('admin', is_staff=True)
        r = req('post', URL + 'test/', sans)
        ok('test sans abonnement -> 400 message clair', r.status_code == 400
           and 'Aucun abonnement' in r.json()['message'], r.content)

        raise Rollback()
except Rollback:
    print('\nRollback effectue (rien persiste).')
except Exception:
    traceback.print_exc(file=sys.stdout)
    KO.append('exception inattendue (trace ci-dessus)')
finally:
    mock.patch.stopall()

print(f'\n=== TOTAL : {NB_OK} OK / {len(KO)} KO ===')
if KO:
    print('KO :', *KO, sep='\n - ')
    raise SystemExit(1)
