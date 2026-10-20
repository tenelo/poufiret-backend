"""Gabarits d'affichage : SOURCE UNIQUE de la correspondance type de
partenaire → gabarit, et de la définition de chaque gabarit (libellés,
fonctionnalités actives, champs propres aux produits — « fiche_specifique »).

Le moteur restaurants (fiche, horaires, statut, sections, produits, images,
variantes, options, menus, commandes ; préfixe /restaurants/ conservé)
s'applique à tous les types de TYPES_MOTEUR. Le gabarit ne fait que
paramétrer l'affichage et quelques règles (menus/options actifs,
pagination publique, champs spécifiques, ordonnance).

Les types gérés par apps.locations (hôtelier, loueurs) gardent leur
fonctionnement propre : leur « gabarit » ne sert qu'à orienter l'appli.
"""
from django.utils import timezone

from apps.users.models import ProfilPartenaire

T = ProfilPartenaire.TypePartenaire

RESTAURANT = 'restaurant'
BOULANGERIE = 'boulangerie'
PHARMACIE = 'pharmacie'
MODE = 'mode'
LIBRAIRIE = 'librairie'
GENERIQUE = 'generique'

# Types pris en charge par le moteur restaurants → gabarit.
GABARIT_PAR_TYPE = {
    T.RESTAURATEUR: RESTAURANT,
    T.FAST_FOOD: RESTAURANT,
    T.BOULANGER: BOULANGERIE,
    T.PHARMACIEN: PHARMACIE,
    T.BOUTIQUE_MODE: MODE,
    T.LIBRAIRE: LIBRAIRIE,
}

# Types gérés à part (apps.locations) : fonctionnement inchangé, valeur
# exposée pour que l'appli ouvre le bon écran.
GABARIT_HORS_MOTEUR = {
    T.HOTELIER: 'hotel',
    T.LOUEUR_MAISON: 'location_maison',
    T.LOUEUR_VOITURE: 'location_vehicule',
}

TYPES_MOTEUR = list(GABARIT_PAR_TYPE)


def gabarit_de_type(type_partenaire):
    return (GABARIT_PAR_TYPE.get(type_partenaire)
            or GABARIT_HORS_MOTEUR.get(type_partenaire)
            or GENERIQUE)


def gabarit_de(partenaire):
    return gabarit_de_type(partenaire.type_partenaire)


# ═══════════════════════════════════════════════════════════════════════
# Définitions (exposées telles quelles par GET /restaurants/meta/gabarits/)
# ═══════════════════════════════════════════════════════════════════════

def _choix(*paires):
    return [{'valeur': v, 'libelle': l} for v, l in paires]


def _champ(cle, libelle, type_, obligatoire=False, choix=None):
    return {'cle': cle, 'libelle': libelle, 'type': type_, 'choix': choix or [],
            'obligatoire': obligatoire}


TEXTE, ENTIER, BOOLEEN, CHOIX = 'texte', 'entier', 'booleen', 'choix'

GABARITS = {
    RESTAURANT: {
        'libelle': 'Restaurant', 'libelle_section': 'Section', 'libelle_produit': 'Plat',
        'libelle_variantes': 'Variantes', 'menus_actifs': True, 'options_actives': True,
        'pagination_publique': False, 'champs': [],
    },
    BOULANGERIE: {
        'libelle': 'Boulangerie', 'libelle_section': 'Section', 'libelle_produit': 'Produit',
        'libelle_variantes': 'Formats', 'menus_actifs': False, 'options_actives': True,
        'pagination_publique': False,
        'champs': [
            _champ('sur_commande', 'Sur commande', BOOLEEN),
            _champ('delai_heures', 'Délai (heures)', ENTIER),
            _champ('allergenes', 'Allergènes', TEXTE),
        ],
    },
    PHARMACIE: {
        'libelle': 'Pharmacie', 'libelle_section': 'Rayon', 'libelle_produit': 'Produit',
        'libelle_variantes': 'Formats', 'menus_actifs': False, 'options_actives': False,
        'pagination_publique': True,
        'champs': [
            _champ('forme', 'Forme', CHOIX, choix=_choix(
                ('comprime', 'Comprimé'), ('gelule', 'Gélule'), ('sirop', 'Sirop'),
                ('pommade', 'Pommade'), ('injectable', 'Injectable'), ('sachet', 'Sachet'),
                ('collyre', 'Collyre'), ('autre', 'Autre'))),
            _champ('dosage', 'Dosage', TEXTE),
            _champ('laboratoire', 'Laboratoire', TEXTE),
            _champ('conditionnement', 'Conditionnement', TEXTE),
            _champ('sur_ordonnance', 'Sur ordonnance', BOOLEEN),
        ],
    },
    MODE: {
        'libelle': 'Mode / Chaussures', 'libelle_section': 'Catégorie', 'libelle_produit': 'Article',
        'libelle_variantes': 'Pointures', 'menus_actifs': False, 'options_actives': False,
        'pagination_publique': True,
        'champs': [
            _champ('marque', 'Marque', TEXTE),
            _champ('matiere', 'Matière', TEXTE),
            _champ('couleur', 'Couleur', TEXTE),
            _champ('genre', 'Genre', CHOIX, choix=_choix(
                ('homme', 'Homme'), ('femme', 'Femme'), ('enfant', 'Enfant'), ('mixte', 'Mixte'))),
        ],
    },
    LIBRAIRIE: {
        'libelle': 'Librairie', 'libelle_section': 'Rayon', 'libelle_produit': 'Livre',
        'libelle_variantes': 'Formats', 'menus_actifs': False, 'options_actives': False,
        'pagination_publique': True,
        'champs': [
            _champ('auteur', 'Auteur', TEXTE, obligatoire=True),
            _champ('editeur', 'Éditeur', TEXTE),
            _champ('isbn', 'ISBN', TEXTE),
            _champ('langue', 'Langue', TEXTE),
            _champ('classe', 'Classe', TEXTE),
            _champ('annee', 'Année', ENTIER),
            _champ('genre_livre', 'Genre', CHOIX, choix=_choix(
                ('scolaire', 'Scolaire'), ('roman', 'Roman'), ('jeunesse', 'Jeunesse'),
                ('religieux', 'Religieux'), ('dictionnaire', 'Dictionnaire'), ('essai', 'Essai'),
                ('bd', 'Bande dessinée'), ('autre', 'Autre'))),
            _champ('niveau', 'Niveau', CHOIX, choix=_choix(
                ('primaire', 'Primaire'), ('college', 'Collège'), ('lycee', 'Lycée'),
                ('superieur', 'Supérieur'), ('aucun', 'Aucun'))),
            _champ('etat', 'État', CHOIX, choix=_choix(('neuf', 'Neuf'), ('occasion', 'Occasion'))),
        ],
    },
}

