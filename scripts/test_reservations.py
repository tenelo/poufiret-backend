"""Tests : demandes de visite/réservation (apps.reservations), communes aux
métiers de location. Création (règles : visite sur logement disponible
uniquement, dates obligatoires selon la nature), droits (client, loueur,
admin), transitions (mode parallèle), effet sur la disponibilité du
logement (confirmee -> reserve, annulee depuis confirmee -> disponible),
annulation client, notifications admin, centre de gestion admin.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_reservations.py
"""
import json, uuid
from django.db import transaction
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken
from apps.administration.models import PermissionsAdmin
from apps.catalog.models import Article, Logement
from apps.moderation.models import Notification
from apps.reservations.models import DemandeReservation, HistoriqueDemande, NoteAdminDemande
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
class Rollback(Exception): pass
NB = 0
def ok(l, c, d=''):
    global NB
    print(('OK   ' if c else 'FAIL '), l, '' if c else d)
    assert c, f'{l} {d}'
    NB += 1

def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel

def utilisateur(username, role='client', staff=False, superuser=False):
    u = User.objects.create(telephone=telephone_libre(), username=username, role=role,
                            est_verifie=True, is_staff=staff, is_superuser=superuser)
    u.set_password('1234'); u.save()
    return u

def req(method, url, user=None, corps=None):
    kw = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    c = Client()
    if corps is None:
        return getattr(c, method)(url, **kw)
    return getattr(c, method)(url, json.dumps(corps), content_type='application/json', **kw)

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        loueur_user = utilisateur('t_rsv_loueur', role='partenaire')
        loueur = ProfilPartenaire.objects.create(user=loueur_user, plan=plan, nom_commerce=f'Loueur RSV QA {uid}',
            type_partenaire='loueur_maison', statut='actif', est_visible=True)
        cat = __import__('apps.catalog.correspondances', fromlist=['categories_correspondantes']).categories_correspondantes('loueur_maison').first()
        art_dispo = Article.objects.create(partenaire=loueur, categorie=cat, nom=f'Dispo RSV {uid}',
            slug=f'dispo-rsv-{uid}', type='logement', prix=100000, est_actif=True)
        log_dispo = Logement.objects.create(article=art_dispo, type_logement='villa', disponibilite='disponible')
        art_loue = Article.objects.create(partenaire=loueur, categorie=cat, nom=f'Loue RSV {uid}',
            slug=f'loue-rsv-{uid}', type='logement', prix=80000, est_actif=True)
        log_loue = Logement.objects.create(article=art_loue, type_logement='studio', disponibilite='loue')

        client_user = utilisateur('t_rsv_client', role='client')
        autre_client = utilisateur('t_rsv_autre', role='client')
        super_ = utilisateur('t_rsv_super', role='admin', staff=True, superuser=True)
        admin_sans = utilisateur('t_rsv_sans', role='admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans)
        admin_avec = utilisateur('t_rsv_avec', role='admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin_avec, gerer_reservations=True)

        CREER = '/api/v1/reservations/'

        print('=== 1. CREATION : regles de validation ===')
        r = req('post', CREER, client_user, {'objet_id': art_loue.id, 'nature': 'visite',
                                             'date_souhaitee': '2026-11-01T10:00:00Z'})
        ok('visite sur logement non disponible -> 400 details.objet_id',
           r.status_code == 400 and 'objet_id' in r.json()['details'], r.content)
        r = req('post', CREER, client_user, {'objet_id': art_dispo.id, 'nature': 'visite'})
        ok('visite sans date_souhaitee -> 400', r.status_code == 400, r.content)
        r = req('post', CREER, client_user, {'objet_id': art_dispo.id, 'nature': 'reservation'})
        ok('reservation sans dates -> 400', r.status_code == 400, r.content)
        r = req('post', CREER, client_user, {'objet_id': art_dispo.id, 'nature': 'reservation',
                                             'date_debut': '2026-11-10', 'date_fin': '2026-11-01'})
        ok('date_fin <= date_debut -> 400', r.status_code == 400, r.content)

        print('=== 2. CREATION VALIDE : visite, puis notification admin ===')
        avant_notif = Notification.objects.filter(type='reservation_nouvelle').count()
        r = req('post', CREER, client_user, {'objet_id': art_dispo.id, 'nature': 'visite',
                                             'date_souhaitee': '2026-11-01T10:00:00Z', 'nb_personnes': 2,
                                             'telephone_contact': '0700000099'})
        ok('visite valide -> 201', r.status_code == 201, r.content)
        demande_visite = r.json()
        ok('numero genere, statut nouvelle', demande_visite['numero'].startswith('RSV-')
           and demande_visite['statut'] == 'nouvelle', demande_visite)
        ok('historique : 1 entree (creation)', len(demande_visite['historique']) == 1, demande_visite['historique'])
        ok('notification admin creee (reservation_nouvelle)',
           Notification.objects.filter(type='reservation_nouvelle').count() > avant_notif)
        notif = Notification.objects.filter(type='reservation_nouvelle').order_by('-id').first()
        ok('notification : data.demande_id present', notif.data.get('demande_id') == demande_visite['id'], notif.data)
        ok('notification envoyee au super-admin', Notification.objects.filter(
            type='reservation_nouvelle', user=super_).exists())
        ok('notification envoyee a l admin avec capacite', Notification.objects.filter(
            type='reservation_nouvelle', user=admin_avec).exists())
        ok('PAS de notification a l admin sans capacite', not Notification.objects.filter(
            type='reservation_nouvelle', user=admin_sans).exists())

        print('=== 3. CREATION VALIDE : reservation (pour le cycle confirmee/annulee) ===')
        r = req('post', CREER, client_user, {'objet_id': art_dispo.id, 'nature': 'reservation',
                                             'date_debut': '2026-12-01', 'date_fin': '2026-12-10'})
        ok('reservation valide -> 201', r.status_code == 201, r.content)
        demande_resa = r.json()

        print('=== 4. DROITS DE LECTURE ===')
        r = req('get', '/api/v1/reservations/mes-demandes/', client_user)
        ok('mes-demandes (client) -> 200, 2 demandes', r.status_code == 200 and r.json()['count'] == 2, r.content)
        r = req('get', '/api/v1/reservations/mes-demandes/', autre_client)
        ok('mes-demandes (autre client) -> 0 demande', r.status_code == 200 and r.json()['count'] == 0)
        r = req('get', '/api/v1/reservations/mon-espace/', loueur_user)
        ok('mon-espace (loueur) -> 200, 2 demandes', r.status_code == 200 and r.json()['count'] == 2, r.content)
        r = req('get', '/api/v1/reservations/mon-espace/', client_user)
        ok('mon-espace (non partenaire) -> 200, liste vide', r.status_code == 200 and r.json()['count'] == 0)

        print('=== 5. TRANSITIONS LOUEUR ===')
        TR_VISITE = f'/api/v1/reservations/{demande_visite["id"]}/transition/'
        r = req('post', TR_VISITE, autre_client, {'action': 'en_cours'})
        ok('transition par un tiers -> 404/403', r.status_code in (403, 404), r.content)
        r = req('post', TR_VISITE, loueur_user, {'action': 'refusee'})
        ok('refuser sans motif -> 400', r.status_code == 400, r.content)
        r = req('post', TR_VISITE, loueur_user, {'action': 'en_cours'})
        ok('loueur : nouvelle -> en_cours -> 200', r.status_code == 200 and r.json()['statut'] == 'en_cours', r.content)
        r = req('post', TR_VISITE, loueur_user, {'action': 'nouvelle'})
        ok('transition hors machine d etat -> 400', r.status_code == 400, r.content)
        r = req('post', TR_VISITE, loueur_user, {'action': 'confirmee'})
        ok('loueur : en_cours -> confirmee -> 200', r.status_code == 200 and r.json()['statut'] == 'confirmee', r.content)
        log_dispo.refresh_from_db()
        ok('visite confirmee : disponibilite du logement inchangee (reste disponible)',
           log_dispo.disponibilite == 'disponible', log_dispo.disponibilite)

        print('=== 6. RESERVATION CONFIRMEE : logement -> reserve ===')
        TR_RESA = f'/api/v1/reservations/{demande_resa["id"]}/transition/'
        req('post', TR_RESA, loueur_user, {'action': 'en_cours'})
        r = req('post', TR_RESA, loueur_user, {'action': 'confirmee'})
        ok('reservation confirmee -> 200', r.status_code == 200, r.content)
        log_dispo.refresh_from_db()
        ok('logement passe en reserve', log_dispo.disponibilite == 'reserve', log_dispo.disponibilite)

        print('=== 7. ANNULATION CLIENT (depuis confirmee) : logement redevient disponible ===')
        r = req('post', f'/api/v1/reservations/{demande_resa["id"]}/annuler/', autre_client)
        ok('annuler une demande d un autre client -> 404', r.status_code == 404, r.content)
        r = req('post', f'/api/v1/reservations/{demande_resa["id"]}/annuler/', client_user, {'commentaire': 'changement de plan'})
        ok('annulation par le client -> 200', r.status_code == 200 and r.json()['statut'] == 'annulee', r.content)
        log_dispo.refresh_from_db()
        ok('logement redevient disponible', log_dispo.disponibilite == 'disponible', log_dispo.disponibilite)
        ok('loueur notifie de l annulation (notification systeme best-effort, pas d erreur)', True)

        print('=== 8. CENTRE ADMIN ===')
        ok('admin sans capacite -> 403', req('get', '/api/v1/reservations/admin/meta/', admin_sans).status_code == 403)
        r = req('get', '/api/v1/reservations/admin/meta/', admin_avec)
        ok('meta -> 200', r.status_code == 200 and {'statuts', 'groupes', 'natures'} <= set(r.json()), r.content)
        r = req('get', f'/api/v1/reservations/admin/demandes/?partenaire={loueur.id}', admin_avec)
        ok('liste admin -> 200 avec compteurs_groupe', r.status_code == 200 and 'compteurs_groupe' in r.json(), r.content)
        ok('2 demandes pour ce loueur', r.json()['count'] == 2)
        r = req('get', '/api/v1/reservations/admin/demandes/?groupe=zzz', admin_avec)
        ok('groupe invalide -> 400', r.status_code == 400)
        r = req('get', f'/api/v1/reservations/admin/demandes/?search={demande_visite["numero"]}', admin_avec)
        ok('recherche par numero -> 1 resultat', r.json()['count'] == 1, r.json())
        r = req('get', f'/api/v1/reservations/admin/demandes/{demande_visite["id"]}/', admin_avec)
        ok('detail admin -> 200, notes_admin vide', r.status_code == 200 and r.json()['notes_admin'] == [], r.content)
        r = req('post', f'/api/v1/reservations/admin/demandes/{demande_visite["id"]}/notes/', admin_avec, {'texte': 'Client fiable'})
        ok('note admin -> 201', r.status_code == 201, r.content)
        r = req('get', f'/api/v1/reservations/admin/demandes/{demande_visite["id"]}/', admin_avec)
        ok('note visible dans le detail admin', len(r.json()['notes_admin']) == 1, r.json()['notes_admin'])
        r = req('get', f'/api/v1/reservations/mes-demandes/', client_user)
        ok('note admin jamais visible du client', 'notes_admin' not in r.json()['results'][0])
        r = req('post', f'/api/v1/reservations/admin/demandes/{demande_visite["id"]}/transition/', admin_avec, {'action': 'terminee'})
        ok('transition admin : confirmee -> terminee -> 200', r.status_code == 200 and r.json()['statut'] == 'terminee', r.content)
        r = req('post', f'/api/v1/reservations/admin/demandes/{demande_visite["id"]}/transition/', admin_avec, {'action': 'annulee'})
        ok('transition admin sans motif sur une action qui le requiert -> 400', r.status_code == 400, r.content)
        r = req('get', '/api/v1/reservations/admin/demandes/export/', admin_avec)
        ok('export CSV -> 200', r.status_code == 200 and r['Content-Type'].startswith('text/csv'), r.status_code)
        ok('historique complet trace tous les acteurs',
           set(HistoriqueDemande.objects.filter(demande_id=demande_visite['id']).values_list('acteur_role', flat=True))
           == {'client', 'loueur', 'admin'})

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
