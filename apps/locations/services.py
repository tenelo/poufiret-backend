"""Services du module locations (Phase M1 : maisons à louer).

Centralise la constante des types de partenaires concernés et la
construction de la réponse « logement » (gestion), pour que l'espace
loueur, l'espace admin et la liste admin s'y greffent sans dupliquer.
"""
from apps.catalog.serializers import ArticleImageSerializer, PanoramaSerializer
from apps.users.models import ProfilPartenaire

# 'loueur_voiture' et 'hotelier' viendront dans une phase ultérieure
# (véhicules, hôtels/résidences) — hors périmètre M1.
TYPES_LOCATION = [ProfilPartenaire.TypePartenaire.LOUEUR_MAISON]

EQUIPEMENTS_LIBELLES = {
    'climatisation': 'Climatisation',
    'gardien': 'Gardien',
    'parking': 'Parking',
    'garage': 'Garage',
    'cour': 'Cour',
    'cuisine': 'Cuisine équipée',
    'forage': 'Forage',
    'carrelage': 'Carrelage',
    'staff': 'Staff (personnel de maison)',
    'balcon': 'Balcon',
    'piscine': 'Piscine',
    'wifi': 'Wifi',
    'groupe_electrogene': 'Groupe électrogène',
}
# Dérivée du dictionnaire ci-dessus (source unique : pas de liste recopiée
# à la main ailleurs — apps.locations.views_prive.MetaLocationsView inclus).
EQUIPEMENTS_REFERENTIEL = list(EQUIPEMENTS_LIBELLES)


def valider_equipements(valeur):
    """Liste validée (sous-ensemble du référentiel, sans doublon) ou None."""
    if not isinstance(valeur, list) or not all(isinstance(e, str) for e in valeur):
        return None
    inconnus = [e for e in valeur if e not in EQUIPEMENTS_REFERENTIEL]
    if inconnus:
        return None
    return list(dict.fromkeys(valeur))


def logement_dict(obj, request):
    """Représentation complète d'un logement pour l'espace loueur/admin
    (gestion) — Article + Logement, une seule ressource en sortie."""
    a = obj.article
    return {
        'id': a.id,
        'nom': a.nom,
        'slug': a.slug,
        'description': a.description,
        'prix': a.prix,
        'est_actif': a.est_actif,
        'type_logement': obj.type_logement,
        'type_logement_libelle': obj.get_type_logement_display(),
        'nb_chambres': obj.nb_chambres,
        'nb_salons': obj.nb_salons,
        'nb_salles_de_bain': obj.nb_sdb,
        'surface_m2': obj.surface_m2,
        'meuble': obj.meuble,
        'caution_mois': obj.caution_mois,
        'avance_mois': obj.avance_mois,
        'frais_agence': obj.frais_agence,
        'compteur_eau_individuel': obj.compteur_eau_individuel,
        'compteur_electricite_individuel': obj.compteur_electricite_individuel,
        'equipements': obj.equipements,
        'disponibilite': obj.disponibilite,
        'disponibilite_libelle': obj.get_disponibilite_display(),
        'disponible_a_partir_du': obj.disponible_a_partir_du,
        'departement_id': obj.localite.departement_id if obj.localite_id else None,
        'departement_nom': obj.localite.departement.nom if obj.localite_id else None,
        'localite_id': obj.localite_id,
        'localite_nom': obj.localite.nom if obj.localite_id else None,
        'quartier_id': obj.quartier_geo_id,
        'quartier_nom': obj.quartier_geo.nom if obj.quartier_geo_id else None,
        'secteur': obj.secteur,
        'adresse_reperes': obj.adresse_reperes,
        'latitude': obj.localisation.y if obj.localisation else None,
        'longitude': obj.localisation.x if obj.localisation else None,
        'images': ArticleImageSerializer(a.images.order_by('ordre'), many=True,
                                         context={'request': request}).data,
        'panoramas': PanoramaSerializer(a.panoramas.order_by('ordre'), many=True,
                                        context={'request': request}).data,
        'modifie_par_role': obj.modifie_par_role,
        'modifie_par_nom': obj.modifie_par_nom,
        'modifie_le': obj.updated_at,
        'cree_le': obj.created_at,
    }
