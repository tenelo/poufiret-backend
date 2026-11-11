"""Tests : l'admin crée et reconduit une pub POUR un partenaire (capacité
gerer_pubs_partenaires). Création active immédiate aux dates choisies,
date_fin par défaut, dates invalides, reconduction admin (copie active,
originale intacte, pub non terminée refusée), reconduction partenaire
inchangée (brouillon), quota (409), règlement payée / offerte (revenus
estimés), droits, recherche de partenaires, aucun champ nouveau côté
partenaire, journal.

Données propres ; tout est annulé à la fin (aucune donnée ni fichier conservé).
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_publicites_admin_partenaire.py
"""
import io
import shutil
import tempfile
import uuid
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client
from django.test.utils import override_settings
from django.utils import timezone
from PIL import Image
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.publicites.models import FormulePublicite, ImagePublicite, Publicite
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
# Limitation de débit DRF désactivée pour ce script (même mécanisme que les autres scripts).
from unittest import mock as _mock_debit
from rest_framework.views import APIView as _APIViewDebit
_mock_debit.patch.object(_APIViewDebit, 'get_throttles', return_value=[]).start()
NB_OK = 0


class Rollback(Exception):
    pass


def ok(libelle, condition, detail=''):
    global NB_OK
    print(('OK   ' if condition else 'FAIL '), libelle, '' if condition else detail)
    assert condition, f'{libelle} {detail}'
    NB_OK += 1


def entetes(user):
    return {'HTTP_AUTHORIZATION': f'Bearer {AccessToken.for_user(user)}', 'HTTP_HOST': HOST}


def png():
    tampon = io.BytesIO()
    Image.new('RGB', (40, 40), (30, 120, 200)).save(tampon, format='PNG')
    return SimpleUploadedFile('pub.png', tampon.getvalue(), content_type='image/png')


def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel


def compte(nom, role='admin', staff=False, superuser=False):
    return User.objects.create(telephone=telephone_libre(), username=f'{nom}_{uuid.uuid4().hex[:5]}',
                               role=role, is_staff=staff, is_superuser=superuser, est_verifie=True)


