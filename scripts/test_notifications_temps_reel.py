"""Tests : notifications admin en temps réel (WebSocket ws/notifications/admin/).

- connexion refusée sans jeton (4001) et pour un non-admin (4003) ;
- compteurs envoyés à la connexion (nouvelle: false) ;
- « nouvelle: true » à la création (vrai site bulk_create : notification
  admin de commande) ;
- « nouvelle: false » après lire et tout-lire (endpoints REST, réponses inchangées) ;
- isolation entre deux admins ;
- action métier réussie même si la diffusion échoue (erreur journalisée).

Couche de canaux EN MÉMOIRE (pas de Redis), données propres, transaction
annulée (rien ne persiste), limitation de débit désactivée. on_commit des
actions exécuté via captureOnCommitCallbacks (la transaction du test n'est
jamais validée). Total OK / KO.
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_notifications_temps_reel.py
"""
import uuid
from unittest import mock

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.layers import channel_layers
from channels.testing import WebsocketCommunicator
from django.db import transaction
from django.test import Client, TestCase, override_settings
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import PermissionsAdmin
from apps.moderation.models import Notification
from apps.notifications.temps_reel import compteurs_admin, diffuser_compteurs_admin
from apps.orders.models import Commande
from apps.orders.services import _notifier_admins_commande
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
# Limitation de débit DRF désactivée pour ce script : sinon tous les scripts partagent
# le compteur anonyme (60/min, client de test = 127.0.0.1) et la suite complète reçoit des 429.
from unittest import mock as _mock_debit
from rest_framework.views import APIView as _APIViewDebit
_mock_debit.patch.object(_APIViewDebit, 'get_throttles', return_value=[]).start()

# Couche de canaux en mémoire pour ce script (Redis non sollicité).
_couche = override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
_couche.enable()
channel_layers.backends.clear()
# Channels ferme les connexions « obsolètes » autour de chaque accès base d'un
# consumer : dans la transaction du test, cela fermerait la connexion. Neutralisé ici.
mock.patch('channels.db.close_old_connections', lambda: None).start()

from poufiret_backend.asgi import application  # noqa: E402  (après la configuration ci-dessus)


class Rollback(Exception):
    pass


NB_OK, KO = 0, []
CLES = {'type', 'restaurant', 'general', 'nb_non_lues', 'nouvelle'}


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


def utilisateur(role='client', **kw):
    return User.objects.create(telephone=telephone_libre(), username=f't_ntr_{uuid.uuid4().hex[:8]}',
                               role=role, est_verifie=True, **kw)


def communicateur(user=None):
    url = '/ws/notifications/admin/'
    if user is not None:
        url += f'?token={AccessToken.for_user(user)}'
    return WebsocketCommunicator(application, url, headers=[
        (b'origin', f'https://{HOST}'.encode()), (b'host', HOST.encode())])


def apres_commit(fn):
    """Exécute fn (sync) en déclenchant ses callbacks on_commit, depuis l'async."""
    def executer():
        with TestCase.captureOnCommitCallbacks(execute=True):
            return fn()
    return database_sync_to_async(executer)()


