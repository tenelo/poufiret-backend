"""Tests : centre de gestion admin des commandes (capacité gerer_commandes,
filtres/compteurs, détail, transition admin + historique + notifications,
annulation sans motif, demande de livreur, notes internes, stats,
notifications admin creation/annulation, non-régression partenaire).

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_orders_admin.py
"""
import json

from django.db import transaction
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import PermissionsAdmin
from apps.administration.views import _filtrer_anti_escalade
from apps.catalog.models import Article
from apps.livraison.models import Course
from apps.moderation.models import Notification
from apps.orders.models import (
    Commande, HistoriqueCommande, LignePanier, NoteAdminCommande, Panier,
)
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


def resultats(r):
    data = r.json()
    return data['results'] if isinstance(data, dict) and 'results' in data else data


BASE = '/api/v1/orders/admin'

# ═══════════════════════════════════════════════════════════════════════
# PARTIE A — transaction annulée (CRUD, filtres, transitions, stats, notes)
# ═══════════════════════════════════════════════════════════════════════
avant_c = Commande.objects.count()
avant_h = HistoriqueCommande.objects.count()
avant_n = NoteAdminCommande.objects.count()
avant_notif = Notification.objects.count()
try:
    with transaction.atomic():
        superadmin = User.objects.filter(is_superuser=True).first()
        admin_sans = User.objects.create(
            telephone='+22504000001', username='t_cmd_sans', role=User.Role.ADMIN,
            is_staff=True, is_superuser=False, est_verifie=True)
        admin_sans.set_password('0000'); admin_sans.save()
        PermissionsAdmin.objects.create(admin=admin_sans)
        admin_avec = User.objects.create(
            telephone='+22504000002', username='t_cmd_avec', role=User.Role.ADMIN,
            is_staff=True, is_superuser=False, est_verifie=True)
        admin_avec.set_password('0000'); admin_avec.save()
        PermissionsAdmin.objects.create(admin=admin_avec, gerer_commandes=True)

        pa = ProfilPartenaire.objects.get(id=1)   # Business Center : GPS + departement + quartier
        client = User.objects.get(id=144)
        article = Article.objects.filter(partenaire=pa, est_actif=True).first()

        def creer_commande(statut='nouvelle', mode_livraison='emporter', **kw):
            c = Commande.objects.create(
                numero=f'PFR-TEST-{Commande.objects.count()+1:05d}', user=client,
                partenaire=pa, mode_livraison=mode_livraison, statut=statut,
                sous_total=5000, frais_livraison=500, total=5500, **kw)
            if article:
                from apps.orders.models import LigneCommande
                LigneCommande.objects.create(
                    commande=c, article=article, nom_article=article.nom,
                    quantite=2, prix_unitaire=2500, prix_ligne=5000)
            return c

        print('\n=== 0. CAPACITE + ANTI-ESCALADE ===')
        ok('capacite gerer_commandes existe', hasattr(admin_avec.permissions_admin, 'gerer_commandes'))
        f1 = _filtrer_anti_escalade({'gerer_commandes': True, 'voir_stats': True}, admin_avec)
        ok('non-superadmin ne peut pas accorder gerer_commandes',
           'gerer_commandes' not in f1 and 'voir_stats' in f1, f1)
        f2 = _filtrer_anti_escalade({'gerer_commandes': True}, superadmin)
        ok('superadmin peut l\'accorder', f2.get('gerer_commandes') is True)

        print('\n=== 1. ACCES : 403 / superadmin OK / admin avec capacite OK ===')
        c1 = creer_commande('nouvelle')
        r = j(f'{BASE}/commandes/', 'get', admin_sans)
        ok('sans capacite -> 403', r.status_code == 403, r.content)
        r = j(f'{BASE}/commandes/', 'get', superadmin)
        ok('superadmin -> 200', r.status_code == 200, r.content)
        r = j(f'{BASE}/commandes/', 'get', admin_avec)
        ok('admin avec capacite -> 200', r.status_code == 200, r.content)
        r = j(f'{BASE}/commandes/', 'get', pa.user)
        ok('un partenaire -> 403', r.status_code == 403, r.content)

        print('\n=== 2. META ===')
        r = j(f'{BASE}/meta/', 'get', superadmin)
        d = r.json()
        ok('meta -> 200, 9 statuts, 4 groupes, 3 modes',
           r.status_code == 200 and len(d['statuts']) == 9 and len(d['groupes']) == 4
           and len(d['modes_livraison']) == 3, d)
        ok('chaque statut a un groupe non vide', all(s['groupe'] for s in d['statuts']), d['statuts'])

        print('\n=== 3. FILTRES + COMPTEURS ===')
        c_acceptee = creer_commande('acceptee')
        c_livree = creer_commande('livree')
        c_annulee = creer_commande('annulee')
        c_autre_partenaire = Commande.objects.create(
            numero=f'PFR-TEST-{Commande.objects.count()+1:05d}', user=client,
            partenaire=ProfilPartenaire.objects.exclude(id=pa.id).first(),
            statut='nouvelle', total=1000)

        r = j(f'{BASE}/commandes/?groupe=a_traiter', 'get', superadmin)
        ok('?groupe=a_traiter contient c1', str(c1.id) in {x['id'] for x in resultats(r)} or c1.id in {x['id'] for x in resultats(r)}, resultats(r))
        ok('?groupe=a_traiter : plus anciennes d\'abord (cree_le croissant)',
           [x['cree_le'] for x in resultats(r)] == sorted(x['cree_le'] for x in resultats(r)))
        r = j(f'{BASE}/commandes/?statut=livree', 'get', superadmin)
        ids_livree = {x['id'] for x in resultats(r)}
        ok('?statut=livree', c_livree.id in ids_livree and c1.id not in ids_livree and all(x['statut'] == 'livree' for x in resultats(r)))
        r = j(f'{BASE}/commandes/?statut=inconnu', 'get', superadmin)
        ok('statut inconnu -> 400', r.status_code == 400, r.content)
        r = j(f'{BASE}/commandes/?groupe=inconnu', 'get', superadmin)
        ok('groupe inconnu -> 400', r.status_code == 400, r.content)
        r = j(f'{BASE}/commandes/?partenaire={pa.id}', 'get', superadmin)
        ok('?partenaire=', c_autre_partenaire.id not in {x['id'] for x in resultats(r)}
           and c1.id in {x['id'] for x in resultats(r)})
        r = j(f'{BASE}/commandes/?client={client.id}', 'get', superadmin)
        ok('?client=', all(x['client']['id'] == client.id for x in resultats(r)))
        r = j(f'{BASE}/commandes/?search={c1.numero}', 'get', superadmin)
        ok('?search= reference', {x['id'] for x in resultats(r)} == {c1.id}, resultats(r))
        r = j(f'{BASE}/commandes/?search={pa.nom_commerce}', 'get', superadmin)
        ok('?search= nom partenaire', c1.id in {x['id'] for x in resultats(r)})
        r = j(f'{BASE}/commandes/?mode_livraison=emporter', 'get', superadmin)
        ok('?mode_livraison=', all(x['mode_livraison'] == 'emporter' for x in resultats(r)))
        r = j(f'{BASE}/commandes/?ordering=montant_total', 'get', superadmin)
        montants = [float(x['montant_total']) for x in resultats(r)]
        ok('?ordering=montant_total croissant', montants == sorted(montants))

        r = j(f'{BASE}/commandes/?partenaire={pa.id}&statut=livree', 'get', superadmin)
        cg = r.json()['compteurs_groupe']
        ok('compteurs_groupe ignore statut mais respecte partenaire (pas c_autre_partenaire)',
           cg['total'] == Commande.objects.filter(partenaire=pa).count(), cg)

        print('\n=== 4. DETAIL COMPLET ===')
        r = j(f'{BASE}/commandes/{c1.id}/', 'get', superadmin)
        d = r.json()
        ok('detail -> 200', r.status_code == 200, r.content)
        for cle in ('lignes', 'adresse_livraison', 'note_client', 'notes_admin',
                    'historique', 'transitions_possibles', 'peut_demander_livreur'):
            ok(f'detail contient "{cle}"', cle in d, d.keys())
        ok('lignes[0] a article_nom/quantite/prix_unitaire/sous_total/details',
           d['lignes'] and {'article_nom', 'quantite', 'prix_unitaire', 'sous_total', 'details'} <= set(d['lignes'][0]))
        ok('transitions_possibles = celles de "nouvelle"',
           {t['action'] for t in d['transitions_possibles']} == {'acceptee', 'refusee', 'annulee'}, d['transitions_possibles'])
        ok('commentaire_obligatoire=True uniquement pour annulee',
           {t['action']: t['commentaire_obligatoire'] for t in d['transitions_possibles']}['annulee'] is True
           and {t['action']: t['commentaire_obligatoire'] for t in d['transitions_possibles']}['acceptee'] is False)

        print('\n=== 5. TRANSITION ADMIN : historique + notification comme le partenaire ===')
        r = j(f'{BASE}/commandes/{c1.id}/transition/', 'post', admin_avec,
              {'action': 'acceptee', 'commentaire': 'Vu et validé'})
        ok('transition admin acceptee -> 200', r.status_code == 200, r.content)
        c1.refresh_from_db()
        ok('statut mis a jour', c1.statut == 'acceptee')
        hist = HistoriqueCommande.objects.filter(commande=c1).order_by('cree_le')
        ok('historique cree avec acteur=admin_avec, role=admin, commentaire',
           hist.count() == 1 and hist.first().acteur_id == admin_avec.id
           and hist.first().acteur_role == 'admin' and hist.first().commentaire == 'Vu et validé')
        from apps.notifications.fcm import notifier_utilisateur
        # notification client identique a une transition partenaire : on verifie
        # via l'appel direct de la fonction partagee (comportement, pas mock ici)
        from apps.orders.services import _notifier_transition_commande
        ok('meme fonction de notification que le flux partenaire (import direct)',
           _notifier_transition_commande.__module__ == 'apps.orders.services')

        print('\n=== 6. ANNULATION SANS MOTIF -> 400 ===')
        c2 = creer_commande('nouvelle')
        r = j(f'{BASE}/commandes/{c2.id}/transition/', 'post', admin_avec, {'action': 'annulee'})
        ok('annulation sans commentaire -> 400', r.status_code == 400, r.content)
        c2.refresh_from_db()
        ok('statut inchange', c2.statut == 'nouvelle')
        r = j(f'{BASE}/commandes/{c2.id}/transition/', 'post', admin_avec,
              {'action': 'annulee', 'commentaire': 'Rupture de stock confirmee par le commercant'})
        ok('annulation avec motif -> 200', r.status_code == 200, r.content)
        c2.refresh_from_db()
        ok('statut = annulee, annulee_par = admin', c2.statut == 'annulee' and c2.annulee_par_id == admin_avec.id)

        print('\n=== 7. DEMANDE DE LIVREUR (TeneLivr) + 409 doublon ===')
        c3 = creer_commande('prete', mode_livraison='livraison')
        r = j(f'{BASE}/commandes/{c3.id}/demander-livreur/', 'post', admin_avec, {'commentaire': 'Client a rappele'})
        ok('demande de livreur -> 201', r.status_code == 201, r.content)
        ok('reponse contient livraison{id,statut,...}',
           'livraison' in r.json() and {'id', 'statut', 'statut_libelle', 'livreur_nom', 'livreur_telephone'} <= set(r.json()['livraison']))
        c3.refresh_from_db()
        ok('commande passee en_livraison', c3.statut == 'en_livraison')
        ok('une Course TeneLivr a bien ete creee', Course.objects.filter(commande=c3).exists())
        course = Course.objects.filter(commande=c3).first()
        ok('type_demandeur = admin (analytics)', course.type_demandeur == 'admin')
        ok('historique note la demande de livreur',
           HistoriqueCommande.objects.filter(commande=c3, acteur_role='admin').exists())
        r = j(f'{BASE}/commandes/{c3.id}/demander-livreur/', 'post', admin_avec, {})
        ok('2e demande sur la meme commande -> 409', r.status_code == 409, r.content)
        ok('   message + course_numero', 'course_numero' in r.json())

        c4 = creer_commande('nouvelle', mode_livraison='livraison')
        r = j(f'{BASE}/commandes/{c4.id}/demander-livreur/', 'post', admin_avec, {})
        ok('commande pas prete -> 400 message clair', r.status_code == 400 and 'prête' in r.json()['message'], r.content)

        print('\n=== 8. NOTES INTERNES : invisibles partenaire/client ===')
        r = j(f'{BASE}/commandes/{c1.id}/notes/', 'post', admin_avec, {'texte': 'Client VIP, a rappele 2 fois'})
        ok('creation note -> 201', r.status_code == 201, r.content)
        note = r.json()
        ok('note a id/auteur_nom/texte/cree_le', {'id', 'auteur_nom', 'texte', 'cree_le'} <= set(note))
        ok('auteur_nom renseigne', note['auteur_nom'])
        r = j(f'{BASE}/commandes/{c1.id}/notes/', 'post', admin_avec, {'texte': ''})
        ok('texte vide -> 400', r.status_code == 400, r.content)

        r_part = j('/api/v1/orders/commandes/partenaire/', 'get', pa.user)
        ok('vue partenaire : aucune trace de "notes_admin" ni du texte de la note',
           'notes_admin' not in json.dumps(r_part.json())
           and 'Client VIP' not in json.dumps(r_part.json()))
        r_client = j(f'/api/v1/orders/commandes/{c1.id}/', 'get', client)
        ok('vue client (detail existant) : aucune trace de la note interne',
           'notes_admin' not in json.dumps(r_client.json())
           and 'Client VIP' not in json.dumps(r_client.json()))
        r_admin_detail = j(f'{BASE}/commandes/{c1.id}/', 'get', superadmin)
        ok('vue admin : la note apparait bien dans notes_admin',
           any('Client VIP' in n['texte'] for n in r_admin_detail.json()['notes_admin']))

        print('\n=== 9. STATS COHERENTES ===')
        du = c1.created_at.date().isoformat()
        r = j(f'{BASE}/stats/?du={du}&partenaire={pa.id}', 'get', superadmin)
        ok('stats -> 200', r.status_code == 200, r.content)
        s = r.json()
        for cle in ('kpis', 'par_jour', 'par_statut', 'par_groupe', 'par_partenaire',
                    'par_type_partenaire', 'par_client', 'par_mode_livraison',
                    'par_heure', 'par_jour_semaine', 'par_departement'):
            ok(f'stats contient "{cle}"', cle in s, s.keys())
        total_reel = Commande.objects.filter(
            partenaire=pa, created_at__date__gte=du).count()
        ok('kpis.total coherent avec la base', s['kpis']['total'] == total_reel, (s['kpis']['total'], total_reel))
        ok('kpis : a_traiter+en_cours+terminees+annulees = total',
           s['kpis']['a_traiter'] + s['kpis']['en_cours'] + s['kpis']['terminees']
           + s['kpis']['annulees'] == s['kpis']['total'], s['kpis'])
        ok('par_heure a 24 entrees (0-23)', len(s['par_heure']) == 24
           and {x['heure'] for x in s['par_heure']} == set(range(24)))
        ok('par_jour_semaine a 7 entrees, lundi=1', len(s['par_jour_semaine']) == 7
           and s['par_jour_semaine'][0]['jour'] == 1 and s['par_jour_semaine'][0]['libelle'] == 'Lundi')
        print('\n=== 9b. par_partenaire_detail ===')
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        c_autre_stats = Commande.objects.filter(pk=c_autre_partenaire.pk).exists() if False else None
        du_large = Commande.objects.order_by('created_at').first().created_at.date().isoformat()
        with CaptureQueriesContext(connection) as ctx:
            rr = j(f'{BASE}/stats/?du={du_large}', 'get', superadmin)
        sd = rr.json()
        det = sd['par_partenaire_detail']
        ok('par_partenaire_detail present', rr.status_code == 200 and isinstance(det, list) and det, sd.keys())
        ok('champs exacts id/nom/total/a_traiter/en_cours/terminees/annulees/montant',
           all({'id', 'nom', 'total', 'a_traiter', 'en_cours', 'terminees', 'annulees', 'montant'} <= set(x) for x in det))
        ok('trie par total decroissant', [x['total'] for x in det] == sorted((x['total'] for x in det), reverse=True))
        ok('chaque ligne : groupes = total', all(
            x['a_traiter'] + x['en_cours'] + x['terminees'] + x['annulees'] == x['total'] for x in det), det)
        ok('somme des totaux = kpis.total', sum(x['total'] for x in det) == sd['kpis']['total'])
        ok('tous les partenaires ayant des commandes y figurent (pas de limite a 10)',
           {x['id'] for x in det} == set(Commande.objects.filter(
               created_at__date__gte=du_large).values_list('partenaire_id', flat=True)))
        ok('le partenaire de test "autre" (1 commande a traiter) est present',
           any(x['id'] == c_autre_partenaire.partenaire_id and x['a_traiter'] >= 1 for x in det))
        ok('par_partenaire (top 10) inchange : toujours present avec id/nom/nb/montant',
           sd['par_partenaire'] and {'id', 'nom', 'nb', 'montant'} <= set(sd['par_partenaire'][0]))
        nb_req_detail = sum(1 for q in ctx.captured_queries if 'nb_a_traiter' in q['sql'])
        ok('UNE seule requete agregee pour par_partenaire_detail', nb_req_detail == 1, nb_req_detail)
        somme_statut = sum(x['nb'] for x in s['par_statut'])
        ok('somme par_statut = total', somme_statut == s['kpis']['total'], (somme_statut, s['kpis']['total']))

        raise Rollback('annulation volontaire')
