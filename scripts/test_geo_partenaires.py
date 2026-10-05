"""Tests : localité et quartier des partenaires issus de la géographie.
Cohérence (400), synchronisation ville/quartier texte, lecture (profil,
vitrine, liste admin), création admin, cascades publiques (localites,
quartiers?localite=), rapprochement (endpoints admin, droits, application,
propositions), commande rapprocher_geographie_partenaires (lecture seule
puis --appliquer), non-régression du quartiers?departement= existant.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_geo_partenaires.py
"""
import io, json, uuid
from django.core.management import call_command
from django.db import transaction
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken
from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.geo.models import Departement, Localite, Quartier
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
class Rollback(Exception): pass
NB = 0
def ok(l, c, d=''):
    global NB
    print(('OK   ' if c else 'FAIL '), l, '' if c else d)
    assert c, f'{l} {d}'
    NB += 1

def cli(user=None):
    kw = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    return Client(), kw

def get(url, user=None):
    c, kw = cli(user)
    return c.get(url, **kw)

def send(method, url, corps, user):
    c, kw = cli(user)
    return getattr(c, method)(url, json.dumps(corps), content_type='application/json', **kw)

def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel


def utilisateur(tel, username, role, staff=False, superuser=False):
    tel = telephone_libre() if tel is None else tel
    u = User.objects.create(telephone=tel, username=username, role=role, est_verifie=True,
                            is_staff=staff, is_superuser=superuser)
    u.set_password('1234'); u.save()
    return u

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        dep_ferke = Departement.objects.get(nom='Ferké')
        dep_kong = Departement.objects.get(nom='Kong')
        loc_ferke = Localite.objects.get(nom='Ferké', departement=dep_ferke)
        loc_ferke_qa = Localite.objects.create(nom=f'Ferké QA {uid}', departement=dep_ferke)
        loc_kong_qa = Localite.objects.create(nom=f'Kong QA {uid}', departement=dep_kong)
        q_ferke = Quartier.objects.create(nom=f'Quartier QA {uid}', localite=loc_ferke_qa)
        q_kong = Quartier.objects.create(nom=f'Quartier Kong QA {uid}', localite=loc_kong_qa)
        plan = PlanAbonnement.objects.get(libelle='Basique')
        superadmin = utilisateur(None, 't_geo_super', 'admin', staff=True, superuser=True)
        admin_sans = utilisateur(None, 't_geo_sans', 'admin', staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans)
        part_user = utilisateur(None, 't_geo_part', 'partenaire')
        part = ProfilPartenaire.objects.create(user=part_user, plan=plan, nom_commerce='Geo QA',
                                               type_partenaire='commercant', departement=dep_ferke,
                                               statut='actif', est_visible=True)

        print('=== 1. COHERENCE (400) ===')
        url = '/api/v1/auth/mon-profil-partenaire/'
        r = send('patch', url, {'localite_id': loc_kong_qa.id}, part_user)
        ok('localite d un autre departement -> 400', r.status_code == 400, r.content)
        ok('message francais sur localite_id', 'département' in str(r.json()), r.content)
        r = send('patch', url, {'localite_id': loc_ferke_qa.id, 'quartier_id': q_kong.id}, part_user)
        ok('quartier d une autre localite -> 400', r.status_code == 400 and 'quartier_id' in r.content.decode(), r.content)
        r = send('patch', url, {'quartier_id': q_ferke.id}, part_user)
        ok('quartier sans localite -> 400', r.status_code == 400, r.content)

        print('=== 2. ECRITURE + SYNCHRONISATION DES TEXTES ===')
        r = send('patch', url, {'localite_id': loc_ferke_qa.id, 'quartier_id': q_ferke.id}, part_user)
        ok('coherent -> 200', r.status_code == 200, r.content)
        body = r.json()
        ok('lecture : localite_id/localite_nom/quartier_id/quartier_nom',
           body['localite_id'] == loc_ferke_qa.id and body['localite_nom'] == loc_ferke_qa.nom
           and body['quartier_id'] == q_ferke.id and body['quartier_nom'] == q_ferke.nom, body)
        part.refresh_from_db()
        ok('ville texte = localite.nom', part.ville == loc_ferke_qa.nom, part.ville)
        ok('quartier texte = quartier.nom', part.quartier == q_ferke.nom, part.quartier)
        r = send('patch', url, {'ville': 'Texte libre', 'quartier': 'Texte libre'}, part_user)
        part.refresh_from_db()
        ok('ville/quartier texte non modifiables directement',
           part.ville == loc_ferke_qa.nom and part.quartier == q_ferke.nom, (part.ville, part.quartier))
        r = get(url, part_user)
        ok('MonProfil GET : champs geo presents', 'localite_nom' in r.json() and 'quartier_nom' in r.json())

        print('=== 3. LECTURE VITRINE ET LISTE ADMIN ===')
        r = get(f'/api/v1/auth/partenaires/{part.id}/')
        ok('vitrine : localite_nom/quartier_nom presents',
           r.status_code == 200 and r.json()['localite_nom'] == loc_ferke_qa.nom
           and r.json()['quartier_nom'] == q_ferke.nom, r.content)
        r = get('/api/v1/administration/partenaires/liste/', superadmin)
        ligne = next((x for x in r.json().get('resultats', r.json()) if x['id'] == part.id), None) \
            if r.status_code == 200 else None
        ok('liste admin : localite/quartier presents', ligne is not None and ligne['localite_nom'] == loc_ferke_qa.nom,
           r.status_code)

        print('=== 4. CREATION ADMIN ===')
        tel = '+2250771234567'
        r = send('post', '/api/v1/auth/partenaires/creer/', {
            'telephone': tel, 'type_partenaire': 'commercant', 'nom_commerce': 'Creation Geo QA',
            'localite_id': loc_kong_qa.id, 'quartier_id': q_ferke.id}, superadmin)
        ok('creation : quartier hors localite -> 400', r.status_code == 400, r.content)
        r = send('post', '/api/v1/auth/partenaires/creer/', {
            'telephone': tel, 'type_partenaire': 'commercant', 'nom_commerce': 'Creation Geo QA',
            'localite_id': loc_kong_qa.id, 'quartier_id': q_kong.id}, superadmin)
        ok('creation coherente -> 201', r.status_code == 201, r.content)
        cree = ProfilPartenaire.objects.get(user__telephone=tel)
        ok('creation : departement derive de la localite', cree.departement_id == dep_kong.id)
        ok('creation : ville/quartier texte synchronises',
           cree.ville == loc_kong_qa.nom and cree.quartier == q_kong.nom, (cree.ville, cree.quartier))

        print('=== 5. CASCADES PUBLIQUES ===')
        r = get(f'/api/v1/geo/localites/?departement={dep_ferke.id}')
        ok('localites anonyme -> 200 {resultats}', r.status_code == 200 and 'resultats' in r.json(), r.content)
        noms = [x['nom'] for x in r.json()['resultats']]
        ok('localites : actives, triees par nom', noms == sorted(noms) and loc_ferke_qa.nom in noms, noms)
        ok('localites : ids+nom seulement', set(r.json()['resultats'][0]) == {'id', 'nom'})
        r = get(f'/api/v1/geo/quartiers/?localite={loc_ferke_qa.id}')
        ok('quartiers?localite= -> {resultats}', r.status_code == 200 and [x['id'] for x in r.json()['resultats']] == [q_ferke.id], r.content)
        r = get(f'/api/v1/geo/quartiers/?departement={dep_ferke.id}')
        ok('quartiers?departement= inchange : liste brute', isinstance(r.json(), list) and any(x['id'] == q_ferke.id for x in r.json()), r.content[:200])
        ok('localites?departement=abc -> 200 vide', get('/api/v1/geo/localites/?departement=abc').json() == {'resultats': []})

        print('=== 6. RAPPROCHEMENT : LISTE ET DROITS ===')
        url_r = '/api/v1/administration/geo/rapprochement-partenaires/'
        ok('sans capacite gerer_geographie -> 403', get(url_r, admin_sans).status_code == 403)
        ok('statut invalide -> 400', get(url_r + '?statut=zzz', superadmin).status_code == 400)
        r = get(url_r + '?statut=tous', superadmin)
        ok('liste -> 200 {resultats, compteurs}', r.status_code == 200 and {'resultats', 'compteurs'} <= set(r.json()), r.content[:200])
        ok('chaque ligne porte departement_id (null si aucun)',
           all('departement_id' in x and 'departement_nom' in x for x in r.json()['resultats']))
        cpt = r.json()['compteurs']
        ok('compteurs : exact, proposition, aucun, rapproches',
           set(cpt) == {'exact', 'proposition', 'aucun', 'rapproches'}, cpt)
        ok('partenaire deja rattache : compte dans rapproches, non liste',
           cpt['rapproches'] >= 1 and not any(x['partenaire_id'] == part.id for x in r.json()['resultats']))
        ok('filtre exact ne retourne que des exact',
           all(x['statut'] == 'exact' for x in get(url_r + '?statut=exact', superadmin).json()['resultats']))

        print('=== 7. RAPPROCHEMENT : PROPOSITIONS ET APPLICATION ===')
        # Partenaire de test : ville exacte + quartier proche (faute de frappe)
        p2_user = utilisateur(None, 't_geo_p2', 'partenaire')
        p2 = ProfilPartenaire.objects.create(user=p2_user, plan=plan, nom_commerce='Rapp QA',
                                             type_partenaire='commercant', departement=dep_kong,
                                             ville=loc_kong_qa.nom.upper(), quartier='Quartier kong-qa '+uid)
        r = get(url_r + '?statut=tous', superadmin)
        ligne = next(x for x in r.json()['resultats'] if x['partenaire_id'] == p2.id)
        ok('ville normalisee (majuscules) -> localite exacte', ligne['localite'] and ligne['localite']['id'] == loc_kong_qa.id, ligne)
        ok('quartier proche -> statut exact (normalisation tirets/casse)', ligne['statut'] == 'exact', ligne)
        p3_user = utilisateur(None, 't_geo_p3', 'partenaire')
        p3 = ProfilPartenaire.objects.create(user=p3_user, plan=plan, nom_commerce='Prop QA',
                                             type_partenaire='commercant', departement=dep_ferke,
                                             ville=loc_ferke_qa.nom, quartier='Quartier QA ' + uid + ' x')
        r = get(url_r + '?statut=tous', superadmin)
        ligne3 = next(x for x in r.json()['resultats'] if x['partenaire_id'] == p3.id)
        ok('quartier avec ecart -> proposition (score >= 0.85)',
           ligne3['statut'] == 'proposition' and ligne3['propositions']['quartiers']
           and ligne3['propositions']['quartiers'][0]['score'] >= 0.85, ligne3)
        r = send('post', f'{url_r}{p3.id}/', {'localite_id': loc_kong_qa.id, 'quartier_id': q_ferke.id}, superadmin)
        ok('application : quartier hors localite choisie -> 400 (coherence)', r.status_code == 400, r.content)
        r = send('post', f'{url_r}{p3.id}/', {'localite_id': loc_ferke_qa.id}, admin_sans)
        ok('application sans capacite -> 403', r.status_code == 403, r.content)
        r = send('post', f'{url_r}{p3.id}/', {}, superadmin)
        ok('application sans localite -> 400', r.status_code == 400, r.content)
        r = send('post', f'{url_r}{p3.id}/', {'localite_id': 'abc'}, superadmin)
        ok('localite non numerique -> 400', r.status_code == 400, r.content)
        r = send('post', f'{url_r}{p2.id}/', {'localite_id': loc_kong_qa.id, 'quartier_id': q_kong.id}, superadmin)
        ok('application coherente -> 200', r.status_code == 200, r.content)
        p2.refresh_from_db()
        ok('application : localite/quartier ecrits et textes synchronises',
           p2.localite_id == loc_kong_qa.id and p2.quartier_geo_id == q_kong.id
           and p2.ville == loc_kong_qa.nom and p2.quartier == q_kong.nom, (p2.ville, p2.quartier))
        ok('application : journalisee',
           JournalModeration.objects.filter(cible=p2_user,
               action=JournalModeration.Action.GEO_RAPPROCHEMENT_PARTENAIRE).exists())
        ok('application : partenaire ne figure plus dans les non rapproches',
           not any(x['partenaire_id'] == p2.id for x in get(url_r + '?statut=tous', superadmin).json()['resultats']))

        print('=== 8. COMMANDE : rapport puis --appliquer ===')
        p4_user = utilisateur(None, 't_geo_p4', 'partenaire')
        p4 = ProfilPartenaire.objects.create(user=p4_user, plan=plan, nom_commerce='Cmd QA',
                                             type_partenaire='commercant', departement=dep_ferke,
                                             ville=loc_ferke_qa.nom.replace(' ', '-').lower(),
                                             quartier=q_ferke.nom)
        sortie = io.StringIO()
        avant = ProfilPartenaire.objects.filter(localite__isnull=False).count()
        call_command('rapprocher_geographie_partenaires', stdout=sortie)
        ok('lecture seule : aucune ecriture',
           ProfilPartenaire.objects.filter(localite__isnull=False).count() == avant)
        ok('rapport : compteurs affiches', 'exact=' in sortie.getvalue() and 'aucun=' in sortie.getvalue(), sortie.getvalue()[:200])
        ok('rapport : le partenaire exact est liste', f'id={p4.id}' in sortie.getvalue())
        sortie = io.StringIO()
        call_command('rapprocher_geographie_partenaires', '--appliquer', stdout=sortie)
        p4.refresh_from_db()
        ok('--appliquer : partenaire exact rapproche', p4.localite_id == loc_ferke_qa.id and p4.quartier_geo_id == q_ferke.id,
           (p4.localite_id, p4.quartier_geo_id))
        ok('--appliquer : sortie indique le nombre ecrit', 'rapproché(s)' in sortie.getvalue(), sortie.getvalue()[-120:])
        ok('--appliquer : proposition non ecrite',
           ProfilPartenaire.objects.get(pk=p3.id).localite_id is None)
        ok('--appliquer : journal (acteur null)',
           JournalModeration.objects.filter(cible=p4_user, acteur__isnull=True,
               action=JournalModeration.Action.GEO_RAPPROCHEMENT_PARTENAIRE).exists())

        print('=== 9. PARTENAIRE SANS DEPARTEMENT : aucun ===')
        p5_user = utilisateur(None, 't_geo_p5', 'partenaire')
        p5 = ProfilPartenaire.objects.create(user=p5_user, plan=plan, nom_commerce='Sans dep QA',
                                             type_partenaire='commercant', ville='Ferké')
        r = get(url_r + '?statut=aucun', superadmin)
        ok('sans departement -> aucun', any(x['partenaire_id'] == p5.id for x in r.json()['resultats']))
        ligne5 = next(x for x in r.json()['resultats'] if x['partenaire_id'] == p5.id)
        ok('sans departement : departement_id = null, departement_nom vide',
           ligne5['departement_id'] is None and ligne5['departement_nom'] == '', ligne5)
        tous = get(url_r + '?statut=tous', superadmin).json()['resultats']
        ligne3 = next(x for x in tous if x['partenaire_id'] == p3.id)
        ok('avec departement : departement_id = id du departement',
           ligne3['departement_id'] == dep_ferke.id and ligne3['departement_nom'] == dep_ferke.nom, ligne3)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
