"""Optimisation des images a l'enregistrement.

Une affiche de 2 Mo met plusieurs secondes a charger en 3G : le client
voit une page vide et s'en va. On redimensionne et on recompresse a
l'upload, sans rien demander au partenaire — il envoie ce qu'il a.
"""
from io import BytesIO

from django.core.files.uploadedfile import InMemoryUploadedFile

try:
    from PIL import Image, ImageOps
except ImportError:  # Pillow absent : on laisse passer l'original
    Image = None


# Un ecran de telephone affiche ~500px de large ; 1200 laisse de la
# marge pour les tablettes sans transporter de pixels inutiles.
LARGEUR_MAX = 1200
HAUTEUR_MAX = 1400
QUALITE = 85


def _a_de_la_transparence(image):
    """Vrai si l'image utilise vraiment la transparence.

    Beaucoup de photos sont enregistrees en RGBA sans le moindre pixel
    transparent : les garder en PNG couterait cinq fois le poids d'un
    JPEG pour rien.
    """
    if image.mode not in ('RGBA', 'LA', 'P'):
        return False
    if image.mode == 'P':
        if 'transparency' not in image.info:
            return False
        image = image.convert('RGBA')
    alpha = image.getchannel('A')
    minimum, _ = alpha.getextrema()
    return minimum < 255


def optimiser_image(fichier, largeur_max=LARGEUR_MAX,
                    hauteur_max=HAUTEUR_MAX, qualite=QUALITE):
    """Redimensionne et recompresse une image uploadee.

    Retourne le fichier optimise, ou l'original si le traitement echoue
    (une image un peu lourde vaut mieux qu'un upload refuse).

    La transparence est preservee : un logo converti en JPEG gagnerait
    un fond blanc disgracieux, on le garde donc en PNG.
    """
    if Image is None or not fichier:
        return fichier

    try:
        image = Image.open(fichier)
        # Respecte l'orientation EXIF des photos prises au telephone.
        image = ImageOps.exif_transpose(image)

        transparent = _a_de_la_transparence(image)
        original = image.size

        # Ne jamais agrandir : thumbnail ne reduit que si necessaire.
        image.thumbnail((largeur_max, hauteur_max), Image.LANCZOS)

        tampon = BytesIO()
        if transparent:
            if image.mode == 'P':
                image = image.convert('RGBA')
            image.save(tampon, format='PNG', optimize=True)
            extension, type_mime = 'png', 'image/png'
        else:
            image = image.convert('RGB')
            image.save(tampon, format='JPEG', quality=qualite, optimize=True,
                       progressive=True)
            extension, type_mime = 'jpg', 'image/jpeg'

        taille = tampon.tell()
        # Si le traitement n'apporte rien, on garde l'original. La taille
        # d'origine n'est pas toujours exposee (fichier ouvert depuis le
        # disque) : dans ce cas on garde la version optimisee.
        taille_origine = getattr(fichier, 'size', None)
        if taille_origine is None:
            try:
                position = fichier.tell()
                fichier.seek(0, 2)
                taille_origine = fichier.tell()
                fichier.seek(position)
            except Exception:
                taille_origine = None
        if (image.size == original and taille_origine
                and taille >= taille_origine):
            fichier.seek(0)
            return fichier

        tampon.seek(0)
        nom = getattr(fichier, 'name', 'image')
        base = nom.rsplit('.', 1)[0] if '.' in nom else nom
        return InMemoryUploadedFile(
            tampon, None, f'{base}.{extension}', type_mime, taille, None,
        )
    except Exception:
        try:
            fichier.seek(0)
        except Exception:
            pass
        return fichier


class ImagesOptimiseesMixin:
    """Optimise les champs images d'un modele avant enregistrement.

    Utilisation : declarer `champs_images = ('image_couverture', 'logo')`
    sur le modele et heriter de ce mixin avant models.Model.
    """
    champs_images = ()

    def save(self, *args, **kwargs):
        for nom in self.champs_images:
            champ = getattr(self, nom, None)
            # _committed=False : fichier fraichement affecte, pas encore
            # ecrit sur le disque. C'est le seul moment ou l'optimiser a
            # du sens (sinon on retraiterait a chaque save()).
            if champ and getattr(champ, '_committed', True) is False:
                setattr(self, nom, optimiser_image(champ.file))
        return super().save(*args, **kwargs)