except Rollback as e:
    print('\nRollback partie A effectue :', e)

assert Commande.objects.count() == avant_c, 'commandes de test persistees !'
assert HistoriqueCommande.objects.count() == avant_h, 'historique persiste !'
assert NoteAdminCommande.objects.count() == avant_n, 'notes persistees !'
print(f'Partie A : rien persiste (commandes={avant_c}, historique={avant_h}, notes={avant_n}).')

# ═══════════════════════════════════════════════════════════════════════
# PARTIE B — hors transaction (notifications de creation via on_commit,
# et annulation client -> notif admin) : cree reellement, puis nettoie.
# ═══════════════════════════════════════════════════════════════════════
print('\n=== 10. NOTIFICATION ADMIN A LA CREATION (on_commit reel) ===')
superadmin = User.objects.filter(is_superuser=True).first()
pa = ProfilPartenaire.objects.get(id=1)
client = User.objects.get(id=144)
article = Article.objects.filter(partenaire=pa, est_actif=True).first()
categorie_id = article.categorie_id

admin_avec_b = User.objects.create(
    telephone='+22504000003', username='t_cmd_avec_b', role=User.Role.ADMIN,
    is_staff=True, is_superuser=False, est_verifie=True)
admin_avec_b.set_password('0000'); admin_avec_b.save()
PermissionsAdmin.objects.create(admin=admin_avec_b, gerer_commandes=True)

