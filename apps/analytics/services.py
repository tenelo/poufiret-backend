from django.utils import timezone


def enregistrer_vue_dans_profil(utilisateur, article):
    """Met à jour le ProfilNavigation après une vue d'article (au fil de l'eau)."""
    if not utilisateur or not utilisateur.is_authenticated:
        return
    from .views import _profil
    profil = _profil(utilisateur)
    profil.nb_articles_vus_mois += 1
    slug_cat = article.categorie.slug if article.categorie_id else 'sans_categorie'
    compteurs = profil.categories_consultees or {}
    compteurs[slug_cat] = compteurs.get(slug_cat, 0) + 1
    profil.categories_consultees = compteurs
    profil.derniere_activite = timezone.now()
    profil.save()
