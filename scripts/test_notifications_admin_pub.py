"""Tests : notifications in-app admin sur soumission/paiement de pub,
destinataires, endpoints, isolation, non-blocage sur erreur.

Execution (tout est annule a la fin) :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_notifications_admin_pub.py
"""
import json
from unittest.mock import patch

from django.db import transaction
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken

from apps.moderation.models import Notification
from apps.administration.models import PermissionsAdmin
from apps.publicites.models import FormulePublicite, Publicite
from apps.publicites.services import appliquer_transition
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


def h(user):
    return {'HTTP_AUTHORIZATION': f'Bearer {AccessToken.for_user(user)}', 'HTTP_HOST': HOST}


def j(url, method, user, corps=None):
    c = Client()
    fn = getattr(c, method)
    kw = {'secure': True, **h(user)}
    if corps is not None:
        return fn(url, json.dumps(corps), content_type='application/json', **kw)
    return fn(url, **kw)


avant = Notification.objects.count()
try:
    with transaction.atomic():
        superadmin = User.objects.filter(is_superuser=True).first()
        pa = ProfilPartenaire.objects.get(id=2)
        formule = FormulePublicite.objects.get(nom='Éclair')  # quota large, marge pour le test

        admin_valide = User.objects.create(
            telephone='+22503000001', username='t_admin_valide', role=User.Role.ADMIN,
            is_staff=True, is_superuser=False, est_verifie=True)
        admin_valide.set_password('0000'); admin_valide.save()
        PermissionsAdmin.objects.create(admin=admin_valide, valider_publicite=True)

        admin_sans_droit = User.objects.create(
            telephone='+22503000002', username='t_admin_sans', role=User.Role.ADMIN,
            is_staff=True, is_superuser=False, est_verifie=True)
        admin_sans_droit.set_password('0000'); admin_sans_droit.save()
        PermissionsAdmin.objects.create(admin=admin_sans_droit, valider_publicite=False)

        admin_inactif = User.objects.create(
            telephone='+22503000003', username='t_admin_inactif', role=User.Role.ADMIN,
            is_staff=True, is_superuser=False, est_verifie=True, is_active=False)
        admin_inactif.set_password('0000'); admin_inactif.save()
        PermissionsAdmin.objects.create(admin=admin_inactif, valider_publicite=True)

        pub = Publicite.objects.create(
            partenaire=pa, formule=formule, titre='Notif Test QA', portee='departement',
            image_couverture='publicites/couvertures/x.jpg', statut='brouillon')

        print('\n=== 1. SOUMISSION -> pub_soumise ===')
        nb_avant = Notification.objects.count()
        ok_t, msg = appliquer_transition(pub, 'soumettre')
        ok('transition soumettre reussie', ok_t, msg)
        recus = Notification.objects.filter(type='pub_soumise', data__publicite_id=str(pub.id))
        ok('1 notification pour superadmin', recus.filter(user=superadmin).count() == 1)
        ok('1 notification pour admin_valide (capacite valider_publicite)',
           recus.filter(user=admin_valide).count() == 1)
        ok('AUCUNE notification pour admin_sans_droit',
           recus.filter(user=admin_sans_droit).count() == 0)
        ok('AUCUNE notification pour admin_inactif (is_active=False)',
           recus.filter(user=admin_inactif).count() == 0)
        ok('AUCUNE notification pour le partenaire (pa.user)',
           recus.filter(user=pa.user).count() == 0)
        n = recus.filter(user=admin_valide).first()
        ok('titre = « Nouvelle campagne soumise »', n.titre == 'Nouvelle campagne soumise')
        ok('message = titre — partenaire (formule)',
           n.contenu == f'Notif Test QA — {pa.nom_commerce} ({formule.nom})', n.contenu)
        ok('data.publicite_id / statut_publicite corrects',
           n.data.get('publicite_id') == str(pub.id)
           and n.data.get('statut_publicite') == 'en_attente_paiement', n.data)
        ok('au moins 2 notifications (superadmin + admin_valide) ; le total '
           'reel peut etre superieur si d\'autres admins reels ont deja '
           'valider_publicite=True en base (non maitrise par ce test)',
           recus.count() >= 2)

        print('\n=== 2. PAIEMENT CONFIRME -> pub_a_valider ===')
        ok_t, msg = appliquer_transition(pub, 'confirmer_paiement')
        ok('transition confirmer_paiement reussie', ok_t, msg)
        recus2 = Notification.objects.filter(type='pub_a_valider', data__publicite_id=str(pub.id))
        ok('au moins 2 notifications (superadmin + admin_valide)', recus2.count() >= 2, recus2.count())
        n2 = recus2.filter(user=admin_valide).first()
        ok('titre = « Campagne prête à valider »', n2.titre == 'Campagne prête à valider')
        ok('message = titre — partenaire (sans formule)',
           n2.contenu == f'Notif Test QA — {pa.nom_commerce}', n2.contenu)
        ok('statut_publicite = en_attente_validation', n2.data.get('statut_publicite') == 'en_attente_validation')

        print('\n=== 3. VALIDATION_AUTO : pas de notification "a_valider" (shortcut vers ACTIVE) ===')
        from apps.publicites.models import ParametresPublicite
        params = ParametresPublicite.obtenir()
        ancien = params.validation_auto
        params.validation_auto = True
        params.save(update_fields=['validation_auto'])
        pub2 = Publicite.objects.create(
            partenaire=pa, formule=formule, titre='Notif Test QA2', portee='departement',
            image_couverture='x.jpg', statut='en_attente_paiement')
        Notification.objects.filter(data__publicite_id=str(pub2.id)).delete()
        ok_t, msg = appliquer_transition(pub2, 'confirmer_paiement')
        ok('avec validation_auto=True, confirmer_paiement active directement', ok_t and pub2.statut == 'active', msg)
        ok('aucune notification pub_a_valider (jamais passe par en_attente_validation)',
           not Notification.objects.filter(type='pub_a_valider', data__publicite_id=str(pub2.id)).exists())
        params.validation_auto = ancien
        params.save(update_fields=['validation_auto'])

        print('\n=== 4. ENDPOINTS ===')
        c = Client()
        r = j('/api/v1/notifications/admin/compteur/', 'get', admin_valide)
        ok('compteur -> 200, nb_non_lues >= 2', r.status_code == 200 and r.json()['nb_non_lues'] >= 2, r.content)

        r = j('/api/v1/notifications/admin/', 'get', admin_valide)
        ok('liste -> 200, enveloppe paginee + nb_non_lues',
           r.status_code == 200 and 'results' in r.json() and 'nb_non_lues' in r.json(), r.content)
        ids_admin_valide = {x['id'] for x in r.json()['results']}
        ok('les notifications de la pub y figurent',
           n.id in ids_admin_valide and n2.id in ids_admin_valide)

        r = j('/api/v1/notifications/admin/?non_lues=1', 'get', admin_valide)
        ok('?non_lues=1 -> uniquement des non lues', all(not x['lue'] for x in r.json()['results']), r.content)

        r = j(f'/api/v1/notifications/admin/{n.id}/lire/', 'post', admin_valide)
        ok('lecture unitaire -> 200, lue=true', r.status_code == 200 and r.json()['lue'] is True, r.content)
        n.refresh_from_db()
        ok('persistee en base (lu=True, lu_le rempli)', n.lu is True and n.lu_le is not None)

        r = j('/api/v1/notifications/admin/tout-lire/', 'post', admin_valide)
        ok('tout-lire -> 200', r.status_code == 200, r.content)
        ok('plus aucune non lue pour admin_valide',
           Notification.objects.filter(user=admin_valide, lu=False).count() == 0)
        r = j('/api/v1/notifications/admin/compteur/', 'get', admin_valide)
        ok('compteur retombe a 0', r.json()['nb_non_lues'] == 0, r.content)

        print('\n=== 5. ISOLATION ===')
        r = j('/api/v1/notifications/admin/', 'get', superadmin)
        ids_superadmin = {x['id'] for x in r.json()['results']}
        ok('superadmin ne voit pas les notifications d\'admin_valide',
           not (ids_superadmin & {n.id, n2.id}) or n.id not in ids_superadmin, (ids_superadmin, n.id))
        r_croise = j(f'/api/v1/notifications/admin/{n.id}/lire/', 'post', admin_sans_droit)
        ok('un autre admin ne peut pas marquer lue la notif d\'un autre -> 404',
           r_croise.status_code == 404, r_croise.content)
        r = j('/api/v1/notifications/admin/', 'get', pa.user)
        ok('un partenaire (non admin) -> 403', r.status_code == 403, r.content)
        r = j('/api/v1/notifications/admin/', 'get', admin_sans_droit)
        ok('un admin sans droit de validation voit quand meme SES PROPRES notifs (liste generale ouverte a tout staff)',
           r.status_code == 200, r.content)

        print('\n=== 6. ERREUR DE NOTIFICATION NE BLOQUE PAS LA TRANSITION ===')
        pub3 = Publicite.objects.create(
            partenaire=pa, formule=formule, titre='Notif Test QA3', portee='departement',
            image_couverture='x.jpg', statut='brouillon')
        with patch('apps.publicites.services.Notification' if False else
                   'apps.moderation.models.Notification.objects.bulk_create',
                   side_effect=Exception('panne simulee')):
            ok_t, msg = appliquer_transition(pub3, 'soumettre')
        ok('transition reussit MALGRE l\'echec de la notification', ok_t and pub3.statut == 'en_attente_paiement', msg)
        ok('aucune notification creee pour cette pub (echec propre)',
           not Notification.objects.filter(data__publicite_id=str(pub3.id)).exists())

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback('annulation volontaire')
except Rollback as e:
    print('Rollback effectue :', e)

assert Notification.objects.count() == avant, 'des notifications ont persiste !'
print(f'Aucune donnee persistee (notifications : {avant} avant/apres).')
