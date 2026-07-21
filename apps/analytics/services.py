from django.utils import timezone


def _profil_utilisateur(utilisateur):
    if not utilisateur or not utilisateur.is_authenticated:
        return None
    from .views import _profil
    return _profil(utilisateur)


def enregistrer_vue_dans_profil(utilisateur, article):
    """Consultation de la fiche detail d'un article.

    N'incremente que le compteur d'articles : la categorie est comptee
    separement, a l'entree dans le catalogue (voir enregistrer_visite_categorie).
    """
    profil = _profil_utilisateur(utilisateur)
    if profil is None:
        return
    profil.nb_articles_vus_mois += 1
    profil.derniere_activite = timezone.now()
    profil.save()


def enregistrer_visite_categorie(utilisateur, slug_categorie):
    """Entree dans le catalogue d'une categorie.

    Une visite = +1, quel que soit le nombre d'articles ouverts ensuite.
    Revenir a l'accueil puis recliquer la categorie compte une nouvelle visite.
    """
    profil = _profil_utilisateur(utilisateur)
    if profil is None or not slug_categorie:
        return
    compteurs = profil.categories_consultees or {}
    compteurs[slug_categorie] = compteurs.get(slug_categorie, 0) + 1
    profil.categories_consultees = compteurs
    profil.derniere_activite = timezone.now()
    profil.save()