dossier_media = tempfile.mkdtemp(prefix='test_pub_admin_')
avant_pubs = Publicite.objects.count()
avant_journal = JournalModeration.objects.count()
try:
    with override_settings(MEDIA_ROOT=dossier_media), transaction.atomic():
        c = Client()
        uid = uuid.uuid4().hex[:6]
        aujourdhui = timezone.localdate()
        plan = PlanAbonnement.objects.filter(portee='departement').first() or PlanAbonnement.objects.first()
        p_user = compte('t_pubadm_part', role='partenaire')
        partenaire = ProfilPartenaire.objects.create(
            user=p_user, plan=plan, nom_commerce=f'Boutique Pub QA {uid}', type_partenaire='commercant',
            statut='actif', est_visible=True)
        autre_user = compte('t_pubadm_autre', role='partenaire')
        ProfilPartenaire.objects.create(user=autre_user, plan=plan, nom_commerce=f'Autre QA {uid}',
                                        type_partenaire='commercant', statut='actif', est_visible=True)
        formule = FormulePublicite.objects.create(
            nom=f'Formule QA {uid}', prix=7000, duree_jours=10, quota_partenaires=50,
            types_affichage=['carrousel'], video_autorisee=False)
        exclu = FormulePublicite.objects.create(
            nom=f'Exclu QA {uid}', prix=90000, duree_jours=5, quota_partenaires=1,
            types_affichage=['carrousel'])

        superadmin = compte('t_pubadm_super', staff=True, superuser=True)
        admin_avec = compte('t_pubadm_avec', staff=True)
        PermissionsAdmin.objects.create(admin=admin_avec, gerer_pubs_partenaires=True)
        admin_sans = compte('t_pubadm_sans', staff=True)
        PermissionsAdmin.objects.create(admin=admin_sans, offrir_campagne=False, valider_publicite=True)
        admin_stats = compte('t_pubadm_stats', staff=True)
        PermissionsAdmin.objects.create(admin=admin_stats, voir_stats=True)

        CREER = '/api/v1/publicites/admin/creer/'

        def creer(user, **champs):
            corps = {'partenaire': partenaire.id, 'formule': str(formule.id), 'titre': 'Pub admin QA',
                     'description': 'Créée par l admin', 'image_couverture': png(),
                     'date_debut': str(aujourdhui), 'reglement': 'payee'}
            corps.update(champs)
            corps = {k: v for k, v in corps.items() if v is not None}
            return c.post(CREER, corps, secure=True, **entetes(user))

        def revenus():
            r = c.get(f'/api/v1/publicites/admin/statistiques/?du={aujourdhui}&au={aujourdhui + timedelta(days=60)}',
                      secure=True, **entetes(admin_stats))
            return r.json()['kpis']['revenus_estimes']

        print('=== 1. CAPACITE ===')
        r = c.get('/api/v1/administration/mes-permissions/', secure=True, **entetes(admin_avec))
        ok('mes-permissions expose gerer_pubs_partenaires (True)', r.status_code == 200
           and r.json()['capacites'].get('gerer_pubs_partenaires') is True, r.content)
        ok('defaut False', PermissionsAdmin._meta.get_field('gerer_pubs_partenaires').default is False
           and PermissionsAdmin.objects.get(admin=admin_sans).gerer_pubs_partenaires is False)

        print('=== 2. DROITS ===')
        ok('admin sans la capacite -> 403', creer(admin_sans).status_code == 403)
        ok('partenaire -> 403', creer(p_user).status_code == 403)
        ok('anonyme -> 401', c.post(CREER, {}, secure=True, HTTP_HOST=HOST).status_code == 401)
        revenus_avant = revenus()

        print('=== 3. CREATION : active immediatement, dates choisies ===')
        fin_choisie = aujourdhui + timedelta(days=3)
        r = creer(admin_avec, date_fin=str(fin_choisie), portee='region')
        ok('admin avec la capacite -> 201', r.status_code == 201, r.content)
        d = r.json()
        pub = Publicite.objects.get(id=d['id'])
        ok('statut active, debut maintenant (aujourd hui)', pub.statut == 'active' and d['statut'] == 'active'
           and abs((pub.debut_diffusion - timezone.now()).total_seconds()) < 60)
        ok('fin = date_fin choisie, incluse (23:59 locale)',
           timezone.localtime(pub.fin_diffusion).date() == fin_choisie
           and timezone.localtime(pub.fin_diffusion).hour == 23, pub.fin_diffusion)
        ok('portee = MAX(forfait, demandee) = region', pub.portee == 'region')
        ok('payee : est_faveur False, aucun paiement', pub.est_faveur is False and pub.paiement_id is None
           and d['reglement'] == 'payee')
        ok('trace : cree_par_admin', pub.cree_par_admin_id == admin_avec.id and d['cree_par_admin_id'] == admin_avec.id)
        ok('reponse admin : champs', {'id', 'partenaire_id', 'partenaire_nom', 'formule_id', 'formule_nom', 'titre',
           'image_couverture', 'portee', 'portee_effective', 'statut', 'debut_diffusion', 'fin_diffusion', 'reglement',
           'est_faveur', 'faveur_motif', 'cree_par_admin_id'} <= set(d), set(d))
        ok('journal pub_creee_admin', JournalModeration.objects.filter(
            action='pub_creee_admin', acteur=admin_avec, cible=p_user, motif__contains=str(pub.id)).exists())
        ok('payee comptee dans les revenus estimes (+7000)', revenus() == revenus_avant + 7000,
           (revenus_avant, revenus()))

        r = creer(superadmin, date_debut=str(aujourdhui + timedelta(days=5)), reglement='offerte')
        ok('super-admin -> 201, debut futur', r.status_code == 201, r.content)
        future = Publicite.objects.get(id=r.json()['id'])
        ok('debut futur = minuit local du jour choisi',
           timezone.localtime(future.debut_diffusion).date() == aujourdhui + timedelta(days=5)
           and timezone.localtime(future.debut_diffusion).hour == 0)
        ok('date_fin absente -> debut + duree_jours (10 j)',
           future.fin_diffusion - future.debut_diffusion == timedelta(days=10))
        ok('offerte : est_faveur, admin, motif par defaut', future.est_faveur
           and future.faveur_accordee_par_id == superadmin.id
           and future.faveur_motif == "Offerte par l'administration")
        ok('offerte : non comptee dans les revenus', revenus() == revenus_avant + 7000)
        r = creer(admin_avec, reglement='offerte', motif='Lancement')
        ok('offerte avec motif', r.status_code == 201
           and Publicite.objects.get(id=r.json()['id']).faveur_motif == 'Lancement', r.content)
        ok('pub future pas encore diffusee (carrousel)', str(future.id) not in {
            p['id'] for p in c.get('/api/v1/publicites/carrousel/', secure=True, HTTP_HOST=HOST).json()['publicites']})

        print('=== 4. VALIDATIONS ===')
        def erreur(r):
            return set(r.json().get('details', {})) if r.status_code == 400 else r.status_code
        ok('date_debut passee -> 400', erreur(creer(admin_avec, date_debut=str(aujourdhui - timedelta(days=1))))
           == {'date_debut'})
        ok('date_fin = date_debut -> 400', erreur(creer(admin_avec, date_fin=str(aujourdhui))) == {'date_fin'})
        ok('date_fin < date_debut -> 400', erreur(creer(admin_avec, date_debut=str(aujourdhui + timedelta(days=4)),
                                                         date_fin=str(aujourdhui + timedelta(days=2)))) == {'date_fin'})
        r = creer(admin_avec, reglement='gratuit')
        ok('reglement invalide -> 400 (message + details)', erreur(r) == {'reglement'} and r.json()['message'], r.content)
        ok('reglement absent -> 400', erreur(creer(admin_avec, reglement=None)) == {'reglement'})
        ok('date_debut absente -> 400', erreur(creer(admin_avec, date_debut=None)) == {'date_debut'})
        ok('partenaire absent -> 400', erreur(creer(admin_avec, partenaire=None)) == {'partenaire'})
        ok('partenaire inconnu -> 400', erreur(creer(admin_avec, partenaire=999999999)) == {'partenaire'})
        ok('image absente -> 400', erreur(creer(admin_avec, image_couverture=None)) == {'image_couverture'})
        FormulePublicite.objects.filter(pk=exclu.pk).update(est_active=False)
        ok('formule inactive -> 400', creer(admin_avec, formule=str(exclu.id)).status_code == 400)
        FormulePublicite.objects.filter(pk=exclu.pk).update(est_active=True)
        ok('aucune pub creee par les requetes refusees', Publicite.objects.filter(partenaire=partenaire).count() == 3)

        print('=== 5. QUOTA -> 409 ===')
        r = creer(admin_avec, formule=str(exclu.id))
        ok('1re pub Exclu (quota 1) -> 201', r.status_code == 201, r.content)
        nb = Publicite.objects.filter(formule=exclu).count()
        r = creer(admin_avec, formule=str(exclu.id))
        ok('2e pub Exclu -> 409, message du circuit normal', r.status_code == 409
           and r.json()['message'].startswith(f'Quota de la formule « {exclu.nom} » atteint (1/1')
           and 'Activation impossible' in r.json()['message'], r.content)
        ok('409 : rien cree (rollback)', Publicite.objects.filter(formule=exclu).count() == nb)

        print('=== 6. RECONDUCTION ADMIN ===')
        ancienne = Publicite.objects.create(
            partenaire=partenaire, formule=formule, titre='Ancienne QA', description='Desc ancienne',
            image_couverture='publicites/couvertures/ancienne.jpg', video='publicites/videos/v.mp4',
            portee='departement', statut='terminee', nb_impressions=42,
            debut_diffusion=timezone.now() - timedelta(days=20), fin_diffusion=timezone.now() - timedelta(days=10))
        ImagePublicite.objects.create(publicite=ancienne, image='publicites/images/g.jpg')
        etat_avant = Publicite.objects.filter(pk=ancienne.pk).values().get()
        RECONDUIRE = f'/api/v1/publicites/admin/{ancienne.id}/reconduire/'

        def reconduire(user, pub_id=None, **champs):
            corps = {'date_debut': str(aujourdhui), 'reglement': 'payee'}
            corps.update(champs)
            corps = {k: v for k, v in corps.items() if v is not None}
            url = f'/api/v1/publicites/admin/{pub_id or ancienne.id}/reconduire/'
            return c.post(url, corps, secure=True, **entetes(user))

        ok('admin sans capacite -> 403', reconduire(admin_sans).status_code == 403)
        ok('partenaire -> 403', reconduire(p_user).status_code == 403)
        r = reconduire(admin_avec, reglement='offerte', date_fin=str(aujourdhui + timedelta(days=7)))
        ok('reconduction admin -> 201', r.status_code == 201, r.content)
        d = r.json()
        copie = Publicite.objects.get(id=d['id'])
        ok('copie active, dates, offerte', copie.statut == 'active' and copie.est_faveur
           and timezone.localtime(copie.fin_diffusion).date() == aujourdhui + timedelta(days=7))
        ok('memes champs copies que cote partenaire', (copie.titre, copie.description, copie.image_couverture.name,
           copie.video.name, copie.portee, copie.formule_id) == ('Ancienne QA', 'Desc ancienne',
           'publicites/couvertures/ancienne.jpg', 'publicites/videos/v.mp4', 'departement', formule.id))
        ok('galerie non copiee, compteurs a zero', copie.images.count() == 0 and copie.nb_impressions == 0)
        ok('reconduite_depuis + cree_par_admin', d['reconduite_depuis'] == str(ancienne.id)
           and copie.cree_par_admin_id == admin_avec.id)
        ok('originale intacte', Publicite.objects.filter(pk=ancienne.pk).values().get() == etat_avant)
        ok('journal pub_reconduite_admin', JournalModeration.objects.filter(
            action='pub_reconduite_admin', acteur=admin_avec, motif__contains=str(ancienne.id)).exists())
        r = reconduire(superadmin, formule_id=str(exclu.id))
        ok('reconduction sur formule au quota atteint -> 409', r.status_code == 409, r.content)
        r = c.post(RECONDUIRE, {'date_debut': str(aujourdhui), 'reglement': 'payee',
                                'image_couverture': png(), 'portee': 'district'}, secure=True, **entetes(superadmin))
        ok('nouvelle image + portee facultatives', r.status_code == 201
           and Publicite.objects.get(id=r.json()['id']).portee == 'district'
           and Publicite.objects.get(id=r.json()['id']).image_couverture.name != ancienne.image_couverture.name, r.content)
        ok('formule inconnue -> 400 meme message que partenaire',
           reconduire(admin_avec, formule_id=str(uuid.uuid4())).json().get('message') == 'Formule introuvable ou inactive.')
        ok('date passee -> 400', reconduire(admin_avec, date_debut=str(aujourdhui - timedelta(days=2))).status_code == 400)
        r = reconduire(admin_avec, pub_id=copie.id)
        ok('pub non terminee -> 400', r.status_code == 400 and 'Seule une publicité terminée' in r.json()['message'],
           r.content)
        ok('pub inconnue -> 404', reconduire(admin_avec, pub_id=uuid.uuid4()).status_code == 404)

        print('=== 7. RECONDUCTION PARTENAIRE INCHANGEE ===')
        r = c.post(f'/api/v1/publicites/mes-publicites/{ancienne.id}/reconduire/', {}, secure=True, **entetes(p_user))
        ok('partenaire -> 201, toujours un brouillon', r.status_code == 201 and r.json()['statut'] == 'brouillon',
           r.content)
        ok('reponse partenaire : memes champs qu avant', set(r.json()) == {
            'id', 'formule', 'titre', 'description', 'image_couverture', 'video', 'portee', 'statut'}, set(r.json()))
        brouillon = Publicite.objects.get(id=r.json()['id'])
        ok('brouillon partenaire sans trace admin, ni dates, ni faveur', brouillon.cree_par_admin_id is None
           and brouillon.debut_diffusion is None and brouillon.est_faveur is False)
        ok('partenaire : pub non terminee -> 400 (inchange)', c.post(
            f'/api/v1/publicites/mes-publicites/{copie.id}/reconduire/', {}, secure=True,
            **entetes(p_user)).status_code == 400)
        ok('partenaire : portee invalide -> 400 (inchange)', c.post(
            f'/api/v1/publicites/mes-publicites/{ancienne.id}/reconduire/', {'portee': 'monde'}, secure=True,
            **entetes(p_user)).json().get('message') == 'Portée invalide.')

        print('=== 8. COTE PARTENAIRE : AUCUN CHAMP NOUVEAU ===')
        r = c.get('/api/v1/publicites/mes-publicites/', secure=True, **entetes(p_user))
        lignes = r.json()['results'] if isinstance(r.json(), dict) else r.json()
        ok('mes-publicites : pubs creees par l admin visibles', str(pub.id) in {x['id'] for x in lignes})
        ok('mes-publicites : aucun champ nouveau', all(set(x) == {
            'id', 'formule', 'titre', 'description', 'image_couverture', 'video', 'portee', 'statut'} for x in lignes),
           set(lignes[0]))
        ok('aucune mention de l admin dans la reponse', 'cree_par_admin' not in r.content.decode())

        print('=== 9. RECHERCHE DE PARTENAIRES ===')
        RECH = f'/api/v1/administration/partenaires/recherche/?q=Boutique Pub QA {uid}'
        r = c.get(RECH, secure=True, **entetes(admin_avec))
        ok('avec gerer_pubs_partenaires -> 200 et trouve', r.status_code == 200
           and [x['id'] for x in r.json()['resultats']] == [partenaire.id], r.content)
        admin_offrir = compte('t_pubadm_offrir', staff=True)
        PermissionsAdmin.objects.create(admin=admin_offrir, offrir_campagne=True)
        ok('avec offrir_campagne -> 200 (inchange)', c.get(RECH, secure=True, **entetes(admin_offrir)).status_code == 200)
        ok('sans aucune des deux -> 403', c.get(RECH, secure=True, **entetes(admin_sans)).status_code == 403)
        ok('partenaire -> 403', c.get(RECH, secure=True, **entetes(p_user)).status_code == 403)
        ok('gerer_pubs_partenaires ne donne pas offrir une campagne (faveur)', c.post(
            f'/api/v1/administration/publicites/{pub.id}/faveur/', {'motif': 'x'}, secure=True,
            **entetes(admin_avec)).status_code == 403)

        print(f'\n=== {NB_OK} verifications reussies ===')
        raise Rollback('annulation volontaire')
except Rollback as e:
    print('Rollback effectue :', e)
finally:
    shutil.rmtree(dossier_media, ignore_errors=True)

assert Publicite.objects.count() == avant_pubs, 'des publicites de test ont persiste !'
assert JournalModeration.objects.count() == avant_journal, 'des entrees de journal ont persiste !'
print('Aucune donnee persistee (publicites : %d, journal : %d avant/apres), dossier media temporaire supprime.'
      % (avant_pubs, avant_journal))
