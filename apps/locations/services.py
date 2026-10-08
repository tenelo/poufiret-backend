"""Services du module locations (Phase M1 : maisons à louer ; Phase V1 :
location de véhicules).

Centralise la constante des types de partenaires concernés et la
construction de la réponse « logement » (gestion), pour que l'espace
loueur, l'espace admin et la liste admin s'y greffent sans dupliquer.
"""
from apps.catalog.serializers import ArticleImageSerializer, PanoramaSerializer
from apps.users.models import ProfilPartenaire

# 'hotelier' viendra dans une phase ultérieure (hôtels/résidences).
TYPES_LOCATION = [ProfilPartenaire.TypePartenaire.LOUEUR_MAISON,
                  ProfilPartenaire.TypePartenaire.LOUEUR_VOITURE]

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


EQUIPEMENTS_VEHICULE_LIBELLES = {
    'gps': 'GPS',
    'bluetooth': 'Bluetooth',
    'camera_recul': 'Caméra de recul',
    'sieges_cuir': 'Sièges en cuir',
    'toit_ouvrant': 'Toit ouvrant',
    'siege_enfant': 'Siège enfant',
    'usb': 'Prise USB',
}


def valider_equipements(valeur, referentiel=None):
    """Liste validée (sous-ensemble du référentiel, sans doublon) ou None.
    Référentiel par défaut : équipements de logement (M1)."""
    referentiel = EQUIPEMENTS_REFERENTIEL if referentiel is None else referentiel
    if not isinstance(valeur, list) or not all(isinstance(e, str) for e in valeur):
        return None
    inconnus = [e for e in valeur if e not in referentiel]
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


def reservations_confirmees(article_id):
    """Réservations confirmées à venir (ou en cours) d'un objet —
    [{demande_id, date_debut, date_fin}], triées par date de début."""
    from django.utils import timezone

    from apps.reservations.models import DemandeReservation
    return [
        {'demande_id': d['id'], 'date_debut': d['date_debut'], 'date_fin': d['date_fin']}
        for d in DemandeReservation.objects.filter(
            objet_id=article_id, nature=DemandeReservation.Nature.RESERVATION,
            statut=DemandeReservation.Statut.CONFIRMEE, date_fin__gt=timezone.localdate(),
        ).order_by('date_debut').values('id', 'date_debut', 'date_fin')
    ]


def localisation_texte(obj):
    """« Localité - Quartier - Secteur » d'un bien (logement ou véhicule)."""
    return ' - '.join(filter(None, [
        obj.localite.nom if obj.localite_id else None,
        obj.quartier_geo.nom if obj.quartier_geo_id else None,
        obj.secteur or None,
    ]))


def vehicule_dict(obj, request):
    """Représentation complète d'un véhicule pour l'espace loueur/admin
    (gestion) — Article + Vehicule, une seule ressource en sortie."""
    a = obj.article
    return {
        'id': a.id,
        'nom': a.nom,
        'slug': a.slug,
        'description': a.description,
        'prix': a.prix,
        'est_actif': a.est_actif,
        'categorie_vehicule': obj.categorie_vehicule,
        'categorie_libelle': obj.get_categorie_vehicule_display(),
        'marque': obj.marque,
        'modele': obj.modele,
        'annee': obj.annee,
        'couleur': obj.couleur,
        'nb_places': obj.places,
        'boite': obj.boite_vitesse,
        'boite_libelle': obj.get_boite_vitesse_display(),
        'carburant': obj.carburant,
        'carburant_libelle': obj.get_carburant_display(),
        'climatisation': obj.climatisation,
        'equipements': obj.equipements,
        'equipements_libelles': [EQUIPEMENTS_VEHICULE_LIBELLES.get(e, e) for e in obj.equipements],
        'chauffeur_disponible': obj.chauffeur_disponible,
        'chauffeur_obligatoire': obj.chauffeur_obligatoire,
        'prix_jour_avec_chauffeur': obj.prix_jour_avec_chauffeur,
        'caution': obj.caution,
        'km_inclus_par_jour': obj.km_inclus_par_jour,
        'prix_km_supplementaire': obj.prix_km_supplementaire,
        'carburant_inclus': obj.carburant_inclus,
        'duree_min_jours': obj.duree_min_jours,
        'zone_circulation': obj.zone_circulation,
        'disponibilite': obj.disponibilite,
        'disponibilite_libelle': obj.get_disponibilite_display(),
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
        'reservations_confirmees': reservations_confirmees(a.id),
        'modifie_par_role': obj.modifie_par_role,
        'modifie_par_nom': obj.modifie_par_nom,
        'modifie_le': obj.updated_at,
        'cree_le': obj.created_at,
    }
