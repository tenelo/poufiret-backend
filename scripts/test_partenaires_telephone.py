"""Tests : changement du numéro de connexion d'un partenaire par l'admin.
Droits (capacité modifier_identifiant_partenaire, super-admin, anti-escalade),
formats et erreurs (400/409), cible non partenaire, effets (ancien numéro
refusé, nouveau accepté avec le même PIN, anciens refresh tokens refusés,
sessions désactivées), aussi_telephone_pro, notification, journal, historique.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_partenaires_telephone.py
"""
import json
from django.db import transaction
from unittest import mock

from django.db import connection
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken
from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.administration.views import _filtrer_anti_escalade
from apps.administration.views_telephone import normaliser_telephone_ci
from apps.moderation.models import Notification
from apps.users.models import NumeroVerifie, PlanAbonnement, ProfilPartenaire, SessionAppareil, User

HOST = 'poufiret.tenelo.cloud'
class Rollback(Exception): pass
NB = 0
def ok(l, c, d=''):
    global NB
    print(('OK   ' if c else 'FAIL '), l, '' if c else d)
    assert c, f'{l} {d}'
    NB += 1

def post(url, corps, user=None):
    kw = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    return Client().post(url, json.dumps(corps), content_type='application/json', **kw)

def executer_on_commit(appel):
    """Équivalent de captureOnCommitCallbacks(execute=True) hors TestCase : la
    transaction de test ne se termine jamais, donc on exécute ici les callbacks
    ajoutés pendant l'appel (un savepoint annulé les retire de la liste)."""
    debut = len(connection.run_on_commit)
    resultat = appel()
    nouveaux = connection.run_on_commit[debut:]
    del connection.run_on_commit[debut:]
    for _sids, fonction, _robust in nouveaux:
        fonction()
    return resultat


def post_valide(url, corps, user):
    return executer_on_commit(lambda: post(url, corps, user))


