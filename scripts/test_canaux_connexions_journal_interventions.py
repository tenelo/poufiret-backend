"""Tests : notifications admin à deux canaux, connexions admin à une ligne,
journal d'audit regroupé (+ purge en simulation), centre de gestion admin
des demandes d'intervention.

Tout se déroule dans une transaction annulée (rien n'est persisté). La
purge n'est lancée qu'en SIMULATION (jamais --appliquer).

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_canaux_connexions_journal_interventions.py
"""
import importlib
import io
import json
from datetime import timedelta
from unittest import mock

from django.apps import apps as django_apps
from django.core.management import call_command
from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import ConnexionAdmin, JournalModeration, PermissionsAdmin
from apps.messaging.models import DemandeIntervention, HistoriqueIntervention, NoteAdminIntervention
from apps.moderation.models import Notification
from apps.orders.models import Commande
from apps.orders.services import _notifier_admins_commande
from apps.users.models import ProfilPartenaire, SessionAppareil, User

HOST = 'poufiret.tenelo.cloud'
NB = 0


class Rollback(Exception):
    pass


def ok(libelle, cond, detail=''):
    global NB
    print(('OK   ' if cond else 'FAIL '), libelle, '' if cond else detail)
    assert cond, f'{libelle} {detail}'
    NB += 1


def req(method, url, user=None, corps=None, **extra):
    kw = {'secure': True, 'HTTP_HOST': HOST, **extra}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    fn = getattr(Client(), method)
    if corps is not None:
        return fn(url, json.dumps(corps), content_type='application/json', **kw)
    return fn(url, **kw)


def executer_on_commit(appel):
    """Exécute les callbacks on_commit ajoutés pendant l'appel (la transaction
    de test ne se termine jamais) — même helper que test_partenaires_telephone."""
    debut = len(connection.run_on_commit)
    resultat = appel()
    nouveaux = connection.run_on_commit[debut:]
    del connection.run_on_commit[debut:]
    for _sids, fonction, _robust in nouveaux:
        fonction()
    return resultat


def admin(tel, username, superuser=False, **caps):
    u = User.objects.create(telephone=tel, username=username, role=User.Role.ADMIN,
                            is_staff=True, is_superuser=superuser, est_verifie=True)
    u.set_password('1234'); u.save()
    if not superuser:
        PermissionsAdmin.objects.create(admin=u, **caps)
    return u


def migration(module):
    return importlib.import_module(module)