# Champs texte de fiche_specifique couverts par la recherche publique ?q=.
CHAMPS_RECHERCHE = ('auteur', 'isbn', 'marque', 'laboratoire', 'dosage')

LONGUEUR_MAX_TEXTE = 300


def definition(gabarit):
    """Définition du gabarit ; le gabarit restaurant pour un gabarit hors
    table (le moteur ne sert que les types de TYPES_MOTEUR)."""
    return GABARITS.get(gabarit, GABARITS[RESTAURANT])


def valider_fiche_specifique(gabarit, valeur):
    """(fiche normalisée, erreurs) — erreurs = {"fiche_specifique.<cle>": [msg]}.
    Clés inconnues refusées ; valeurs nulles retirées ; champs obligatoires
    exigés (non vides)."""
    if valeur is None:
        valeur = {}
    if not isinstance(valeur, dict):
        return None, {'fiche_specifique': ['Objet JSON attendu.']}
    champs = {c['cle']: c for c in definition(gabarit)['champs']}
    erreurs, fiche = {}, {}

    def err(cle, msg):
        erreurs.setdefault(f'fiche_specifique.{cle}', []).append(msg)

    for cle, v in valeur.items():
        champ = champs.get(cle)
        if champ is None:
            err(cle, f'Champ inconnu pour le gabarit « {gabarit} ».')
            continue
        if v is None:
            continue
        type_ = champ['type']
        if type_ == TEXTE:
            if not isinstance(v, str):
                err(cle, 'Texte attendu.')
            elif len(v) > LONGUEUR_MAX_TEXTE:
                err(cle, f'{LONGUEUR_MAX_TEXTE} caractères au plus.')
            else:
                fiche[cle] = v.strip()
        elif type_ == ENTIER:
            if isinstance(v, bool) or not isinstance(v, int):
                err(cle, 'Entier attendu.')
            elif v < 0:
                err(cle, 'Doit être positif ou nul.')
            else:
                fiche[cle] = v
        elif type_ == BOOLEEN:
            if not isinstance(v, bool):
                err(cle, 'Booléen attendu (true/false).')
            else:
                fiche[cle] = v
        elif type_ == CHOIX:
            valeurs = [c['valeur'] for c in champ['choix']]
            if v not in valeurs:
                err(cle, f'Valeur attendue parmi : {", ".join(valeurs)}.')
            else:
                fiche[cle] = v

    for cle, champ in champs.items():
        if champ['obligatoire'] and fiche.get(cle) in (None, '') and f'fiche_specifique.{cle}' not in erreurs:
            err(cle, 'Ce champ est obligatoire.')
    return fiche, erreurs


# ═══════════════════════════════════════════════════════════════════════
# Règles dérivées
# ═══════════════════════════════════════════════════════════════════════

MESSAGE_ORDONNANCE = 'Médicament sur ordonnance : contactez la pharmacie.'


def sur_ordonnance(article, gabarit=None):
    gabarit = gabarit or gabarit_de(article.partenaire)
    return gabarit == PHARMACIE and bool((article.fiche_specifique or {}).get('sur_ordonnance'))


def commandable(article, gabarit=None):
    """Peut être ajouté au panier : disponible, et pas un médicament sur
    ordonnance (pharmacie)."""
    return bool(article.est_disponible) and not sur_ordonnance(article, gabarit)


def variante_epuisee(variante):
    """Épuisée si marquée comme telle, ou si son stock (non nul = suivi)
    est à 0."""
    return bool(variante.est_epuise) or (variante.stock is not None and variante.stock <= 0)


def de_garde(fiche, maintenant=None):
    """Pharmacie de garde : de_garde_jusqu_au renseigné et dans le futur."""
    fin = getattr(fiche, 'de_garde_jusqu_au', None)
    return fin is not None and fin > (maintenant or timezone.now())


def type_article(gabarit):
    """Type d'Article créé par le moteur : 'plat' pour la restauration,
    'produit' pour les autres gabarits."""
    from apps.catalog.models import Article
    return Article.Type.PLAT if gabarit == RESTAURANT else Article.Type.PRODUIT


def types_articles_moteur():
    from apps.catalog.models import Article
    return [Article.Type.PLAT, Article.Type.PRODUIT]
