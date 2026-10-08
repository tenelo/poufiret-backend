"""Services du module locations (Phase M1 : maisons à louer ; Phase V1 :
location de véhicules ; Phase V2 : hôtels et résidences meublées).

Centralise la constante des types de partenaires concernés et la
construction de la réponse « logement » (gestion), pour que l'espace
loueur, l'espace admin et la liste admin s'y greffent sans dupliquer.
"""
from apps.catalog.serializers import ArticleImageSerializer, PanoramaSerializer
from apps.users.models import ProfilPartenaire

TYPES_LOCATION = [ProfilPartenaire.TypePartenaire.LOUEUR_MAISON,
                  ProfilPartenaire.TypePartenaire.LOUEUR_VOITURE,
                  ProfilPartenaire.TypePartenaire.HOTELIER]

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


EQUIPEMENTS_ETABLISSEMENT_LIBELLES = {
    'wifi': 'Wifi',
    'parking': 'Parking',
    'piscine': 'Piscine',
    'restaurant': 'Restaurant',
    'bar': 'Bar',
    'salle_conference': 'Salle de conférence',
    'groupe_electrogene': 'Groupe électrogène',
    'securite_24h': 'Sécurité 24h/24',
    'navette': 'Navette',
    'blanchisserie': 'Blanchisserie',
}