def get(url, user):
    return Client().get(url, secure=True, HTTP_HOST=HOST,
                        HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')

def connexion(tel, pin, appareil_id=''):
    corps = {'telephone': tel, 'password': pin}
    if appareil_id:
        corps['appareil_id'] = appareil_id
    return post('/api/v1/auth/connexion/', corps)

def utilisateur(tel, username, role, staff=False, superuser=False):
    u = User.objects.create(telephone=tel, username=username, role=role, est_verifie=True,
                            is_staff=staff, is_superuser=superuser)
    u.set_password('1234'); u.save()
    return u

ANCIEN = '+2250711111111'
NOUVEAU = '+2250777782290'

try:
    with transaction.atomic():
        ok('pre-requis : numeros de test libres',
           not User.objects.filter(telephone__in=[ANCIEN, NOUVEAU, '+2250722222222']).exists())

        print('=== 0. NORMALISATION (unitaire) ===')
        ok('0777782290 -> +2250777782290', normaliser_telephone_ci('0777782290') == NOUVEAU)
        ok('+2250777782290 accepte tel quel', normaliser_telephone_ci('+2250777782290') == NOUVEAU)
        ok('espaces tolérés', normaliser_telephone_ci('07 77 78 22 90') == NOUVEAU)
        ok('trop court refuse', normaliser_telephone_ci('077778229') is None)
        ok('etranger refuse', normaliser_telephone_ci('+33612345678') is None)
        ok('lettres refusees', normaliser_telephone_ci('abcdefghij') is None)

        plan = PlanAbonnement.objects.get(libelle='Basique')
        partenaire_user = utilisateur(ANCIEN, 't_chg_part', 'partenaire')
        profil = ProfilPartenaire.objects.create(user=partenaire_user, plan=plan,
            nom_commerce='Partenaire CHG QA', type_partenaire='commercant',
            telephone_pro='0700000000', whatsapp=ANCIEN)
        NumeroVerifie.objects.create(telephone=ANCIEN, source='otp')
        autre = utilisateur('+2250722222222', 't_chg_autre', 'client')
        sans_capacite = utilisateur('+2250733333333', 't_chg_sans', 'admin', staff=True)
        PermissionsAdmin.objects.create(admin=sans_capacite)
        avec = utilisateur('+2250744444444', 't_chg_avec', 'admin', staff=True)
        PermissionsAdmin.objects.create(admin=avec, modifier_identifiant_partenaire=True)
        superadmin = utilisateur('+2250755555555', 't_chg_super', 'admin', staff=True, superuser=True)
        admin_non_partenaire = utilisateur('+2250766666666', 't_chg_staffprof', 'admin', staff=True)
        profil_staff = ProfilPartenaire.objects.create(user=admin_non_partenaire, plan=plan,
            nom_commerce='Staff prof QA', type_partenaire='commercant')
        url = f'/api/v1/administration/partenaires/{profil.id}/changer-telephone/'
        hist = f'/api/v1/administration/partenaires/{profil.id}/historique-telephone/'

        print('=== 1. DROITS ===')
        r = post(url, {'nouveau_telephone': NOUVEAU, 'motif': 'test'}, sans_capacite)
        ok('admin sans capacite -> 403', r.status_code == 403, r.content)
        r = post(url, {'nouveau_telephone': NOUVEAU, 'motif': 'test'}, None)
        ok('anonyme -> 401/403', r.status_code in (401, 403), r.status_code)
        ok('anti-escalade : non super-admin ne peut pas poser la capacite',
           'modifier_identifiant_partenaire' not in _filtrer_anti_escalade(
               {'modifier_identifiant_partenaire': True, 'gerer_commandes': True}, avec))
        ok('anti-escalade : super-admin la pose',
           _filtrer_anti_escalade({'modifier_identifiant_partenaire': True}, superadmin)
           == {'modifier_identifiant_partenaire': True})

        print('=== 2. FORMATS ET CHAMPS OBLIGATOIRES (rien ne change) ===')
        r = post(url, {'nouveau_telephone': '077778229', 'motif': 'x'}, avec)
        ok('format invalide -> 400 details.nouveau_telephone',
           r.status_code == 400 and 'nouveau_telephone' in r.json()['details'], r.content)
        r = post(url, {'nouveau_telephone': '+33612345678', 'motif': 'x'}, avec)
        ok('etranger -> 400', r.status_code == 400, r.content)
        r = post(url, {'nouveau_telephone': NOUVEAU}, avec)
        ok('motif manquant -> 400 details.motif',
           r.status_code == 400 and 'motif' in r.json()['details'], r.content)
        r = post(url, {'nouveau_telephone': NOUVEAU, 'motif': '   '}, avec)
        ok('motif blanc -> 400', r.status_code == 400, r.content)
        partenaire_user.refresh_from_db()
        ok('aucun changement apres les rejets', partenaire_user.telephone == ANCIEN)

        print('=== 3. IDENTIQUE ET DEJA PRIS ===')
        r = post(url, {'nouveau_telephone': ANCIEN, 'motif': 'x'}, avec)
        ok('identique (meme format) -> 400', r.status_code == 400, r.content)
        r = post(url, {'nouveau_telephone': '0711111111', 'motif': 'x'}, avec)
        ok('identique (format local) -> 400', r.status_code == 400, r.content)
        r = post(url, {'nouveau_telephone': '0722222222', 'motif': 'x'}, avec)
        ok('numero deja pris par un autre compte -> 409',
           r.status_code == 409 and r.json()['message'] == 'Ce numéro est déjà utilisé par un autre compte.', r.content)

        print('=== 4. CIBLE NON PARTENAIRE ===')
        r = post(f'/api/v1/administration/partenaires/{profil_staff.id}/changer-telephone/',
                 {'nouveau_telephone': NOUVEAU, 'motif': 'x'}, superadmin)
        ok('cible admin (staff) -> 400', r.status_code == 400, r.content)
        r = post('/api/v1/administration/partenaires/999999/changer-telephone/',
                 {'nouveau_telephone': NOUVEAU, 'motif': 'x'}, superadmin)
        ok('partenaire inconnu -> 404', r.status_code == 404, r.content)

        print('=== 5. SESSIONS ET REFRESH AVANT CHANGEMENT ===')
        r = connexion(ANCIEN, '1234', 'device-A')
        ok('connexion ancien numero + PIN -> 200', r.status_code == 200, r.content)
        refresh_ancien = r.json()['refresh']
        ok('session appareil active avant', SessionAppareil.objects.filter(
            user=partenaire_user, est_active=True).exists())

        print('=== 6. CHANGEMENT PAR ADMIN AVEC CAPACITE ===')
        r = post_valide(url, {'nouveau_telephone': '0777782290', 'motif': 'Nouveau numero confirme par le partenaire'}, avec)
        ok('admin avec capacite -> 200', r.status_code == 200, r.content)
        corps = r.json()
        ok('reponse : id, telephone, message',
           corps['id'] == profil.id and corps['telephone'] == NOUVEAU and 'déconnecté' in corps['message'], corps)
        ok('telephone_pro inchange (aussi=false)', corps['telephone_pro'] == '0700000000')
        ok('whatsapp inchange (aussi=false)', corps['whatsapp'] == ANCIEN)

        print('=== 7. EFFETS : connexion, PIN, refresh, sessions ===')
        partenaire_user.refresh_from_db()
        ok('User.telephone mis a jour', partenaire_user.telephone == NOUVEAU)
        ok('ancien numero refuse a la connexion', connexion(ANCIEN, '1234').status_code == 401)
        r = connexion(NOUVEAU, '1234')
        ok('nouveau numero + meme PIN -> 200', r.status_code == 200, r.content)
        ok('ancien refresh token refuse', post('/api/v1/auth/rafraichir/', {'refresh': refresh_ancien}).status_code == 401)
        ok('session de l appareil connecte avant le changement desactivee',
           not SessionAppareil.objects.get(user=partenaire_user, appareil_id='device-A').est_active)
        ok('NumeroVerifie du nouveau numero : source admin',
           NumeroVerifie.objects.filter(telephone=NOUVEAU, source='admin').exists())
        ok('PIN inchange', partenaire_user.check_password('1234'))

        print('=== 8. NOTIFICATION ET JOURNAL ===')
        notif = Notification.objects.filter(user=partenaire_user,
                                            type=Notification.Type.COMPTE_TELEPHONE_MODIFIE).first()
        ok('notification in-app creee', notif is not None)
        ok('contenu cite le nouveau numero et le PIN habituel',
           notif and NOUVEAU in notif.contenu and 'PIN habituel' in notif.contenu, notif and notif.contenu)
        entree = JournalModeration.objects.filter(
            cible=partenaire_user, action=JournalModeration.Action.PARTENAIRE_TELEPHONE_MODIF).first()
        ok('journal partenaire_telephone_modif cree', entree is not None)
        ok('journal : motif ancien → nouveau — motif',
           entree and entree.motif == f'{ANCIEN} → {NOUVEAU} — Nouveau numero confirme par le partenaire',
           entree and entree.motif)
        ok('journal : acteur = admin', entree and entree.acteur_id == avec.id)

        print('=== 9. HISTORIQUE ===')
        r = get(hist, avec)
        ok('historique -> 200', r.status_code == 200, r.content)
        res = r.json()['resultats']
        ok('historique : ancien/nouveau/motif/auteur_nom/cree_le',
           res and res[0]['ancien'] == ANCIEN and res[0]['nouveau'] == NOUVEAU
           and res[0]['motif'] == 'Nouveau numero confirme par le partenaire'
           and res[0]['auteur_nom'] == 't_chg_avec' and res[0]['cree_le'], res[:1])
        ok('historique : droit requis (sans capacite -> 403)',
           get(hist, sans_capacite).status_code == 403)

        print('=== 10. SUPER-ADMIN + aussi_telephone_pro + whatsapp distinct ===')
        partenaire_user.refresh_from_db()
        profil.refresh_from_db()
        profil.whatsapp = '+2250700009999'  # distinct : ne doit pas suivre le changement
        profil.save(update_fields=['whatsapp'])
        r = post_valide(url, {'nouveau_telephone': '0788889999', 'motif': 'Changement global',
                       'aussi_telephone_pro': True}, superadmin)
        ok('super-admin -> 200', r.status_code == 200, r.content)
        profil.refresh_from_db()
        ok('aussi_telephone_pro : telephone_pro = nouveau', profil.telephone_pro == '+2250788889999', profil.telephone_pro)
        ok('whatsapp distinct conserve', profil.whatsapp == '+2250700009999', profil.whatsapp)

        profil.whatsapp = '+2250788889999'  # egal au numero courant avant le changement
        profil.save(update_fields=['whatsapp'])
        r = post_valide(url, {'nouveau_telephone': '0799990000', 'motif': 'whatsapp suit', 'aussi_telephone_pro': True}, superadmin)
        profil.refresh_from_db()
        ok('whatsapp egal a l ancien numero -> suit le changement',
           r.status_code == 200 and profil.whatsapp == '+2250799990000', profil.whatsapp)

        r = get(hist, superadmin)
        ok('historique : 3 entrees, la plus recente d abord',
           len(r.json()['resultats']) == 3 and r.json()['resultats'][0]['nouveau'] == '+2250799990000',
           [x['nouveau'] for x in r.json()['resultats']])

        print('=== 11. ECHEC APRES VALIDATION : aucune notification ===')
        avant = Notification.objects.filter(user=partenaire_user).count()
        tel_avant = User.objects.get(pk=partenaire_user.pk).telephone
        def tentative():
            try:
                Client(raise_request_exception=True).post(
                    url, json.dumps({'nouveau_telephone': '0700001111', 'motif': 'echec'}),
                    content_type='application/json', secure=True, HTTP_HOST=HOST,
                    HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(superadmin)}')
            except RuntimeError:
                pass
        with mock.patch('apps.administration.views_telephone._journaliser', side_effect=RuntimeError('panne')):
            executer_on_commit(tentative)
        partenaire_user.refresh_from_db()
        ok('echec : telephone inchange (rollback)', partenaire_user.telephone == tel_avant, partenaire_user.telephone)
        ok('echec : aucune notification creee',
           Notification.objects.filter(user=partenaire_user).count() == avant)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
