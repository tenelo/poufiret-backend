"""Tests : demandes d'intervention — capacités voir_interventions (lecture)
et gerer_interventions (écriture, implique la lecture, privilégiée).

Constat : côté admin, seuls existent la liste et l'export (lecture). Les
écritures (/messaging/interventions/<id>/transition/ et photos/) sont des
flux client/artisan, NON modifiés : un admin n'y a pas accès (non-régression).

Tout se déroule dans une transaction annulée (rien n'est persisté).

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_interventions_admin.py
"""
import json

from django.db import transaction
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import PermissionsAdmin
from apps.administration.views import CAPACITES_PRIVILEGIEES, _filtrer_anti_escalade
from apps.messaging.models import DemandeIntervention
from apps.users.models import ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
NB = 0


class Rollback(Exception):
    pass


def ok(libelle, cond, detail=''):
    global NB
    print(('OK   ' if cond else 'FAIL '), libelle, '' if cond else detail)
    assert cond, f'{libelle} {detail}'
    NB += 1


def j(url, user, method='get', corps=None):
    kw = {'secure': True, 'HTTP_AUTHORIZATION': f'Bearer {AccessToken.for_user(user)}',
          'HTTP_HOST': HOST}
    fn = getattr(Client(), method)
    if corps is not None:
        return fn(url, json.dumps(corps), content_type='application/json', **kw)
    return fn(url, **kw)


def creer_admin(tel, username, **caps):
    u = User.objects.create(telephone=tel, username=username, role=User.Role.ADMIN,
                            is_staff=True, is_superuser=False, est_verifie=True)
    u.set_password('0000'); u.save()
    PermissionsAdmin.objects.create(admin=u, **caps)
    return u


LISTE = '/api/v1/administration/interventions/'
EXPORT = '/api/v1/administration/interventions/export/'

try:
    with transaction.atomic():
        superadmin = User.objects.filter(is_superuser=True).first()
        sans = creer_admin('+22504100001', 't_int_sans')
        voir = creer_admin('+22504100002', 't_int_voir', voir_interventions=True)
        gerer = creer_admin('+22504100003', 't_int_gerer', gerer_interventions=True)
        gestionnaire = creer_admin('+22504100004', 't_int_gest', gerer_admins=True)

        print('\n=== 1. CAPACITE ===')
        ok('champ gerer_interventions existe (defaut False)',
           PermissionsAdmin._meta.get_field('gerer_interventions').default is False)
        ok('gerer_interventions dans CAPACITES_PRIVILEGIEES', 'gerer_interventions' in CAPACITES_PRIVILEGIEES)
        ok('voir_interventions reste non privilegiee', 'voir_interventions' not in CAPACITES_PRIVILEGIEES)

        print('\n=== 2. LECTURE : liste + export ===')
        for url in (LISTE, EXPORT):
            ok(f'{url} sans droit -> 403', j(url, sans).status_code == 403)
            ok(f'{url} voir_interventions -> 200', j(url, voir).status_code == 200)
            ok(f'{url} gerer_interventions (implique lecture) -> 200', j(url, gerer).status_code == 200)
            ok(f'{url} super-admin -> 200', j(url, superadmin).status_code == 200)
            pa = ProfilPartenaire.objects.first()
            ok(f'{url} partenaire -> 403', pa is None or j(url, pa.user).status_code == 403)
        r = j(LISTE, voir)
        ok('liste : format inchange (total, resultats)', {'total', 'resultats'} <= set(r.json()), r.json().keys())

        print('\n=== 3. ECRITURES : flux client/artisan inchanges ===')
        d = DemandeIntervention.objects.filter(statut='en_attente').first()
        if d is not None:
            r = j(f'/api/v1/messaging/interventions/{d.id}/transition/', gerer, 'post', {'statut': 'annulee'})
            ok('admin (meme gerer_interventions) hors client/artisan -> 403 (inchange)', r.status_code == 403, r.content)
            d.refresh_from_db()
            ok('statut non modifie', d.statut == 'en_attente')
        else:
            print('(aucune demande en_attente : verification transition ignoree)')

        print('\n=== 4. MES-PERMISSIONS ===')
        for u, attendu in ((gerer, True), (voir, False), (sans, False), (superadmin, True)):
            caps = j('/api/v1/administration/mes-permissions/', u).json()['capacites']
            ok(f'{u.username} : gerer_interventions={attendu}', caps.get('gerer_interventions') is attendu, caps)

        print('\n=== 5. ANTI-ESCALADE ===')
        f = _filtrer_anti_escalade({'gerer_interventions': True, 'voir_interventions': True}, gestionnaire)
        ok('non-superadmin : gerer_interventions retire, voir_interventions garde',
           'gerer_interventions' not in f and f.get('voir_interventions') is True, f)
        ok('superadmin : conserve', _filtrer_anti_escalade({'gerer_interventions': True}, superadmin)
           .get('gerer_interventions') is True)
        r = j(f'/api/v1/administration/admins/{sans.id}/', gestionnaire, 'patch',
              {'capacites': {'gerer_interventions': True, 'voir_interventions': True}})
        ok('PATCH par gestionnaire -> 200', r.status_code == 200, r.content)
        sans.permissions_admin.refresh_from_db()
        ok('... gerer_interventions NON accorde, voir_interventions accorde',
           sans.permissions_admin.gerer_interventions is False
           and sans.permissions_admin.voir_interventions is True)
        r = j(f'/api/v1/administration/admins/{voir.id}/', superadmin, 'patch',
              {'capacites': {'gerer_interventions': True}})
        voir.permissions_admin.refresh_from_db()
        ok('PATCH par super-admin -> gerer_interventions accorde',
           r.status_code == 200 and voir.permissions_admin.gerer_interventions is True, r.content)

        raise Rollback('annulation volontaire')
except Rollback as e:
    print('\nRollback effectue :', e)

ok('rien persiste', not User.objects.filter(username__startswith='t_int_').exists())
print(f'\n=== TOTAL : {NB} verifications reussies ===')
