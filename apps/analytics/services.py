from django.utils import timezone


def _profil_utilisateur(utilisateur):
    if not utilisateur or not utilisateur.is_authenticated:
        return None
    from .views import _profil
    return _profil(utilisateur)


def _incrementer_interaction(profil):
    """Signal d'engagement generique : alimente le compteur d'interactions
    utilise par le scoring 'client actif' (vue article, vue vitrine,
    ouverture d'une demande d'intervention...)."""
    profil.nb_interactions_mois += 1
    profil.derniere_activite = timezone.now()


def enregistrer_vue_dans_profil(utilisateur, article):
    """Consultation de la fiche detail d'un article.

    Incremente le compteur d'articles (usage propre : stats par article)
    ET le compteur d'interactions (scoring). La categorie est comptee
    separement, a l'entree dans le catalogue.
    """
    profil = _profil_utilisateur(utilisateur)
    if profil is None:
        return
    profil.nb_articles_vus_mois += 1
    _incrementer_interaction(profil)
    profil.save()


def enregistrer_visite_categorie(utilisateur, slug_categorie):
    """Entree dans le catalogue d'une categorie.

    Une visite = +1 sur le compteur de la categorie, quel que soit le nombre
    d'articles ouverts ensuite.
    """
    profil = _profil_utilisateur(utilisateur)
    if profil is None or not slug_categorie:
        return
    compteurs = profil.categories_consultees or {}
    compteurs[slug_categorie] = compteurs.get(slug_categorie, 0) + 1
    profil.categories_consultees = compteurs
    profil.derniere_activite = timezone.now()
    profil.save()


def enregistrer_vue_vitrine(utilisateur, partenaire, source='autre'):
    """Consultation de la vitrine d'un partenaire.

    Incremente le compteur public du partenaire et, pour un utilisateur
    connecte, le compteur d'interactions : c'est le principal signal pour
    les metiers de service, ou aucun article n'est consulte.
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
    _incrementer_interaction(profil)
    profil.save()


def enregistrer_demande_intervention(utilisateur):
    """Ouverture de l'ecran 'Demande d'intervention'.

    Signal d'intention forte : compte comme une interaction, meme si la
    demande n'est finalement pas envoyee.
    """
    profil = _profil_utilisateur(utilisateur)
    if profil is None:
        return
    _incrementer_interaction(profil)
    profil.save()
