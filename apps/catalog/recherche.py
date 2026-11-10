"""Moteur de recherche unifié (catégories > partenaires > articles).

Utilisé par la recherche publique (qui journalise les termes sans résultat)
et par le testeur du dictionnaire admin (qui ne journalise jamais).
"""
import re

from django.db.models import F, Q, TextField
from django.db.models.functions import Cast

from apps.geo.portee import filtre_visibilite
from apps.users.models import ProfilPartenaire

from .models import Article, Categorie, RechercheSansResultat


MOTS_MAX = 100
LONGUEUR_MOT_MAX = 60


def normaliser_terme(terme):
    return ' '.join((terme or '').lower().split())


def normaliser_mots_cles(valeur):
    """Liste de mots-clés : minuscules, espaces unifiés, sans doublon ni vide.
    None si la valeur n'est pas une liste de textes ou dépasse les bornes."""
    if not isinstance(valeur, list) or not all(isinstance(m, str) for m in valeur):
        return None
    mots = []
    for m in valeur:
        n = normaliser_terme(m)
        if n and n not in mots:
            mots.append(n)
    if len(mots) > MOTS_MAX or any(len(m) > LONGUEUR_MOT_MAX for m in mots):
        return None
    return mots


def motif_debut_de_mot(terme):
    """Regex PostgreSQL : le terme en DÉBUT DE MOT (\\m), pas au milieu
    (« oeuf » ne trouve plus « boeuf », « pou » trouve « poulet »).
    Utilisé avec __unaccent__iregex : minuscules / accents ignorés des deux côtés."""
    return r'\m' + re.escape(terme)


def q_debut_de_mot(terme, *champs):
    """Q() : le terme commence un mot dans l'un des champs."""
    motif = motif_debut_de_mot(terme)
    q = Q()
    for champ in champs:
        q |= Q(**{f'{champ}__unaccent__iregex': motif})
    return q


def _url(request, champ):
    if not champ:
        return ''
    try:
        return request.build_absolute_uri(champ.url)
    except Exception:
        return ''


def _prefixer(q, prefixe):
    """Recrée un Q en préfixant chaque clé (ex. plan__portee → partenaire__plan__portee)."""
    nouveau = Q()
    nouveau.connector = q.connector
    nouveau.negated = q.negated
    for enfant in q.children:
        if isinstance(enfant, Q):
            nouveau.children.append(_prefixer(enfant, prefixe))
        else:
            cle, val = enfant
            nouveau.children.append((prefixe + cle, val))
    return nouveau


def rechercher(request, terme, localites=None):
    """Retourne {'categories', 'partenaires', 'articles'} pour un terme >= 2 car."""
    dep_user = getattr(request.user, 'departement', None) if request.user.is_authenticated else None
    visibilite = filtre_visibilite(dep_user, localites)

    # Mots-clés (liste JSON) lus comme texte : « ["boeufs", "oeufs frais"] ».
    categories = (Categorie.objects
                  .filter(est_active=True, est_archivee=False)
                  .annotate(mots_cles_texte=Cast('mots_cles', TextField()))
                  .filter(q_debut_de_mot(terme, 'nom', 'description', 'mots_cles_texte'))
                  .order_by('ordre', 'nom')[:10])
    donnees_cat = [{
        'id': c.id, 'nom': c.nom, 'slug': c.slug, 'icone': c.icone,
        'mode_transaction': c.mode_transaction,
        'affiche_catalogue': c.affiche_catalogue,
    } for c in categories]

    from apps.users.visibilite import q_partenaire_public
    partenaires = (ProfilPartenaire.objects
                   .filter(q_partenaire_public())
                   .filter(visibilite)
                   .filter(q_debut_de_mot(terme, 'nom_commerce', 'description'))
                   .select_related('departement__region')
                   .order_by('-est_faveur', 'nom_commerce')[:15])
    donnees_part = [{
        'id': p.id, 'nom_commerce': p.nom_commerce,
        'description': p.description,
        'logo': _url(request, p.logo),
        'photo_couverture': _url(request, p.photo_couverture),
        'type_partenaire': p.get_type_partenaire_display(),
        'departement': p.departement.nom if p.departement_id else '',
    } for p in partenaires]

    # Catégories sans catalogue (plomberie, maçonnerie…) : leurs « articles »
    # sont des prestations, pas des produits achetables.
    visibilite_art = filtre_visibilite(dep_user, localites)
    articles = (Article.objects
                .filter(est_actif=True, categorie__affiche_catalogue=True)
                .filter(q_partenaire_public('partenaire__'))
                .filter(_prefixer(visibilite_art, 'partenaire__'))
                .filter(q_debut_de_mot(terme, 'nom', 'description'))
                .select_related('partenaire__departement__region')
                .order_by('-nb_vues')[:20])
    donnees_art = [{
        'id': a.id, 'nom': a.nom, 'slug': a.slug,
        'prix': str(a.prix) if a.prix is not None else '0',
        'prix_promotion': (str(a.prix_promotion)
                           if a.prix_promotion is not None else None),
        'est_en_promotion': a.est_en_promotion,
        'pourcentage_reduction': a.pourcentage_reduction,
        'prix_effectif': (str(a.prix_effectif)
                          if a.prix_effectif is not None else '0'),
        'partenaire_nom': a.partenaire.nom_commerce,
        'departement': (a.partenaire.departement.nom
                        if a.partenaire.departement_id else ''),
        'image_principale': _url(
            request,
            a.images.filter(est_principale=True).first().image
            if a.images.filter(est_principale=True).exists()
            else (a.images.first().image if a.images.exists() else None)
        ),
    } for a in articles]

    return {'categories': donnees_cat, 'partenaires': donnees_part, 'articles': donnees_art}


def journaliser_sans_resultat(request, terme):
    """Un terme sans aucun résultat révèle le vocabulaire réel des clients."""
    ligne, cree = RechercheSansResultat.objects.get_or_create(
        terme=terme.lower(),
        defaults={'utilisateur': request.user if request.user.is_authenticated else None},
    )
    if not cree:
        RechercheSansResultat.objects.filter(pk=ligne.pk).update(
            nb_occurrences=F('nb_occurrences') + 1)
