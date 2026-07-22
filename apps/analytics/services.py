from django.utils import timezone


def _profil_utilisateur(utilisateur):
    if not utilisateur or not utilisateur.is_authenticated:
        return None
    from .views import _profil
    return _profil(utilisateur)


def enregistrer_vue_dans_profil(utilisateur, article):
    """Consultation de la fiche detail d'un article."""
    profil = _profil_utilisateur(utilisateur)
    if profil is None:
        return
    profil.nb_articles_vus_mois += 1
    profil.derniere_activite = timezone.now()
    profil.save()


def enregistrer_visite_categorie(utilisateur, slug_categorie):
    """Entree dans le catalogue d'une categorie (compteur par categorie)."""
    profil = _profil_utilisateur(utilisateur)
    if profil is None or not slug_categorie:
        return
    compteurs = profil.categories_consultees or {}
    compteurs[slug_categorie] = compteurs.get(slug_categorie, 0) + 1
    profil.categories_consultees = compteurs
    profil.derniere_activite = timezone.now()
    profil.save()


def enregistrer_vue_vitrine(utilisateur, partenaire, source='autre', avec_catalogue=True):
    """Consultation de la page d'un partenaire.

    Dans tous les cas : +1 sur le compteur public nb_vues du partenaire.
    Puis selon le type de la categorie d'origine :
      - avec catalogue (restaurant, hotel...) -> +1 nb_vues_catalogue_mois
      - sans catalogue (plombier, service...) -> +1 nb_articles_vus_mois
        (la fiche de service est comptee comme un article).
    """
    from django.db.models import F
    from apps.users.models import ProfilPartenaire
    from .models import VueVitrine

    utilisateur_reel = (
        utilisateur if utilisateur and utilisateur.is_authenticated else None
    )
    VueVitrine.objects.create(
        partenaire=partenaire, utilisateur=utilisateur_reel, source=source,
    )
    ProfilPartenaire.objects.filter(pk=partenaire.pk).update(
        nb_vues=F('nb_vues') + 1,
    )

    profil = _profil_utilisateur(utilisateur_reel)
    if profil is None:
        return
    if avec_catalogue:
        profil.nb_vues_catalogue_mois += 1
    else:
        profil.nb_articles_vus_mois += 1
    profil.derniere_activite = timezone.now()
    profil.save()