try:
    with transaction.atomic():
        superadmin = admin('+22508800000', 't_c4_super', superuser=True)
        cmd_admin = admin('+22508800001', 't_c4_cmd', gerer_commandes=True)
        voir = admin('+22508800002', 't_c4_voir', voir_interventions=True)
        gerer = admin('+22508800003', 't_c4_gerer', gerer_interventions=True)
        sans = admin('+22508800004', 't_c4_sans')
        journal_admin = admin('+22508800005', 't_c4_journal', lire_journal=True)
        client = User.objects.filter(role=User.Role.CLIENT, is_active=True).first()

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 1. NOTIFICATIONS : CANAUX ET CIBLES ===')
        resto = ProfilPartenaire.objects.filter(type_partenaire='restaurateur').first()
        autre = ProfilPartenaire.objects.exclude(type_partenaire='restaurateur').first()

        def commande(partenaire):
            return Commande.objects.create(
                numero=f'PFR-C4-{Commande.objects.count() + 1:05d}', user=client,
                partenaire=partenaire, total=1000)

        c_resto, c_autre = commande(resto), commande(autre)
        _notifier_admins_commande(c_resto, 'commande_nouvelle', 'Nouvelle commande', 'resto')
        _notifier_admins_commande(c_autre, 'commande_nouvelle', 'Nouvelle commande', 'autre')
        _notifier_admins_commande(c_resto, 'commande_annulee_client', 'Commande annulée', 'resto annulee')
        n_resto = Notification.objects.get(user=cmd_admin, data__commande_id=c_resto.id, type='commande_nouvelle')
        n_autre = Notification.objects.get(user=cmd_admin, data__commande_id=c_autre.id)
        n_annul = Notification.objects.get(user=cmd_admin, type='commande_annulee_client')
        ok('commande restaurateur -> canal restaurant, cible commandes',
           n_resto.canal == 'restaurant' and n_resto.cible == {'ecran': 'commandes', 'id': c_resto.id},
           (n_resto.canal, n_resto.cible))
        ok('commande non restaurant -> general', n_autre.canal == 'general', n_autre.canal)
        ok('commande_annulee_client restaurant -> restaurant', n_annul.canal == 'restaurant')

        from apps.notifications.canaux import champs_canal
        ok('pub -> general, cible publicites',
           champs_canal('pub_a_valider', {'publicite_id': 'abc'})
           == {'canal': 'general', 'cible': {'ecran': 'publicites', 'id': 'abc'}})
        ok('demande location -> general, cible demandes_location',
           champs_canal('reservation_nouvelle', {'demande_id': 7})
           == {'canal': 'general', 'cible': {'ecran': 'demandes_location', 'id': 7}})
        ok('commande_acceptee (autre type) d\'un restaurant -> general',
           champs_canal('commande_acceptee', {'commande_id': c_resto.id}, commande=c_resto)['canal'] == 'general')

        # Catégorie de restauration sur une commande d'un partenaire non restaurateur.
        from apps.catalog.models import Categorie
        cat_resto = Categorie.objects.filter(types_partenaire__contains=['restaurateur']).first()
        if cat_resto:
            c_cat = commande(autre)
            c_cat.categorie = cat_resto
            c_cat.save(update_fields=['categorie'])
            ok('Commande.categorie Restaurants -> restaurant',
               champs_canal('commande_nouvelle', {'commande_id': c_cat.id}, commande=c_cat)['canal'] == 'restaurant')

        r = req('get', '/api/v1/notifications/admin/?canal=restaurant', cmd_admin)
        res = r.json()['results']
        ok('?canal=restaurant -> seulement restaurant', r.status_code == 200 and res
           and all(x['canal'] == 'restaurant' for x in res), res)
        ok('serializer : canal + cible exposes', {'canal', 'cible'} <= set(res[0]) and res[0]['cible']['ecran'] == 'commandes')
        r = req('get', '/api/v1/notifications/admin/?canal=general&non_lues=1', cmd_admin)
        ok('?canal=general&non_lues=1', all(x['canal'] == 'general' and not x['lue'] for x in r.json()['results']))
        ok('?canal=inconnu -> 400', req('get', '/api/v1/notifications/admin/?canal=x', cmd_admin).status_code == 400)

        attendu_r = Notification.objects.filter(user=cmd_admin, lu=False, canal='restaurant').count()
        attendu_g = Notification.objects.filter(user=cmd_admin, lu=False, canal='general').count()
        with CaptureQueriesContext(connection) as ctx:
            r = req('get', '/api/v1/notifications/admin/compteur/', cmd_admin)
        ok('compteur {restaurant, general, nb_non_lues}', r.json() == {
            'restaurant': attendu_r, 'general': attendu_g, 'nb_non_lues': attendu_r + attendu_g}, r.json())
        requetes_notif = [q for q in ctx.captured_queries if 'moderation_notification' in q['sql']]
        ok('compteur : UNE requete sur les notifications', len(requetes_notif) == 1, len(requetes_notif))

        r = req('post', '/api/v1/notifications/admin/tout-lire/?canal=restaurant', cmd_admin)
        ok('tout-lire ?canal=restaurant -> seulement ce canal',
           r.status_code == 200 and r.json()['nb_mises_a_jour'] == attendu_r
           and not Notification.objects.filter(user=cmd_admin, lu=False, canal='restaurant').exists()
           and Notification.objects.filter(user=cmd_admin, lu=False, canal='general').count() == attendu_g, r.json())
        ok('tout-lire ?canal=x -> 400',
           req('post', '/api/v1/notifications/admin/tout-lire/?canal=x', cmd_admin).status_code == 400)

        print('\n--- migration de donnees (canal/cible des notifications existantes) ---')
        ancienne = Notification.objects.create(
            user=cmd_admin, type='commande_nouvelle', titre='t', contenu='c',
            data={'commande_id': c_resto.id, 'groupe': 'a_traiter'})
        ancienne_pub = Notification.objects.create(
            user=cmd_admin, type='pub_a_valider', titre='t', contenu='c', data={'publicite_id': 'x-1'})
        ok('avant migration : general, cible null', ancienne.canal == 'general' and ancienne.cible is None)
        migration('apps.moderation.migrations.0007_notification_canal_cible').remplir(django_apps, None)
        ancienne.refresh_from_db(); ancienne_pub.refresh_from_db()
        ok('apres : restaurant + cible commandes',
           ancienne.canal == 'restaurant' and ancienne.cible == {'ecran': 'commandes', 'id': c_resto.id},
           (ancienne.canal, ancienne.cible))
        ok('apres : pub general + cible publicites', ancienne_pub.canal == 'general'
           and ancienne_pub.cible == {'ecran': 'publicites', 'id': 'x-1'})

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 2. INTERVENTION_NOUVELLE ===')
        artisan = ProfilPartenaire.objects.filter(statut='actif').exclude(type_partenaire='restaurateur').first()
        r = executer_on_commit(lambda: req('post', '/api/v1/messaging/interventions/', client, {
            'artisan': artisan.id, 'description': 'Fuite QA C4', 'urgence': 'urgent',
            'type_intervention': 'depannage_urgent'}))
        ok('creation demande (client) -> 201', r.status_code == 201, r.content)
        d1 = DemandeIntervention.objects.get(id=r.json()['id'])
        notifs = Notification.objects.filter(type='intervention_nouvelle', data__intervention_id=d1.id)
        ok('envoyee au super-admin, voir_ et gerer_interventions',
           {superadmin.id, voir.id, gerer.id} <= set(notifs.values_list('user_id', flat=True)))
        ok('pas aux admins sans droit', not notifs.filter(user__in=[sans, cmd_admin]).exists())
        n = notifs.get(user=voir)
        ok('canal general, cible interventions', n.canal == 'general'
           and n.cible == {'ecran': 'interventions', 'id': d1.id}, (n.canal, n.cible))
        ok('un seul exemplaire par destinataire (distinct)', notifs.filter(user=superadmin).count() == 1)

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 3. INTERVENTIONS ADMIN : LECTURE ===')
        B = '/api/v1/administration/interventions/'
        r = req('get', f'{B}meta/', voir)
        ok('meta (voir) -> statuts, urgences, types', r.status_code == 200
           and {'statuts', 'urgences', 'types'} <= set(r.json())
           and {'valeur', 'libelle'} <= set(r.json()['types'][0]), r.content)
        ok('meta sans droit -> 403', req('get', f'{B}meta/', sans).status_code == 403)
        r = req('get', f'{B}?urgence=urgent&type=depannage_urgent&artisan={artisan.id}&q=QA', gerer)
        d = r.json()
        ok('liste filtree (gerer implique lecture) contient d1', r.status_code == 200
           and d1.id in {x['id'] for x in d['resultats']}, r.content[:300])
        ligne = next(x for x in d['resultats'] if x['id'] == d1.id)
        ok('libelles type/urgence/statut', {'type_libelle', 'urgence_libelle', 'statut_libelle'} <= set(ligne)
           and ligne['type_libelle'] == 'Dépannage urgent', ligne)
        ok('compteurs_statut (tous statuts + total)', 'compteurs_statut' in d
           and d['compteurs_statut']['en_attente'] >= 1
           and d['compteurs_statut']['total'] == sum(v for k, v in d['compteurs_statut'].items() if k != 'total'))
        r = req('get', f'{B}?urgence=flexible&q=QA C4', voir)
        ok('filtre urgence exclut d1', d1.id not in {x['id'] for x in r.json()['resultats']})
        aujourdhui = timezone.localdate().isoformat()
        ok('filtres du/au', d1.id in {x['id'] for x in req('get', f'{B}?du={aujourdhui}&au={aujourdhui}', voir).json()['resultats']})
        ok('liste sans droit -> 403', req('get', B, sans).status_code == 403)

        r = req('get', f'{B}{d1.id}/', voir)
        det = r.json()
        ok('detail -> 200', r.status_code == 200, r.content)
        for cle in ('client', 'artisan', 'type_libelle', 'urgence_libelle', 'description', 'adresse',
                    'photos', 'historique', 'notes_admin', 'transitions_possibles'):
            ok(f'detail : {cle}', cle in det)
        ok('client/artisan : noms + telephones', {'nom', 'telephone'} <= set(det['client'])
           and {'nom', 'telephone'} <= set(det['artisan']))
        ok('transitions_possibles en_attente + commentaire_obligatoire',
           {t['action']: t['commentaire_obligatoire'] for t in det['transitions_possibles']}
           == {'acceptee': False, 'refusee': True, 'annulee': True}, det['transitions_possibles'])
        ok('detail 404', req('get', f'{B}999999999/', voir).status_code == 404)

        print('\n=== 4. INTERVENTIONS ADMIN : ECRITURES ===')
        T = f'{B}{d1.id}/transition/'
        ok('transition avec voir seulement -> 403',
           req('post', T, voir, {'action': 'acceptee'}).status_code == 403)
        ok('transition sans droit -> 403', req('post', T, sans, {'action': 'acceptee'}).status_code == 403)
        ok('annulation sans motif -> 400', req('post', T, gerer, {'action': 'annulee'}).status_code == 400)
        ok('transition invalide (terminee depuis en_attente) -> 400',
           req('post', T, gerer, {'action': 'terminee'}).status_code == 400)
        with mock.patch('apps.messaging.services.notifier_utilisateur') as notif:
            r = req('post', T, gerer, {'action': 'acceptee', 'commentaire': 'Vu par l admin'})
        ok('acceptee (gerer) -> 200', r.status_code == 200 and r.json()['statut'] == 'acceptee', r.content)
        destinataires = {appel.args[0].id for appel in notif.call_args_list}
        ok('client ET artisan notifies', {d1.user_id, artisan.user_id} <= destinataires, destinataires)
        h = HistoriqueIntervention.objects.filter(demande=d1).last()
        ok('historique : acteur, role admin, commentaire', h.acteur_id == gerer.id
           and h.acteur_role == 'admin' and h.commentaire == 'Vu par l admin')
        ok('historique expose dans le detail', r.json()['historique'][-1]['acteur_role'] == 'admin'
           and r.json()['historique'][-1]['acteur_nom'])
        d1.refresh_from_db()
        ok('acceptee_le renseignee', d1.acceptee_le is not None)
        r = req('post', T, superadmin, {'action': 'en_cours'})
        ok('super-admin -> 200', r.status_code == 200 and r.json()['statut'] == 'en_cours', r.content)

        print('--- transition artisan (flux existant) : historisee, role artisan ---')
        r = req('post', f'/api/v1/messaging/interventions/{d1.id}/transition/', artisan.user, {'statut': 'terminee'})
        ok('artisan termine -> 200 (inchange)', r.status_code == 200, r.content)
        ok('historique role artisan', HistoriqueIntervention.objects.filter(
            demande=d1, acteur_role='artisan', statut='terminee').exists())

        print('--- assigner ---')
        A = f'{B}{d1.id}/assigner/'
        ok('assigner avec voir -> 403', req('post', A, voir, {'artisan_id': artisan.id}).status_code == 403)
        compatible = ProfilPartenaire.objects.filter(statut='actif').exclude(pk=artisan.pk).exclude(
            type_partenaire=artisan.type_partenaire).first()
        incompatible = ProfilPartenaire.objects.filter(statut='actif').exclude(
            pk__in=[artisan.pk, compatible.pk]).exclude(type_partenaire=artisan.type_partenaire).first()
        compatible.type_partenaire = artisan.type_partenaire  # annulé au rollback
        compatible.save(update_fields=['type_partenaire'])
        ok('demande terminee : reassignation refusee -> 400',
           req('post', A, gerer, {'artisan_id': compatible.id}).status_code == 400)
        d2 = DemandeIntervention.objects.create(
            numero='INT-QA-C4-2', user=client, artisan=artisan, description='QA C4 bis')
        A2 = f'{B}{d2.id}/assigner/'
        r = req('get', f'{B}{d2.id}/artisans-compatibles/', gerer)
        ok('artisans-compatibles : contient le compatible, pas l\'actuel',
           compatible.id in {x['id'] for x in r.json()['resultats']}
           and artisan.id not in {x['id'] for x in r.json()['resultats']}, r.content[:200])
        if incompatible:
            ok('type incompatible -> 400', req('post', A2, gerer, {'artisan_id': incompatible.id}).status_code == 400)
        ok('meme artisan -> 400', req('post', A2, gerer, {'artisan_id': artisan.id}).status_code == 400)
        ok('artisan_id invalide -> 400', req('post', A2, gerer, {'artisan_id': 'x'}).status_code == 400)
        with mock.patch('apps.messaging.services.notifier_utilisateur') as notif:
            r = req('post', A2, gerer, {'artisan_id': compatible.id, 'commentaire': 'Plus proche'})
        d2.refresh_from_db()
        ok('assigner -> 200, artisan change, en_attente', r.status_code == 200
           and d2.artisan_id == compatible.id and d2.statut == 'en_attente', r.content)
        ok('nouvel artisan et client notifies',
           {compatible.user_id, client.id} <= {a.args[0].id for a in notif.call_args_list})
        ok('historique de reassignation (admin)', HistoriqueIntervention.objects.filter(
            demande=d2, acteur=gerer, acteur_role='admin', commentaire__contains='Réassignée').exists())
        r = req('post', f'{B}{d2.id}/transition/', gerer, {'action': 'refusee', 'commentaire': 'Indispo'})
        ok('refusee avec motif -> 200, raison_refus', r.status_code == 200 and r.json()['raison_refus'] == 'Indispo')
        r = req('post', A2, superadmin, {'artisan_id': artisan.id})
        ok('refusee -> reassignable (super-admin) -> en_attente', r.status_code == 200
           and r.json()['statut'] == 'en_attente' and r.json()['raison_refus'] == '', r.content)

        print('--- notes ---')
        N = f'{B}{d1.id}/notes/'
        ok('note avec voir -> 403', req('post', N, voir, {'texte': 'x'}).status_code == 403)
        ok('note vide -> 400', req('post', N, gerer, {'texte': '  '}).status_code == 400)
        r = req('post', N, gerer, {'texte': 'Client rappelé'})
        ok('note -> 201', r.status_code == 201 and r.json()['auteur_nom'], r.content)
        ok('note dans le detail admin', any(n['texte'] == 'Client rappelé'
                                            for n in req('get', f'{B}{d1.id}/', voir).json()['notes_admin']))
        r = req('get', f'/api/v1/messaging/interventions/{d1.id}/', client)
        ok('note invisible pour le client', r.status_code == 200 and 'notes_admin' not in r.json()
           and 'Client rappelé' not in r.content.decode())
        ok('NoteAdminIntervention creee', NoteAdminIntervention.objects.filter(demande=d1).count() == 1)

        print('--- serializer client : client_telephone ---')
        ok('detail client : client_telephone = telephone du client',
           r.json().get('client_telephone') == client.telephone, r.json().get('client_telephone'))
        r = req('get', '/api/v1/messaging/interventions/', client)
        ligne = next(x for x in r.json() if x['id'] == d1.id)
        ok('liste client : client_telephone renseigne', ligne.get('client_telephone') == client.telephone, ligne)
        r = req('get', '/api/v1/messaging/interventions/artisan/', artisan.user)
        ligne = next(x for x in r.json() if x['id'] == d1.id)
        ok('liste artisan : client_telephone renseigne', ligne.get('client_telephone') == client.telephone, ligne)

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 5. CONNEXIONS ADMIN : UNE LIGNE PAR ADMIN ===')
        lui = admin('+22508800010', 't_c4_login')
        corps = {'telephone': lui.telephone, 'password': '1234'}
        r = req('post', '/api/v1/auth/connexion/', corps=corps, HTTP_USER_AGENT='Mozilla/5.0 QA-1')
        ok('connexion admin 1 -> 200', r.status_code == 200, r.content)
        c1 = ConnexionAdmin.objects.get(admin=lui)
        ok('ligne creee : nb=1, premiere=derniere, UA', c1.nb_connexions == 1
           and c1.premiere_connexion == c1.derniere_connexion and c1.dernier_appareil == 'Mozilla/5.0 QA-1')
        r = req('post', '/api/v1/auth/connexion/', corps=corps, HTTP_USER_AGENT='Mozilla/5.0 QA-2',
                HTTP_X_FORWARDED_FOR='10.1.2.3')
        c2 = ConnexionAdmin.objects.get(admin=lui)
        ok('2e connexion : meme ligne mise a jour (nb=2, UA, IP)',
           ConnexionAdmin.objects.filter(admin=lui).count() == 1 and c2.nb_connexions == 2
           and c2.premiere_connexion == c1.premiere_connexion and c2.derniere_connexion > c1.derniere_connexion
           and c2.dernier_appareil == 'Mozilla/5.0 QA-2' and c2.derniere_ip == '10.1.2.3', vars(c2))
        ok('admin web sans appareil_id : une seule SessionAppareil',
           SessionAppareil.objects.filter(user=lui, appareil_id='').count() == 1)
        cl = User.objects.create(telephone='+22508800011', username='t_c4_client', role=User.Role.CLIENT,
                                 est_verifie=True)
        cl.set_password('1234'); cl.save()
        for _ in range(2):
            req('post', '/api/v1/auth/connexion/', corps={'telephone': cl.telephone, 'password': '1234'})
        ok('client : pas de ConnexionAdmin, sessions inchangees (1 par connexion)',
           not ConnexionAdmin.objects.filter(admin=cl).exists()
           and SessionAppareil.objects.filter(user=cl).count() == 2)

        r = req('get', '/api/v1/administration/connexions-admin/', journal_admin)
        d = r.json()
        ok('liste -> 200, une ligne par admin', r.status_code == 200
           and len({x['utilisateur_id'] for x in d['resultats']}) == len(d['resultats']), r.content[:200])
        ligne = next(x for x in d['resultats'] if x['utilisateur_id'] == lui.id)
        ok('champs historiques + nb_connexions + premiere_connexion', {
            'id', 'utilisateur_id', 'telephone', 'nom', 'is_superuser', 'date_connexion', 'adresse_ip',
            'plateforme', 'plateforme_libelle', 'appareil_nom', 'est_active', 'derniere_activite_le',
            'nb_connexions', 'premiere_connexion'} <= set(ligne) and ligne['nb_connexions'] == 2
           and ligne['est_active'] is True, ligne)
        ok('?utilisateur= filtre', [x['utilisateur_id'] for x in req(
            'get', f'/api/v1/administration/connexions-admin/?utilisateur={lui.id}', journal_admin
        ).json()['resultats']] == [lui.id])
        ok('liste sans lire_journal -> 403',
           req('get', '/api/v1/administration/connexions-admin/', sans).status_code == 403)
        r = req('get', '/api/v1/administration/connexions-admin/export/', journal_admin)
        ok('export -> 200, colonne nb_connexions', r.status_code == 200
           and 'nb_connexions' in r.content.decode('utf-8-sig').splitlines()[0])

        print('--- migration de regroupement ---')
        vieux = admin('+22508800012', 't_c4_vieux')
        maintenant = timezone.now()
        for jours, ip in ((30, '10.0.0.1'), (20, '10.0.0.2'), (10, '10.0.0.3')):
            s = SessionAppareil.objects.create(user=vieux, appareil_nom='PC', adresse_ip=ip)
            SessionAppareil.objects.filter(pk=s.pk).update(cree_le=maintenant - timedelta(days=jours))
        s = SessionAppareil.objects.create(user=vieux, appareil_id='tel-X', appareil_nom='Tel')
        SessionAppareil.objects.filter(pk=s.pk).update(cree_le=maintenant - timedelta(days=5))
        migration('apps.administration.migrations.0026_journal_regroupement_connexion_admin'
                  ).regrouper_connexions(django_apps, None)
        cv = ConnexionAdmin.objects.get(admin=vieux)
        ok('ConnexionAdmin : nb = nombre de lignes (4), premiere = la plus ancienne',
           cv.nb_connexions == 4 and abs((cv.premiere_connexion - (maintenant - timedelta(days=30))).total_seconds()) < 2,
           vars(cv))
        ok('derniere connexion conservee (la plus recente)',
           abs((cv.derniere_connexion - (maintenant - timedelta(days=5))).total_seconds()) < 2)
        ok('doublons supprimes : 1 session sans appareil_id (la plus recente) + appareil identifie garde',
           SessionAppareil.objects.filter(user=vieux, appareil_id='').count() == 1
           and SessionAppareil.objects.get(user=vieux, appareil_id='').adresse_ip == '10.0.0.3'
           and SessionAppareil.objects.filter(user=vieux, appareil_id='tel-X').exists())
        ok('une seule ligne ConnexionAdmin par admin',
           ConnexionAdmin.objects.filter(admin=vieux).count() == 1)

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 6. JOURNAL : REGROUPEMENT ET PURGE (SIMULATION) ===')
        cible = client
        e1 = JournalModeration.enregistrer(superadmin, cible, 'resto_plat_modif', 'Plat A')
        e2 = JournalModeration.enregistrer(superadmin, cible, 'resto_plat_modif', 'Plat B')
        ok('identique < 10 min -> meme ligne, occurrences=2, dernier motif',
           e1.pk == e2.pk and e2.occurrences == 2 and e2.motif == 'Plat B'
           and e2.derniere_occurrence > e1.derniere_occurrence)
        e3 = JournalModeration.enregistrer(superadmin, cible, 'resto_menu_modif', 'Menu')
        ok('autre action -> nouvelle ligne', e3.pk != e1.pk)
        e4 = JournalModeration.enregistrer(superadmin, voir, 'resto_plat_modif', 'Plat A')
        ok('autre cible -> nouvelle ligne', e4.pk != e1.pk)
        e5 = JournalModeration.enregistrer(gerer, cible, 'resto_plat_modif', 'Plat A')
        ok('autre acteur -> nouvelle ligne', e5.pk != e1.pk)
        JournalModeration.objects.filter(pk=e1.pk).update(
            derniere_occurrence=timezone.now() - timedelta(minutes=11))
        e6 = JournalModeration.enregistrer(superadmin, cible, 'resto_plat_modif', 'Plat C')
        ok('> 10 min -> nouvelle ligne', e6.pk != e1.pk and e6.occurrences == 1)
        s1 = JournalModeration.enregistrer(superadmin, None, 'cat_suppression', '« X » supprimée')
        s2 = JournalModeration.enregistrer(superadmin, None, 'cat_suppression', '« Y » supprimée')
        s3 = JournalModeration.enregistrer(superadmin, None, 'cat_suppression', '« Y » supprimée')
        ok('sans cible : motif different -> lignes distinctes, identique -> regroupe',
           s1.pk != s2.pk and s2.pk == s3.pk and s3.occurrences == 2)
        r = req('get', '/api/v1/administration/moderation/journal/', superadmin)
        ok('liste du journal : occurrences + derniere_occurrence',
           r.status_code == 200 and {'occurrences', 'derniere_occurrence'} <= set(r.json()['entrees'][0]),
           r.content[:200])

        vieille = JournalModeration.enregistrer(superadmin, voir, 'cat_creation', 'tres ancienne QA')
        il_y_a = timezone.now() - timedelta(days=400)
        JournalModeration.objects.filter(pk=vieille.pk).update(cree_le=il_y_a, derniere_occurrence=il_y_a)
        sortie = io.StringIO()
        call_command('purger_journal', '--jours=365', stdout=sortie)
        texte = sortie.getvalue()
        print(texte)
        ok('purge (simulation) : rapport, rien supprime',
           'Simulation' in texte and JournalModeration.objects.filter(pk=vieille.pk).exists(), texte)

        raise Rollback('annulation volontaire')
except Rollback as e:
    print('\nRollback effectue :', e)

ok('rien persiste', not User.objects.filter(username__startswith='t_c4_').exists()
   and not DemandeIntervention.objects.filter(description__contains='QA C4').exists())
print(f'\n=== TOTAL : {NB} verifications reussies ===')
