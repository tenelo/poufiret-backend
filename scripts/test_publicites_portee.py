"""Tests : portee des campagnes (MAX forfait/choisie), fin_diffusion dans les
reponses d'affichage, portee_forfait dans le profil partenaire.

Execution (tout est annule a la fin, aucune donnee ni fichier conserve) :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_publicites_portee.py
"""
import io
import json
import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework_simplejwt.tokens import AccessToken

from apps.publicites.models import FormulePublicite, Publicite
from apps.publicites.serializers import PubliciteListSerializer
from apps.users.models import ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
NB_OK = 0


class Rollback(Exception):
    pass


def ok(libelle, condition, detail=''):
    global NB_OK
    print(('OK   ' if condition else 'FAIL '), libelle, '' if condition else detail)
    assert condition, f'{libelle} {detail}'
    NB_OK += 1


def entetes(user):
    return {'HTTP_AUTHORIZATION': f'Bearer {AccessToken.for_user(user)}',
            'HTTP_HOST': HOST}


def png():
    tampon = io.BytesIO()
    Image.new('RGB', (40, 40), (200, 30, 30)).save(tampon, format='PNG')
    return SimpleUploadedFile('pub.png', tampon.getvalue(), content_type='image/png')


dossier_media = tempfile.mkdtemp(prefix='test_portee_')
avant = Publicite.objects.count()
try:
    with override_settings(MEDIA_ROOT=dossier_media), transaction.atomic():
        c = Client()
        pa = ProfilPartenaire.objects.get(id=2)   # Salon Awa  : forfait Basique = DEPARTEMENT
        pb = ProfilPartenaire.objects.get(id=1)   # Business Center : forfait Premium = REGION
        ok('donnees de depart', pa.portee == 'departement' and pb.portee == 'region',
           (pa.portee, pb.portee))
        ua, ub = pa.user, pb.user
        formule = FormulePublicite.objects.get(nom='Découverte')

        def creer(user, portee=None):
            corps = {'formule': str(formule.id), 'titre': 'Test portee',
                     'image_couverture': png()}
            if portee is not None:
                corps['portee'] = portee
            return c.post('/api/v1/publicites/mes-publicites/', corps,
                          secure=True, **entetes(user))

        def effective(reponse):
            return Publicite.objects.get(id=reponse.json()['id']).portee_effective

        print('\n=== 1a. CREATION, forfait DEPARTEMENT (partenaire 2) ===')
        r = creer(ua, 'departement')
        ok('portee=departement -> 201', r.status_code == 201, r.content)
        ok('   portee stockee/effective = departement',
           r.json()['portee'] == 'departement' and effective(r) == 'departement')
        r = creer(ua)
        ok('portee absente -> 201', r.status_code == 201, r.content)
        ok('   portee effective = departement (forfait)', effective(r) == 'departement')
        r = creer(ua, 'region')
        ok('portee=region -> 201', r.status_code == 201, r.content)
        ok('   portee effective = region', r.json()['portee'] == 'region' and effective(r) == 'region')
        r = creer(ua, 'district')
        ok('portee=district -> 201 (superieure : comportement inchange)',
           r.status_code == 201 and effective(r) == 'district', r.content)
        nb = Publicite.objects.filter(partenaire=pa).count()
        ok('2e et 3e campagnes du meme partenaire : %d campagnes creees, aucune limite' % nb, nb >= 4)
        ok('statut inchange = brouillon', r.json()['statut'] == 'brouillon')

        print('\n=== 1b. CREATION, forfait REGION (partenaire 1) : le cas du bug ===')
        r = creer(ub, 'departement')
        ok('portee=departement -> 201 (etait 400 avant correction)', r.status_code == 201, r.content)
        ok('   portee stockee = region (MAX), effective = region',
           r.json()['portee'] == 'region' and effective(r) == 'region', r.json())
        r = creer(ub, 'region')
        ok('portee=region -> 201, region', r.status_code == 201 and effective(r) == 'region', r.content)
        r = creer(ub)
        ok('portee absente -> 201, region (forfait)', r.status_code == 201 and effective(r) == 'region', r.content)
        r = creer(ub, 'district')
        ok('portee=district -> 201, district', r.status_code == 201 and effective(r) == 'district', r.content)
        r = creer(ub, 'monde')
        ok('portee invalide -> 400 (validation de choix inchangee)', r.status_code == 400, r.content)

        print('\n=== 1c. RECONDUCTION ===')
        def terminee(profil):
            return Publicite.objects.create(
                partenaire=profil, formule=formule, titre='Ancienne',
                image_couverture='publicites/couvertures/x.jpg',
                portee='departement', statut=Publicite.Statut.TERMINEE)

        def reconduire(user, pub, portee=None):
            corps = {} if portee is None else {'portee': portee}
            return c.post(f'/api/v1/publicites/mes-publicites/{pub.id}/reconduire/', corps,
                          secure=True, **entetes(user))

        ta = terminee(pa)
        r = reconduire(ua, ta, 'departement')
        ok('forfait departement, portee=departement -> 201, departement',
           r.status_code == 201 and effective(r) == 'departement', r.content)
        r = reconduire(ua, ta)
        ok('forfait departement, portee absente -> 201, departement',
           r.status_code == 201 and effective(r) == 'departement', r.content)
        r = reconduire(ua, ta, 'region')
        ok('forfait departement, portee=region -> 201, region',
           r.status_code == 201 and r.json()['portee'] == 'region' and effective(r) == 'region', r.content)
        ok('2e et 3e reconductions de la meme pub -> 201 (3 faites)',
           Publicite.objects.filter(partenaire=pa, titre='Ancienne', statut='brouillon').count() == 3)
        tb = terminee(pb)
        r = reconduire(ub, tb, 'departement')
        ok('forfait region, portee=departement -> 201, region (MAX)',
           r.status_code == 201 and effective(r) == 'region', r.content)
        r = reconduire(ub, tb)
        ok('forfait region, portee absente (ancienne = departement) -> 201, region',
           r.status_code == 201 and effective(r) == 'region', r.content)
        r = reconduire(ub, tb, 'district')
        ok('forfait region, portee=district -> 201, district',
           r.status_code == 201 and effective(r) == 'district', r.content)
        r = reconduire(ub, tb, 'monde')
        ok('portee invalide -> 400', r.status_code == 400, r.content)
        ok('ancienne pub jamais modifiee (reste terminee, departement)',
           Publicite.objects.get(id=ta.id).statut == 'terminee'
           and Publicite.objects.get(id=ta.id).portee == 'departement')

        print('\n=== 2. fin_diffusion dans carrousel / bandeau-bas / page publicites ===')
        Publicite.objects.filter(statut='active').update(statut='terminee')   # (annule a la fin)
        exclusif = FormulePublicite.objects.get(nom='Exclusif')
        maintenant = timezone.now()
        fin = maintenant + timedelta(days=30)
        pub = Publicite.objects.create(
            partenaire=pa, formule=exclusif, titre='Pub active test',
            image_couverture='publicites/couvertures/x.jpg', statut='active',
            debut_diffusion=maintenant - timedelta(minutes=1), fin_diffusion=fin)
        anciennes = {'id', 'titre', 'image_couverture', 'partenaire_id',
                     'duree_affichage_secondes', 'priorite'}
        hote = {'HTTP_HOST': HOST}
        for nom, url, cle in (
                ('carrousel', '/api/v1/publicites/carrousel/', 'publicites'),
                ('page publicites', '/api/v1/publicites/', 'publicites'),
                ('bandeau-bas', '/api/v1/publicites/bandeau-bas/', 'publicite')):
            r = c.get(url, secure=True, **hote)
            donnees = r.json()[cle]
            element = donnees[0] if isinstance(donnees, list) else donnees
            ok(f'{nom} : 200 et pub presente', r.status_code == 200 and element and element['id'] == str(pub.id), r.content)
            ok(f'{nom} : fin_diffusion ISO 8601 = {element["fin_diffusion"]}',
               element['fin_diffusion'] == PubliciteListSerializer(pub).data['fin_diffusion']
               and 'T' in element['fin_diffusion'])
            ok(f'{nom} : aucun champ retire/renomme (anciens champs tous presents)',
               anciennes <= set(element) and set(element) - anciennes == {'fin_diffusion'}, set(element))
        # Aucune requete SQL supplementaire : meme nombre avec et sans le champ.
        url = '/api/v1/publicites/carrousel/'
        c.get(url, secure=True, **hote)
        with CaptureQueriesContext(connection) as avec:
            c.get(url, secure=True, **hote)
        champs = PubliciteListSerializer.Meta.fields
        PubliciteListSerializer.Meta.fields = [f for f in champs if f != 'fin_diffusion']
        try:
            c.get(url, secure=True, **hote)
            with CaptureQueriesContext(connection) as sans:
                c.get(url, secure=True, **hote)
        finally:
            PubliciteListSerializer.Meta.fields = champs
        ok(f'requetes SQL carrousel : {len(avec)} avec le champ = {len(sans)} sans', len(avec) == len(sans))

        print('\n=== 3. portee_forfait dans GET /auth/mon-profil-partenaire/ ===')
        r = c.get('/api/v1/auth/mon-profil-partenaire/', secure=True, **entetes(ua))
        ok('partenaire forfait departement -> portee_forfait = departement',
           r.status_code == 200 and r.json()['portee_forfait'] == 'departement', r.content)
        cles_a = set(r.json())
        r = c.get('/api/v1/auth/mon-profil-partenaire/', secure=True, **entetes(ub))
        ok('partenaire forfait region -> portee_forfait = region', r.json()['portee_forfait'] == 'region', r.content)
        r = c.patch('/api/v1/auth/mon-profil-partenaire/', json.dumps({'portee_forfait': 'district', 'description': 'x'}),
                    content_type='application/json', secure=True, **entetes(ub))
        ok('lecture seule : PATCH portee_forfait=district ignore (reste region)',
           r.status_code == 200 and r.json()['portee_forfait'] == 'region'
           and ProfilPartenaire.objects.get(id=1).plan.portee == 'region', r.content)
        ok('ajout uniquement : les autres champs du profil sont toujours la',
           {'id', 'nom_commerce', 'plan_libelle', 'latitude', 'longitude', 'departement'} <= cles_a)

        print(f'\n=== {NB_OK} verifications reussies ===')
        raise Rollback('annulation volontaire')
except Rollback as e:
    print('Rollback effectue :', e)
finally:
    shutil.rmtree(dossier_media, ignore_errors=True)

assert Publicite.objects.count() == avant, 'des donnees de test ont persiste !'
print('Aucune donnee persistee (publicites : %d avant/apres), dossier media temporaire supprime.' % avant)