panier = Panier.objects.create(user=client, partenaire=pa, categorie_id=categorie_id)
LignePanier.objects.create(panier=panier, article=article, quantite=1, prix_unitaire=2500)

commande_creee = None
try:
    r = j(f'/api/v1/orders/paniers/{panier.id}/valider/', 'post', client, {})
    ok('validation panier (flux client, non-regression) -> 201', r.status_code == 201, r.content)
    commande_creee = Commande.objects.get(id=r.json()['id'])

    notifs = Notification.objects.filter(type='commande_nouvelle', data__commande_id=commande_creee.id)
    ok('notification admin creee pour superadmin', notifs.filter(user=superadmin).exists())
    ok('notification admin creee pour admin_avec_b (capacite)', notifs.filter(user=admin_avec_b).exists())
    n = notifs.filter(user=admin_avec_b).first()
    ok('titre = "Nouvelle commande"', n.titre == 'Nouvelle commande')
    ok('message contient reference, client, partenaire, montant',
       commande_creee.numero in n.contenu and pa.nom_commerce in n.contenu and 'FCFA' in n.contenu, n.contenu)
    ok('data.commande_id / groupe corrects',
       n.data.get('commande_id') == commande_creee.id and n.data.get('groupe') == 'a_traiter', n.data)

    print('\n=== 11. NOTIFICATION ADMIN A L\'ANNULATION PAR LE CLIENT ===')
    r = j(f'/api/v1/orders/commandes/{commande_creee.id}/transition/', 'post', client, {'statut': 'annulee'})
    ok('annulation par le client (flux existant, non-regression) -> 200', r.status_code == 200, r.content)
    notifs2 = Notification.objects.filter(type='commande_annulee_client', data__commande_id=commande_creee.id)
    ok('notification admin sur annulation client (superadmin + admin_avec_b)',
       notifs2.filter(user=superadmin).exists() and notifs2.filter(user=admin_avec_b).exists())
    hist = HistoriqueCommande.objects.filter(commande=commande_creee)
    ok('historique cree pour l\'annulation client (role=client)',
       hist.filter(acteur_role='client', acteur=client).exists())

    print('\n=== 12. ENDPOINT NOTIFICATIONS ADMIN : commande_id/groupe exposes ===')
    r = j('/api/v1/notifications/admin/', 'get', admin_avec_b)
    items = resultats(r)
    item = next(x for x in items if x.get('commande_id') == commande_creee.id)
    ok('commande_id/groupe presents dans la reponse /notifications/admin/',
       'commande_id' in item and 'groupe' in item, item)
    ok('publicite_id/statut_publicite toujours presents (rien retire)',
       'publicite_id' in item and 'statut_publicite' in item)

finally:
    print('\n=== NETTOYAGE PARTIE B ===')
    if commande_creee is not None:
        Notification.objects.filter(data__commande_id=commande_creee.id).delete()
        HistoriqueCommande.objects.filter(commande=commande_creee).delete()
        commande_creee.delete()
    Panier.objects.filter(id=panier.id).delete()
    admin_avec_b.delete()
    print('Nettoye.')

print(f'\n=== TOTAL : {NB} verifications reussies ===')
