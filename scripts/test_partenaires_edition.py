"""Tests : fiche partenaire éditable par l'admin (GET/PATCH .../edition/).
Droits (creer_partenaire, super-admin), chaque groupe de champs, images
(ajout, remplacement, retrait), cohérence géographique (400), catégories
(remplacement, principale), changement de type (rattachement P1 non effacé),
champs non modifiables ignorés, journal, réponse, annuaire et vitrine.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_partenaires_edition.py
"""
import io, json, uuid
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from django.contrib.gis.geos import Point
from PIL import Image
from rest_framework_simplejwt.tokens import AccessToken
from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.catalog.models import Categorie, PartenaireCategorie
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

def cli(user):
    kw = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    return Client(), kw

def get(url, user):
    c, kw = cli(user); return c.get(url, **kw)

def patch_json(url, user, corps):
    c, kw = cli(user)
    return c.patch(url, json.dumps(corps), content_type='application/json', **kw)

def patch_multipart(url, user, data):
    c, kw = cli(user)
    return c.patch(url, encode_multipart(BOUNDARY, data), content_type=MULTIPART_CONTENT, **kw)

def png(nom):
    buf = io.BytesIO(); Image.new('RGB', (2, 2), (200, 0, 0)).save(buf, format='PNG')
    return SimpleUploadedFile(nom, buf.getvalue(), content_type='image/png')

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        ferke = Departement.objects.get(nom='Ferké')
        kong = Departement.objects.get(nom='Kong')
        loc_f = Localite.objects.create(nom=f'Edit Ferke {uid}', departement=ferke)
        loc_k = Localite.objects.create(nom=f'Edit Kong {uid}', departement=kong)
        quart_f = Quartier.objects.create(nom=f'Edit Q {uid}', localite=loc_f)
        quart_k = Quartier.objects.create(nom=f'Edit Qk {uid}', localite=loc_k)
        cat_resto = Categorie.objects.get(nom='Restaurants')
        cat_boul = Categorie.objects.get(nom='Boulangerie & Pâtisserie')
        cat_bout = Categorie.objects.get(nom='Boutiques & Commerce')

        super_ = utilisateur('t_ed_super', role='admin', staff=True, superuser=True)
        sans = utilisateur('t_ed_sans', role='admin', staff=True)
        PermissionsAdmin.objects.create(admin=sans)
        avec = utilisateur('t_ed_avec', role='admin', staff=True)
        PermissionsAdmin.objects.create(admin=avec, creer_partenaire=True)

        pu = utilisateur('t_ed_part', role='partenaire')
        tel_initial = pu.telephone
        prof = ProfilPartenaire.objects.create(user=pu, plan=plan, nom_commerce=f'Edit QA {uid}',
            type_partenaire='commercant', statut='actif', est_visible=True, departement=ferke,
            localisation=Point(-5.5, 9.4, srid=4326), secteur='Centre', telephone_pro='0700000000')
        PartenaireCategorie.objects.get_or_create(partenaire=prof, categorie=cat_bout, defaults={'est_principale': True})
        URL = f'/api/v1/administration/partenaires/{prof.id}/edition/'

        print('=== 1. DROITS ===')
        ok('admin sans capacite : GET 403', get(URL, sans).status_code == 403)
        ok('admin sans capacite : PATCH 403', patch_json(URL, sans, {'secteur': 'x'}).status_code == 403)
        ok('anonyme -> 401/403', get(URL, None).status_code in (401, 403))
        ok('super-admin -> 200', get(URL, super_).status_code == 200)
        ok('creer_partenaire -> 200', get(URL, avec).status_code == 200)

        print('=== 2. LECTURE (forme) ===')
        r = get(URL, avec)
        f = r.json()
        attendus = {'id', 'prenom', 'nom', 'nom_commerce', 'description', 'type_partenaire', 'type_partenaire_libelle',
                    'categories', 'departement', 'departement_nom', 'localite_id', 'localite_nom', 'quartier_id',
                    'quartier_nom', 'secteur', 'adresse', 'telephone_pro', 'whatsapp', 'email_pro', 'logo', 'photo_couverture'}
        ok('champs attendus', set(f) == attendus, set(f) ^ attendus)
        ok('categories : [{id, nom}]', f['categories'] == [{'id': cat_bout.id, 'nom': cat_bout.nom}], f['categories'])
        ok('departement_nom et logo null', f['departement_nom'] == 'Ferké' and f['logo'] is None)

        print('=== 3. TEXTES ET IDENTITE ===')
        r = patch_json(URL, avec, {'prenom': 'Awa', 'nom': 'Koné', 'nom_commerce': f'Edit QA renomme {uid}',
                                   'description': 'Nouvelle description', 'secteur': 'Nord',
                                   'adresse': 'Rue 12', 'telephone_pro': '0711223344', 'whatsapp': '0755667788',
                                   'email_pro': 'contact@example.com'})
        ok('PATCH textes -> 200', r.status_code == 200, r.content)
        d = r.json()
        ok('valeurs renvoyees', d['prenom'] == 'Awa' and d['nom'] == 'Koné' and d['secteur'] == 'Nord'
           and d['email_pro'] == 'contact@example.com' and d['adresse'] == 'Rue 12', d)
        pu.refresh_from_db(); prof.refresh_from_db()
        ok('User.first_name / last_name ecrits', pu.first_name == 'Awa' and pu.last_name == 'Koné')
        ok('description ecrite', prof.description == 'Nouvelle description')

        print('=== 4. PATCH PARTIEL, CHAMPS NON MODIFIABLES IGNORES ===')
        r = patch_json(URL, avec, {'telephone': '+2250799999999', 'latitude': 1.0, 'longitude': 1.0,
                                   'statut': 'suspendu', 'secteur': 'Sud'})
        ok('PATCH avec champs interdits -> 200 (ignores)', r.status_code == 200, r.content)
        pu.refresh_from_db(); prof.refresh_from_db()
        ok('numero de connexion inchange', pu.telephone == tel_initial)
        ok('position GPS inchangee', abs(prof.localisation.y - 9.4) < 1e-6)
        ok('statut inchange', prof.statut == 'actif')
        ok('secteur modifie malgre les champs ignores', prof.secteur == 'Sud')

        print('=== 5. CATEGORIES : remplacement, principale ===')
        r = patch_json(URL, avec, {'categories': [cat_resto.id, cat_bout.id]})
        ok('categories -> 200', r.status_code == 200, r.content)
        ok('ordre : premiere = principale',
           PartenaireCategorie.objects.get(partenaire=prof, categorie=cat_resto).est_principale is True
           and PartenaireCategorie.objects.get(partenaire=prof, categorie=cat_bout).est_principale is False)
        r = patch_json(URL, avec, {'categories': [cat_boul.id]})
        ok('remplacement : seules les nouvelles restent', set(PartenaireCategorie.objects.filter(
            partenaire=prof).values_list('categorie_id', flat=True)) == {cat_boul.id})
        r = patch_json(URL, avec, {'categories': [cat_bout.id, 999999]})
        ok('categorie inconnue -> 400 details.categories', r.status_code == 400 and 'categories' in r.json()['details'], r.content)

        print('=== 6. CHANGEMENT DE TYPE : rattachement P1 conserve ===')
        patch_json(URL, avec, {'categories': [cat_bout.id]})
        r = patch_json(URL, avec, {'type_partenaire': 'boulanger'})
        ok('type change -> 200', r.status_code == 200 and r.json()['type_partenaire'] == 'boulanger', r.content)
        noms = {c['nom'] for c in r.json()['categories']}
        ok('categorie du nouveau type ajoutee automatiquement', cat_boul.nom in noms, noms)
        ok('categorie existante conservee', cat_bout.nom in noms, noms)
        patch_json(URL, avec, {'type_partenaire': 'commercant', 'categories': [cat_bout.id]})
        r = patch_json(URL, avec, {'categories': [cat_resto.id], 'type_partenaire': 'boulanger'})
        noms = {c['nom'] for c in r.json()['categories']}
        ok('categories + type dans le meme PATCH : la correspondance n est pas effacee',
           noms == {cat_resto.nom, cat_boul.nom, cat_bout.nom} or noms == {cat_resto.nom, cat_boul.nom}, noms)
        ok('type invalide -> 400', patch_json(URL, avec, {'type_partenaire': 'zzz'}).status_code == 400)
        ok('email invalide -> 400 details.email_pro', 'email_pro' in patch_json(
            URL, avec, {'email_pro': 'pas-un-mail'}).json()['details'])

        print('=== 7. COHERENCE GEOGRAPHIQUE (400) ===')
        r = patch_json(URL, avec, {'localite_id': loc_k.id})
        ok('localite hors departement -> 400 details.localite_id',
           r.status_code == 400 and 'localite_id' in r.json()['details'], r.content)
        r = patch_json(URL, avec, {'localite_id': loc_f.id, 'quartier_id': quart_k.id})
        ok('quartier hors localite -> 400 details.quartier_id',
           r.status_code == 400 and 'quartier_id' in r.json()['details'], r.content)
        patch_json(URL, avec, {'localite_id': loc_f.id})
        r = patch_json(URL, avec, {'departement': kong.id})
        ok('departement change sans localite compatible -> 400',
           r.status_code == 400 and 'localite_id' in r.json()['details'], r.content)
        r = patch_json(URL, avec, {'localite_id': loc_f.id, 'quartier_id': quart_f.id})
        ok('localite + quartier coherents -> 200', r.status_code == 200, r.content)
        prof.refresh_from_db()
        ok('textes ville/quartier synchronises', prof.ville == loc_f.nom and prof.quartier == quart_f.nom)
        ok('reponse : localite_nom / quartier_nom', r.json()['localite_nom'] == loc_f.nom and r.json()['quartier_nom'] == quart_f.nom)
        r = patch_json(URL, avec, {'localite_id': None, 'quartier_id': None})
        ok('localite et quartier effaces -> 200', r.status_code == 200 and r.json()['localite_id'] is None, r.content)
        patch_json(URL, avec, {'localite_id': loc_f.id})

        print('=== 8. IMAGES : ajout, remplacement, retrait ===')
        r = patch_multipart(URL, avec, {'logo': png('l1.png')})
        ok('ajout logo (multipart) -> 200', r.status_code == 200, r.content)
        url1 = r.json()['logo']
        ok('logo renvoye en URL', url1 and 'partenaires' in url1, url1)
        r = patch_multipart(URL, avec, {'logo': png('l2.png')})
        url2 = r.json()['logo']
        ok('remplacement logo : nouvelle URL', url2 and url2 != url1, (url1, url2))
        r = patch_multipart(URL, avec, {'photo_couverture': png('c1.png')})
        ok('ajout couverture -> 200', r.status_code == 200 and r.json()['photo_couverture'], r.content)
        r = patch_multipart(URL, avec, {'supprimer_couverture': 'true'})
        ok('supprimer_couverture -> couverture null', r.status_code == 200 and r.json()['photo_couverture'] is None, r.content)
        ok('logo conserve quand on retire la couverture', r.json()['logo'] == url2)
        r = patch_json(URL, avec, {'supprimer_logo': True})
        ok('supprimer_logo (JSON) -> logo null', r.status_code == 200 and r.json()['logo'] is None, r.content)

        print('=== 9. JOURNAL ===')
        avant = JournalModeration.objects.filter(cible=pu, action=JournalModeration.Action.PARTENAIRE_EDITION).count()
        patch_json(URL, avec, {'secteur': 'Sud'})
        ok('aucun changement -> pas de journal', JournalModeration.objects.filter(
            cible=pu, action=JournalModeration.Action.PARTENAIRE_EDITION).count() == avant)
        patch_json(URL, avec, {'whatsapp': '0700001111'})
        entree = JournalModeration.objects.filter(cible=pu, action=JournalModeration.Action.PARTENAIRE_EDITION).order_by('-cree_le').first()
        ok('journal : acteur admin', entree is not None and entree.acteur_id == avec.id)
        ok('journal : ancien -> nouveau pour texte court', entree and 'whatsapp (0755667788 → 0700001111)' in entree.motif, entree and entree.motif)

        print('=== 10. ANNUAIRE PUBLIC ET VITRINE ===')
        r = get(f'/api/v1/catalogue/categories/{cat_boul.slug}/partenaires/', None)
        ligne = next((x for x in r.json() if x['id'] == prof.id), None) if r.status_code == 200 else None
        ok('annuaire categorie : partenaire present', ligne is not None, r.status_code)
        ok('annuaire : localite_nom, quartier_nom, secteur ajoutes',
           ligne is not None and {'localite_nom', 'quartier_nom', 'secteur'} <= set(ligne)
           and ligne['localite_nom'] == loc_f.nom and ligne['secteur'] == 'Sud', ligne)
        r = get(f'/api/v1/auth/partenaires/{prof.id}/', None)
        ok('vitrine : secteur, localite_nom, quartier_nom',
           r.status_code == 200 and r.json()['secteur'] == 'Sud' and r.json()['localite_nom'] == loc_f.nom, r.content[:200])

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
