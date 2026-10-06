"""Tests : image de catégorie dans l'endpoint public (grille et sous-catégories).
Clé "image" présente partout : URL absolue si image, null sinon ; image_couverture
conservée ; aucune requête SQL supplémentaire liée à l'image ; upload admin optimisé
(redimensionné, via ImagesOptimiseesMixin).

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_categories_image_publique.py
"""
import io, uuid
from django.db import connection, transaction
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.test.utils import CaptureQueriesContext
from PIL import Image
from apps.catalog.models import Categorie
from apps.core.images import LARGEUR_MAX

HOST = 'poufiret.tenelo.cloud'
class Rollback(Exception): pass
NB = 0
def ok(l, c, d=''):
    global NB
    print(('OK   ' if c else 'FAIL '), l, '' if c else d)
    assert c, f'{l} {d}'
    NB += 1

def grille():
    r = Client().get('/api/v1/catalogue/categories/', secure=True, HTTP_HOST=HOST)
    return r

try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        print('=== 1. CLE image : grille et sous-categories ===')
        r = grille()
        ok('grille -> 200', r.status_code == 200, r.status_code)
        res = r.json()['results']
        ok('chaque categorie a la cle image', all('image' in c for c in res))
        ok('image_couverture conservee (aucun champ retire)', all('image_couverture' in c for c in res))
        sans = [c for c in res if not c['image_couverture']]
        ok('sans image -> image null', sans and all(c['image'] is None for c in sans))
        avec = [c for c in res if c['image_couverture']]
        ok('avec image -> image = URL absolue', avec and all(c['image'].startswith('http') and c['image'] == c['image_couverture'] for c in avec),
           avec[:1])

        print('=== 2. SOUS-CATEGORIES ===')
        parent = Categorie.objects.create(nom=f'QA Parent img {uid}', slug=f'qa-parent-img-{uid}', est_active=True)
        Categorie.objects.create(nom=f'QA Enfant img {uid}', slug=f'qa-enfant-img-{uid}', parent=parent, est_active=True)
        r = grille()
        racine = next(c for c in r.json()['results'] if c['id'] == parent.id)
        enfant = racine['enfants'][0]
        ok('sous-categorie : cle image presente, null sans image', 'image' in enfant and enfant['image'] is None, enfant)

        print('=== 3. AUCUNE REQUETE SUPPLEMENTAIRE LIEE A L IMAGE ===')
        # Meme endpoint, meme nombre de requetes qu'il y ait ou non des images :
        # on compare la grille actuelle à une grille dont l'image est retirée en mémoire.
        with CaptureQueriesContext(connection) as ctx_avec:
            grille()
        n_avec = len(ctx_avec.captured_queries)
        Categorie.objects.filter(image_couverture__isnull=False).update(image_couverture=None)
        with CaptureQueriesContext(connection) as ctx_sans:
            grille()
        n_sans = len(ctx_sans.captured_queries)
        ok('nombre de requetes identique avec / sans image', n_avec == n_sans, (n_avec, n_sans))

        print('=== 4. UPLOAD ADMIN OPTIMISE ===')
        buf = io.BytesIO()
        Image.new('RGB', (4000, 3000), (10, 120, 200)).save(buf, format='PNG')
        lourd = buf.getvalue()
        cat = Categorie(nom=f'QA Upload img {uid}', slug=f'qa-upload-img-{uid}')
        cat.image_couverture = SimpleUploadedFile('grand.png', lourd, content_type='image/png')
        cat.save()
        cat.refresh_from_db()
        with cat.image_couverture.open('rb') as f:
            stocke = Image.open(io.BytesIO(f.read()))
            largeur = stocke.size[0]
        ok('image redimensionnee (largeur <= LARGEUR_MAX)', largeur <= LARGEUR_MAX, largeur)
        ok('fichier stocke plus leger que l original', cat.image_couverture.size < len(lourd),
           (cat.image_couverture.size, len(lourd)))
        r = grille()
        cle = next(c for c in r.json()['results'] if c['id'] == cat.id) if any(
            c['id'] == cat.id for c in r.json()['results']) else None
        ok('categorie uploadee visible avec image URL', cle is not None and cle['image'] and cle['image'].startswith('http'))
        cat.image_couverture.delete(save=False)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
