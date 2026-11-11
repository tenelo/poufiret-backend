"""Plafond de photos par article (ArticleImage) — source unique.

Ordre de priorité :
1. Categorie.max_photos_par_article de la catégorie de l'article ;
2. sinon, la première valeur trouvée en remontant les catégories parentes ;
3. sinon, le quota de l'abonnement du vendeur (PlanAbonnement.
   nb_photos_par_article, 0 = illimité), exactement comme avant.

Le plafond ne bloque que l'AJOUT : baisser une valeur ne supprime aucune
image existante. Utilisé par toutes les routes d'ajout d'image d'article
(/catalogue/images/, routes imbriquées restaurants et locations) et par les
listes d'images côté vendeur / admin (plafond_photos).
"""
from apps.core.exceptions import ErreurMetier

SOURCE_CATEGORIE = 'categorie'
SOURCE_ABONNEMENT = 'abonnement'


def plafond_categorie(categorie):
    """(valeur, catégorie qui la porte) : la catégorie elle-même, sinon la
    première parente qui a une valeur ; (None, None) si aucune."""
    vues = set()
    while categorie is not None and categorie.pk not in vues:
        if categorie.max_photos_par_article is not None:
            return categorie.max_photos_par_article, categorie
        vues.add(categorie.pk)
        categorie = categorie.parent
    return None, None


def plafond_photos(article):
    """Plafond effectif de l'article : dict {max, source, categorie_id,
    categorie_nom, plan_libelle}. max = None si illimité (abonnement à 0)."""
    valeur, porteuse = plafond_categorie(article.categorie)
    plan = article.partenaire.plan
    if valeur is not None:
        return {'max': valeur, 'source': SOURCE_CATEGORIE, 'categorie_id': porteuse.pk,
                'categorie_nom': porteuse.nom, 'plan_libelle': plan.libelle}
    return {'max': plan.nb_photos_par_article or None, 'source': SOURCE_ABONNEMENT,
            'categorie_id': None, 'categorie_nom': None, 'plan_libelle': plan.libelle}


def etat_photos(article):
    """Plafond effectif + compteur, pour l'interface (« n / max »)."""
    plafond = plafond_photos(article)
    nb = article.images.count()
    return {**plafond, 'nb_photos': nb,
            'peut_ajouter': plafond['max'] is None or nb < plafond['max']}


def refus_ajout_photo(article):
    """None si une photo peut être ajoutée, sinon (plafond, nb) — plafond
    étant le dict de plafond_photos."""
    plafond = plafond_photos(article)
    nb = article.images.count()
    if plafond['max'] is not None and nb >= plafond['max']:
        return plafond, nb
    return None


def erreur_plafond_categorie(plafond, nb):
    """Refus 400 quand le plafond vient d'une catégorie."""
    maxi = plafond['max']
    message = (f"Nombre maximum de photos atteint : {maxi} photo(s) par article pour la "
               f"catégorie « {plafond['categorie_nom']} » ({nb} déjà). Supprimez une photo "
               f"pour en ajouter une autre.")
    return ErreurMetier(message, {'quota': maxi, 'nb_images': nb, 'source': SOURCE_CATEGORIE,
                                  'categorie_id': plafond['categorie_id']})