EQUIPEMENTS_HEBERGEMENT_LIBELLES = {
    'climatisation': 'Climatisation',
    'ventilateur': 'Ventilateur',
    'tv': 'Télévision',
    'wifi': 'Wifi',
    'eau_chaude': 'Eau chaude',
    'minibar': 'Minibar',
    'coffre': 'Coffre-fort',
    'balcon': 'Balcon',
    'cuisine': 'Cuisine',
    'refrigerateur': 'Réfrigérateur',
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


def reservations_confirmees(article_id, avec_unites=False):
    """Réservations confirmées à venir (ou en cours) d'un objet —
    [{demande_id, date_debut, date_fin}] (+ nb_unites pour un hébergement),
    triées par date de début."""
    from django.utils import timezone

    from apps.reservations.models import DemandeReservation
    lignes = (DemandeReservation.objects.filter(
                  objet_id=article_id, nature=DemandeReservation.Nature.RESERVATION,
                  statut=DemandeReservation.Statut.CONFIRMEE, date_fin__gt=timezone.localdate())
              .order_by('date_debut').values('id', 'date_debut', 'date_fin', 'nb_unites'))
    resultats = []
    for d in lignes:
        r = {'demande_id': d['id'], 'date_debut': d['date_debut'], 'date_fin': d['date_fin']}
        if avec_unites:
            r['nb_unites'] = d['nb_unites']
        resultats.append(r)
    return resultats


def localisation_texte(obj):
    """« Localité - Quartier - Secteur » d'un bien (logement, véhicule) ou
    d'un partenaire (établissement) — mêmes champs localite/quartier_geo/secteur."""
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


# ═══════════════════════════════════════════════════════════════════════
# Phase V2 : établissements et hébergements
# ═══════════════════════════════════════════════════════════════════════

def libelles(valeurs, referentiel):
    return [referentiel.get(v, v) for v in valeurs]


def fiche_etablissement(partenaire, creer=False):
    """Fiche établissement du partenaire. creer=True : get_or_create
    (gestion) ; sinon fiche existante ou instance par défaut NON enregistrée
    (lecture publique : jamais d'écriture sur un GET)."""
    from .models import ProfilEtablissement
    if creer:
        return ProfilEtablissement.objects.get_or_create(partenaire=partenaire)[0]
    try:
        return partenaire.profil_etablissement
    except ProfilEtablissement.DoesNotExist:
        return ProfilEtablissement(partenaire=partenaire)


def etablissement_gestion_dict(fiche):
    p = fiche.partenaire
    return {
        'partenaire_id': p.id,
        'nom': p.nom_commerce,
        'type_etablissement': fiche.type_etablissement,
        'type_etablissement_libelle': fiche.get_type_etablissement_display(),
        'etoiles': fiche.etoiles,
        'heure_arrivee': fiche.heure_arrivee,
        'heure_depart': fiche.heure_depart,
        'equipements_etablissement': fiche.equipements,
        'equipements_etablissement_libelles': libelles(fiche.equipements, EQUIPEMENTS_ETABLISSEMENT_LIBELLES),
        'petit_dejeuner': fiche.petit_dejeuner,
        'petit_dejeuner_libelle': fiche.get_petit_dejeuner_display(),
        'prix_petit_dejeuner': fiche.prix_petit_dejeuner,
        'politique_annulation': fiche.politique_annulation,
        'conditions': fiche.conditions,
        'modifie_par_role': fiche.modifie_par_role,
        'modifie_par_nom': fiche.modifie_par_nom,
        'modifie_le': fiche.updated_at,
        'cree_le': fiche.created_at,
    }


def occupation_par_nuit(lignes, date_debut, date_fin):
    """Pic d'unités occupées sur [date_debut, date_fin[ (une nuit = un
    jour d'arrivée), à partir de réservations (date_debut, date_fin,
    nb_unites) : deux réservations qui ne se chevauchent pas entre elles ne
    s'additionnent pas."""
    from datetime import timedelta
    pic, jour = 0, date_debut
    while jour < date_fin:
        pic = max(pic, sum(n for d, f, n in lignes if d <= jour < f))
        jour += timedelta(days=1)
    return pic


def unites_disponibles(hebergement, date_debut, date_fin, exclure_id=None):
    """Unités encore vendables sur la période : nb_unites − pic des
    réservations CONFIRMÉES qui la chevauchent (0 si l'hébergement est
    indisponible). Une requête."""
    from apps.reservations.models import DemandeReservation
    if hebergement.disponibilite != hebergement.Disponibilite.DISPONIBLE:
        return 0
    qs = DemandeReservation.objects.filter(
        objet_id=hebergement.article_id, nature=DemandeReservation.Nature.RESERVATION,
        statut=DemandeReservation.Statut.CONFIRMEE, date_debut__lt=date_fin, date_fin__gt=date_debut)
    if exclure_id:
        qs = qs.exclude(pk=exclure_id)
    lignes = list(qs.values_list('date_debut', 'date_fin', 'nb_unites'))
    return max(hebergement.nb_unites - occupation_par_nuit(lignes, date_debut, date_fin), 0)


NUITS_PAR_SEMAINE = 7
NUITS_PAR_MOIS = 30


def tarif_sejour(hebergement, prix_nuit, nuits, nb_unites=1):
    """Montant estimé d'un séjour : mois entiers (30 nuits) au prix_mois
    s'il est renseigné, puis semaines entières (7 nuits) au prix_semaine
    s'il est renseigné, puis nuits restantes au prix par nuit — × nb_unites.
    None si le prix par nuit manque alors qu'il est nécessaire."""
    total, reste = 0, nuits
    if hebergement.prix_mois is not None and reste >= NUITS_PAR_MOIS:
        total += (reste // NUITS_PAR_MOIS) * hebergement.prix_mois
        reste %= NUITS_PAR_MOIS
    if hebergement.prix_semaine is not None and reste >= NUITS_PAR_SEMAINE:
        total += (reste // NUITS_PAR_SEMAINE) * hebergement.prix_semaine
        reste %= NUITS_PAR_SEMAINE
    if reste:
        if prix_nuit is None:
            return None
        total += reste * prix_nuit
    return total * nb_unites


def hebergement_dict(obj, request):
    """Représentation complète d'un hébergement pour l'espace hôtelier/admin
    (gestion) — Article + Hebergement, une seule ressource en sortie."""
    a = obj.article
    return {
        'id': a.id,
        'nom': a.nom,
        'slug': a.slug,
        'description': a.description,
        'prix': a.prix,
        'prix_nuit': a.prix,
        'est_actif': a.est_actif,
        'type_hebergement': obj.type_hebergement,
        'type_hebergement_libelle': obj.get_type_hebergement_display(),
        'capacite_adultes': obj.capacite_adultes,
        'capacite_enfants': obj.capacite_enfants,
        'lits': obj.lits,
        'surface_m2': obj.surface_m2,
        'equipements_hebergement': obj.equipements,
        'equipements_hebergement_libelles': libelles(obj.equipements, EQUIPEMENTS_HEBERGEMENT_LIBELLES),
        'prix_semaine': obj.prix_semaine,
        'prix_mois': obj.prix_mois,
        'nb_unites': obj.nb_unites,
        'duree_min_nuits': obj.duree_min_nuits,
        'disponibilite': obj.disponibilite,
        'disponibilite_libelle': obj.get_disponibilite_display(),
        'images': ArticleImageSerializer(a.images.order_by('ordre'), many=True,
                                         context={'request': request}).data,
        'panoramas': PanoramaSerializer(a.panoramas.order_by('ordre'), many=True,
                                        context={'request': request}).data,
        'reservations_confirmees': reservations_confirmees(a.id, avec_unites=True),
        'modifie_par_role': obj.modifie_par_role,
        'modifie_par_nom': obj.modifie_par_nom,
        'modifie_le': obj.updated_at,
        'cree_le': obj.created_at,
    }