def poster(user, url):
    def appel():
        return Client().post(url, secure=True, HTTP_HOST=HOST,
                             HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
    return apres_commit(appel)


def compter(user):
    return database_sync_to_async(compteurs_admin)(user)


async def scenario(d):
    A, B, client = d['A'], d['B'], d['client']

    print('=== 1. REFUS ===')
    c = communicateur()
    connecte, code = await c.connect()
    ok('sans jeton -> refus 4001', (connecte, code) == (False, 4001), (connecte, code))
    c = communicateur(client)
    connecte, code = await c.connect()
    ok('compte non admin -> refus 4003', (connecte, code) == (False, 4003), (connecte, code))

    print('=== 2. CONNEXION : COMPTEURS ===')
    ca, cb = communicateur(A), communicateur(B)
    ok('admin A connecte', (await ca.connect())[0])
    ok('admin B connecte', (await cb.connect())[0])
    m = await ca.receive_json_from(timeout=3)
    ok('A : compteurs a la connexion (1 restaurant + 1 general, nouvelle false)',
       m == {'type': 'compteurs', 'restaurant': 1, 'general': 1, 'nb_non_lues': 2, 'nouvelle': False}, m)
    m = await cb.receive_json_from(timeout=3)
    ok('B : compteurs a la connexion (0)', m == {'type': 'compteurs', 'restaurant': 0, 'general': 0,
                                                  'nb_non_lues': 0, 'nouvelle': False}, m)
    ok('REST compteur inchange (meme calcul)', await compter(A) == {'restaurant': 1, 'general': 1, 'nb_non_lues': 2})

    print('=== 3. CREATION (bulk_create) ===')
    await apres_commit(lambda: _notifier_admins_commande(d['commande'], 'commande_nouvelle', 'Nouvelle commande', 'QA'))
    m = await ca.receive_json_from(timeout=3)
    attendu = {'type': 'compteurs', **(await compter(A)), 'nouvelle': True}
    ok('A (super-admin) : nouvelle true, compteurs a jour (3)', m == attendu and m['nb_non_lues'] == 3, (m, attendu))
    ok('message : cles exactes', set(m) == CLES, set(m))
    ok('isolation : B (sans gerer_commandes) ne recoit rien', await cb.receive_nothing(timeout=0.5))

    def notif_pour_b():
        Notification.objects.create(user=B, type='systeme', titre='Pour B', contenu='QA', canal='general')
        diffuser_compteurs_admin([B], nouvelle=True)
    await apres_commit(notif_pour_b)
    m = await cb.receive_json_from(timeout=3)
    ok('B : sa notification (nouvelle true, 1 general)', m == {'type': 'compteurs', 'restaurant': 0, 'general': 1,
                                                                'nb_non_lues': 1, 'nouvelle': True}, m)
    ok('isolation : A ne recoit rien', await ca.receive_nothing(timeout=0.5))
    ok('un non-admin est ignore par la diffusion', await database_sync_to_async(
        lambda: diffuser_compteurs_admin([client], nouvelle=True))() is None and await ca.receive_nothing(timeout=0.3))

    print('=== 4. LIRE / TOUT-LIRE ===')
    r = await poster(A, f'/api/v1/notifications/admin/{d["notif_resto"].id}/lire/')
    ok('lire -> 200 (reponse REST inchangee)', r.status_code == 200 and r.json()['lue'] is True, r.content[:200])
    m = await ca.receive_json_from(timeout=3)
    ok('A : nouvelle false apres lire, compteurs a jour (2)',
       m['nouvelle'] is False and m['nb_non_lues'] == 2 and m == {'type': 'compteurs', **(await compter(A)),
                                                                  'nouvelle': False}, m)
    ok('lire une notification deja lue : pas de message', (await poster(
        A, f'/api/v1/notifications/admin/{d["notif_resto"].id}/lire/')).status_code == 200
       and await ca.receive_nothing(timeout=0.3))
    r = await poster(A, '/api/v1/notifications/admin/tout-lire/')
    ok('tout-lire -> 200 (reponse inchangee)', r.status_code == 200 and r.json()['nb_non_lues'] == 0, r.content[:200])
    m = await ca.receive_json_from(timeout=3)
    ok('A : nouvelle false apres tout-lire, 0', m == {'type': 'compteurs', 'restaurant': 0, 'general': 0,
                                                       'nb_non_lues': 0, 'nouvelle': False}, m)
    ok('tout-lire sans rien a lire : pas de message',
       (await poster(A, '/api/v1/notifications/admin/tout-lire/')).status_code == 200
       and await ca.receive_nothing(timeout=0.3))
    ok('isolation : B ne recoit rien des lectures de A', await cb.receive_nothing(timeout=0.3))

    print('=== 5. DIFFUSION EN ECHEC ===')
    notif_b = await database_sync_to_async(lambda: Notification.objects.get(user=B, titre='Pour B'))()
    with mock.patch('channels.layers.get_channel_layer', side_effect=RuntimeError('Redis indisponible')), \
            mock.patch('apps.notifications.temps_reel.logger') as journal:
        r = await poster(B, f'/api/v1/notifications/admin/{notif_b.id}/lire/')
        ok('lire reussit malgre la diffusion en echec', r.status_code == 200 and r.json()['lue'] is True, r.content[:200])
        ok('   notification bien marquee lue', await database_sync_to_async(
            lambda: Notification.objects.get(pk=notif_b.pk).lu)())
        ok('   echec journalise', journal.exception.called)
        avant = await database_sync_to_async(lambda: Notification.objects.filter(user=A).count())()
        await apres_commit(lambda: _notifier_admins_commande(d['commande'], 'commande_nouvelle', 'Encore', 'QA'))
        apres = await database_sync_to_async(lambda: Notification.objects.filter(user=A).count())()
        ok('creation de notifications reussie malgre la diffusion en echec', apres == avant + 1, (avant, apres))
    ok('aucun message envoye pendant la panne', await cb.receive_nothing(timeout=0.3)
       and await ca.receive_nothing(timeout=0.3))

    await ca.disconnect()
    await cb.disconnect()


try:
    with transaction.atomic():
        plan = PlanAbonnement.objects.get(libelle='Basique')
        A = utilisateur('admin', is_staff=True, is_superuser=True)
        B = utilisateur('admin', is_staff=True)
        PermissionsAdmin.objects.create(admin=B, gerer_reservations=True)
        client = utilisateur()
        partenaire = ProfilPartenaire.objects.create(
            user=utilisateur('partenaire'), plan=plan, nom_commerce=f'Boutique NTR {uuid.uuid4().hex[:6]}',
            type_partenaire='commercant', statut='actif', est_visible=True)
        commande = Commande.objects.create(numero=f'PFR-NTR-{uuid.uuid4().hex[:10]}', user=client,
                                           partenaire=partenaire, total=1000)
        notif_resto = Notification.objects.create(user=A, type='systeme', titre='R', contenu='QA', canal='restaurant')
        Notification.objects.create(user=A, type='systeme', titre='G', contenu='QA', canal='general')
        async_to_sync(scenario)({'A': A, 'B': B, 'client': client, 'commande': commande,
                                 'notif_resto': notif_resto})
        raise Rollback()
except Rollback:
    print('\nRollback effectue (rien persiste).')
finally:
    _couche.disable()
    channel_layers.backends.clear()

print(f'\n=== TOTAL : {NB_OK} OK / {len(KO)} KO ===')
if KO:
    print('KO :', *KO, sep='\n - ')
    raise SystemExit(1)
