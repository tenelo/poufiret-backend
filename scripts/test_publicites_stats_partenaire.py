"""Tests : stats de pubs visibles cote partenaire (active/terminee, masquables
par l'admin), endpoint admin stats-visibles, journal, liste admin.

Execution (tout est annule a la fin) :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_publicites_stats_partenaire.py
"""
import json

from django.db import transaction
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.publicites.models import FormulePublicite, Publicite
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


def get(url, user):
    return Client().get(url, secure=True, **h(user))


def post(url, user, corps):
    return Client().post(url, json.dumps(corps), content_type='application/json',
                         secure=True, **h(user))


avant = Publicite.objects.count()
avant_j = JournalModeration.objects.count()
try:
    with transaction.atomic():
        superadmin = User.objects.filter(is_superuser=True).first()
        admin_valide = User.objects.create(
            telephone='+22505000001', username='t_stats_valide', role=User.Role.ADMIN,
            is_staff=True, is_superuser=False, est_verifie=True)
        admin_valide.set_password('0000'); admin_valide.save()
        PermissionsAdmin.objects.create(admin=admin_valide, valider_publicite=True)
        admin_sans = User.objects.create(
            telephone='+22505000002', username='t_stats_sans', role=User.Role.ADMIN,
            is_staff=True, is_superuser=False, est_verifie=True)
        admin_sans.set_password('0000'); admin_sans.save()
        PermissionsAdmin.objects.create(admin=admin_sans)

        pa = ProfilPartenaire.objects.get(id=2)
        formule = FormulePublicite.objects.get(nom='Éclair')

        def pub(statut, **kw):
            return Publicite.objects.create(
                partenaire=pa, formule=formule, titre=f'Stats {statut}',
                image_couverture='x.jpg', statut=statut,
                nb_impressions=100, nb_clics=7, nb_personnes_touchees=40, **kw)

        def stats_de(p):
            r = get('/api/v1/publicites/mes-stats/', pa.user)
            assert r.status_code == 200, r.content
            return next(x for x in r.json()['publicites'] if x['id'] == str(p.id))

        print('\n=== 1. DEFAUT + REGLE DE VISIBILITE COTE PARTENAIRE ===')
        active = pub('active')
        ok('nouvelle pub : stats_visibles_partenaire = True par defaut', active.stats_visibles_partenaire is True)
        d = stats_de(active)
        ok('pub active -> stats visibles (stats_visibles=True)', d['stats_visibles'] is True, d)
        ok('   impressions, personnes touchees, clics, taux de clic presents',
           (d['nb_impressions'], d['nb_personnes_touchees'], d['nb_clics'], d['taux_clic']) == (100, 40, 7, 7.0), d)
        ok('   statut_libelle = Active', d['statut_libelle'] == 'Active')
        ok('   champs existants conserves (id, titre, formule, statut, impressions_par_type...)',
           {'id', 'titre', 'formule', 'statut', 'impressions_par_type', 'cible_atteinte',
            'debut_diffusion', 'fin_diffusion'} <= set(d), set(d))
        terminee = pub('terminee')
        d = stats_de(terminee)
        ok('pub terminee -> stats visibles', d['stats_visibles'] is True and 'nb_impressions' in d, d)
        ok('   statut_libelle = Terminée', d['statut_libelle'] == 'Terminée')
        for statut in ('brouillon', 'en_attente_paiement', 'en_attente_validation', 'rejetee'):
            p = pub(statut)
            d = stats_de(p)
            ok(f'pub {statut} (flag True) -> PAS de stats',
               d['stats_visibles'] is False and d['stats_disponibles'] is False
               and 'nb_impressions' not in d, d)
            ok(f'   {statut} : statut_libelle present et champs allégés existants conserves',
               d['statut_libelle'] and {'id', 'titre', 'formule', 'statut', 'message'} <= set(d))

        print('\n=== 2. ENDPOINT ADMIN stats-visibles ===')
        url = lambda p: f'/api/v1/publicites/admin/{p.id}/stats-visibles/'
        r = post(url(active), pa.user, {'visible': False})
        ok('partenaire -> 403', r.status_code == 403, r.content)
        r = post(url(active), admin_sans, {'visible': False})
        ok('admin sans valider_publicite -> 403', r.status_code == 403, r.content)
        r = post(url(active), admin_valide, {'visible': 'oui'})
        ok('valeur non booleenne -> 400', r.status_code == 400, r.content)
        r = post(url(active), admin_valide, {})
        ok('visible absent -> 400', r.status_code == 400, r.content)
        nb_j = JournalModeration.objects.filter(action='pub_stats_visibles').count()
        r = post(url(active), admin_valide, {'visible': False})
        ok('admin avec valider_publicite : masquer -> 200', r.status_code == 200
           and r.json()['stats_visibles_partenaire'] is False and r.json()['stats_visibles'] is False, r.content)
        e = JournalModeration.objects.filter(action='pub_stats_visibles').latest('cree_le')
        ok('journal : 1 entree, acteur = admin, motif « masquées » + titre',
           JournalModeration.objects.filter(action='pub_stats_visibles').count() == nb_j + 1
           and e.acteur_id == admin_valide.id and 'masquées' in e.motif and 'Stats active' in e.motif, e.motif)
        d = stats_de(active)
        ok('masquee par l\'admin -> stats INVISIBLES cote partenaire',
           d['stats_visibles'] is False and d['stats_disponibles'] is False and 'nb_impressions' not in d, d)
        r = post(url(active), admin_valide, {'visible': False})
        ok('idempotent : 2e masquage identique -> 200, pas de nouvelle entree de journal',
           r.status_code == 200 and JournalModeration.objects.filter(
               action='pub_stats_visibles').count() == nb_j + 1)
        r = post(url(active), superadmin, {'visible': True})
        ok('super-admin rend visibles -> 200', r.status_code == 200 and r.json()['stats_visibles'] is True, r.content)
        e = JournalModeration.objects.filter(action='pub_stats_visibles').latest('cree_le')
        ok('journal : « rendues visibles »', 'rendues visibles' in e.motif, e.motif)
        ok('stats a nouveau visibles cote partenaire', stats_de(active)['stats_visibles'] is True)
        # flag True mais pub en attente : la reponse effective reste False
        attente = pub('en_attente_validation')
        r = post(url(attente), admin_valide, {'visible': True})
        ok('pub en attente : flag True mais stats_visibles effectif False',
           r.status_code == 200 and r.json()['stats_visibles_partenaire'] is True
           and r.json()['stats_visibles'] is False, r.content)
        brouillon = Publicite.objects.filter(statut='brouillon', partenaire=pa).first()
        r = post(url(brouillon), admin_valide, {'visible': False})
        ok('brouillon (invisible de l\'admin) -> 404', r.status_code == 404, r.content)
        import uuid
        r = post(f'/api/v1/publicites/admin/{uuid.uuid4()}/stats-visibles/', admin_valide, {'visible': True})
        ok('pub inconnue -> 404', r.status_code == 404, r.content)

        print('\n=== 3. LISTE ADMIN : stats_visibles_partenaire expose ===')
        post(url(terminee), admin_valide, {'visible': False})
        r = get('/api/v1/publicites/admin/stats/', superadmin)
        lignes = {x['id']: x for x in r.json()['publicites']}
        ok('chaque pub porte stats_visibles_partenaire', all('stats_visibles_partenaire' in x for x in lignes.values()))
        ok('valeur correcte (terminee masquee = False, active = True)',
           lignes[str(terminee.id)]['stats_visibles_partenaire'] is False
           and lignes[str(active.id)]['stats_visibles_partenaire'] is True)
        anciens = {'id', 'titre', 'formule', 'statut', 'nb_impressions', 'nb_clics', 'taux_clic',
                   'portee', 'portee_effective', 'image_couverture', 'video', 'partenaire_id'}
        ok('aucun champ existant retire de la liste admin', anciens <= set(next(iter(lignes.values()))))
        ok('compteurs_statut et totaux toujours presents', {'totaux', 'compteurs_statut'} <= set(r.json()))

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback('annulation volontaire')
except Rollback as e:
    print('Rollback effectue :', e)

assert Publicite.objects.count() == avant and JournalModeration.objects.count() == avant_j, 'donnees persistees !'
print(f'Aucune donnee persistee (publicites: {avant}, journal: {avant_j}).')
