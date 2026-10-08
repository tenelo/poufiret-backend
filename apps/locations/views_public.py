"""Lecture publique des logements (Locations Phase M1), des véhicules
(Phase V1) et des établissements / hébergements (Phase V2). AllowAny — même mur
d'inscription que le reste du catalogue : aucune règle nouvelle."""
from django.db.models import Prefetch
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Article, ArticleImage, Hebergement, Logement, Panorama, Vehicule
from apps.catalog.serializers import PanoramaSerializer
from apps.users.models import ProfilPartenaire

from . import services
from .models import ProfilEtablissement


def _url(request, champ):
    if not champ:
        return None
    try:
        return request.build_absolute_uri(champ.url)
    except ValueError:
        return None


def _photo_principale(article, request):
    images = list(article.images.all())
    img = next((i for i in images if i.est_principale and i.est_active), None) \
        or next((i for i in images if i.est_active), None)
    return _url(request, img.image) if img else None


_localisation_texte = services.localisation_texte


def _carte(logement, request):
    a = logement.article
    return {
        'id': a.id,
        'titre': a.nom,
        'photo': _photo_principale(a, request),
        'type_logement': logement.type_logement,
        'type_logement_libelle': logement.get_type_logement_display(),
        'localisation_texte': _localisation_texte(logement),
        'loyer': a.prix,
        'nb_chambres': logement.nb_chambres,
        'nb_salles_de_bain': logement.nb_sdb,
        'meuble': logement.meuble,
        'disponibilite': logement.disponibilite,
    }


def _logements_qs_partenaire(partenaire):
    return (Logement.objects.filter(
                article__partenaire=partenaire, article__type=Article.Type.LOGEMENT, article__est_actif=True)
            .select_related('localite', 'quartier_geo')
            .prefetch_related(Prefetch('article__images', queryset=ArticleImage.objects.filter(est_active=True))))


class LogementsParPartenaireView(APIView):
    """GET /api/v1/locations/partenaires/<id>/logements/
    ?type=&quartier=&loyer_max=&chambres_min=&meuble=&disponible=1"""
    permission_classes = [permissions.AllowAny]

    def get(self, request, partenaire_id):
        partenaire = (ProfilPartenaire.objects
                      .filter(pk=partenaire_id, type_partenaire__in=services.TYPES_LOCATION,
                              statut=ProfilPartenaire.Statut.ACTIF, est_visible=True)
                      .select_related('departement').first())
        if partenaire is None:
            return Response({'erreur': True, 'message': 'Loueur introuvable.'}, status=404)

        qs = _logements_qs_partenaire(partenaire)
        p = request.query_params
        if p.get('type'):
            qs = qs.filter(type_logement=p['type'])
        if p.get('quartier'):
            qs = qs.filter(quartier_geo_id=p['quartier'])
        if p.get('loyer_max'):
            try:
                qs = qs.filter(article__prix__lte=int(p['loyer_max']))
            except ValueError:
                pass
        if p.get('chambres_min'):
            try:
                qs = qs.filter(nb_chambres__gte=int(p['chambres_min']))
            except ValueError:
                pass
        if p.get('meuble') not in (None, ''):
            qs = qs.filter(meuble=p['meuble'] in ('1', 'true', 'True'))
        if p.get('disponible') == '1':
            qs = qs.filter(disponibilite=Logement.Disponibilite.DISPONIBLE)

        return Response({
            'loueur': {
                'id': partenaire.id,
                'nom': partenaire.nom_commerce,
                'logo': _url(request, partenaire.logo),
                'couverture': _url(request, partenaire.photo_couverture),
                'telephone_pro': partenaire.telephone_pro,
                'whatsapp': partenaire.whatsapp,
            },
            'resultats': [_carte(l, request) for l in qs],
        })


class LogementDetailPublicView(APIView):
    """GET /api/v1/locations/logements/<id>/ — fiche complète en une
    réponse (galerie, panoramas, caractéristiques, conditions, équipements,
    localisation, loueur, autres logements disponibles du même loueur)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk):
        logement = (Logement.objects
                    .filter(article_id=pk, article__type=Article.Type.LOGEMENT, article__est_actif=True)
                    .select_related('article__partenaire', 'localite', 'quartier_geo')
                    .prefetch_related(
                        Prefetch('article__images', queryset=ArticleImage.objects.filter(est_active=True).order_by('ordre')),
                        Prefetch('article__panoramas', queryset=Panorama.objects.filter(est_active=True).order_by('ordre')),
                    ).first())
        if logement is None:
            return Response({'erreur': True, 'message': 'Logement introuvable.'}, status=404)

        a = logement.article
        partenaire = a.partenaire
        autres = (Logement.objects.filter(
                      article__partenaire=partenaire, article__type=Article.Type.LOGEMENT,
                      article__est_actif=True, disponibilite=Logement.Disponibilite.DISPONIBLE)
                  .exclude(article_id=a.id)
                  .select_related('localite', 'quartier_geo')
                  .prefetch_related(Prefetch('article__images', queryset=ArticleImage.objects.filter(est_active=True)))
                  [:4])

        return Response({
            'id': a.id,
            'titre': a.nom,
            'description': a.description,
            'galerie': [_url(request, i.image) for i in a.images.all()],
            'panoramas': PanoramaSerializer(a.panoramas.all(), many=True, context={'request': request}).data,
            'type_logement': logement.type_logement,
            'type_logement_libelle': logement.get_type_logement_display(),
            'nb_chambres': logement.nb_chambres,
            'nb_salons': logement.nb_salons,
            'nb_salles_de_bain': logement.nb_sdb,
            'surface_m2': logement.surface_m2,
            'meuble': logement.meuble,
            'loyer': a.prix,
            'caution_mois': logement.caution_mois,
            'avance_mois': logement.avance_mois,
            'frais_agence': logement.frais_agence,
            'compteur_eau_individuel': logement.compteur_eau_individuel,
            'compteur_electricite_individuel': logement.compteur_electricite_individuel,
            'equipements': logement.equipements,
            'disponibilite': logement.disponibilite,
            'disponible_a_partir_du': logement.disponible_a_partir_du,
            'localite_nom': logement.localite.nom if logement.localite_id else None,
            'quartier_nom': logement.quartier_geo.nom if logement.quartier_geo_id else None,
            'secteur': logement.secteur,
            'adresse_reperes': logement.adresse_reperes,
            'latitude': logement.localisation.y if logement.localisation else None,
            'longitude': logement.localisation.x if logement.localisation else None,
            'loueur': {
                'id': partenaire.id,
                'nom': partenaire.nom_commerce,
                'telephone_pro': partenaire.telephone_pro,
                'whatsapp': partenaire.whatsapp,
            },
            'autres_logements': [_carte(l, request) for l in autres],
        })


# ═══════════════════════════════════════════════════════════════════════
# VÉHICULES (Phase V1)
# ═══════════════════════════════════════════════════════════════════════

def _loueur_public(partenaire_id, types):
    return (ProfilPartenaire.objects
            .filter(pk=partenaire_id, type_partenaire__in=types,
                    statut=ProfilPartenaire.Statut.ACTIF, est_visible=True)
            .first())


def _vehicules_qs():
    return (Vehicule.objects.filter(article__type=Article.Type.VEHICULE, article__est_actif=True)
            .select_related('article', 'localite', 'quartier_geo')
            .prefetch_related(Prefetch('article__images', queryset=ArticleImage.objects.filter(est_active=True))))


def _carte_vehicule(v, request):
    a = v.article
    return {
        'id': a.id,
        'titre': a.nom,
        'photo': _photo_principale(a, request),
        'categorie_vehicule': v.categorie_vehicule,
        'categorie_libelle': v.get_categorie_vehicule_display(),
        'marque': v.marque,
        'modele': v.modele,
        'annee': v.annee,
        'nb_places': v.places,
        'boite_libelle': v.get_boite_vitesse_display(),
        'carburant_libelle': v.get_carburant_display(),
        'climatisation': v.climatisation,
        'prix_jour': a.prix,
        'prix_jour_avec_chauffeur': v.prix_jour_avec_chauffeur,
        'chauffeur_disponible': v.chauffeur_disponible,
        'chauffeur_obligatoire': v.chauffeur_obligatoire,
        'localisation_texte': _localisation_texte(v),
        'disponibilite': v.disponibilite,
    }


def _entier(valeur):
    try:
        return int(valeur)
    except (TypeError, ValueError):
        return None


class VehiculesParPartenaireView(APIView):
    """GET /api/v1/locations/partenaires/<id>/vehicules/
    ?categorie=&prix_max=&places_min=&boite=&avec_chauffeur=&disponible=1
    avec_chauffeur=1 : chauffeur disponible ; avec_chauffeur=0 : location
    sans chauffeur possible (chauffeur non obligatoire)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, partenaire_id):
        partenaire = _loueur_public(partenaire_id, [ProfilPartenaire.TypePartenaire.LOUEUR_VOITURE])
        if partenaire is None:
            return Response({'erreur': True, 'message': 'Loueur introuvable.'}, status=404)

        qs = _vehicules_qs().filter(article__partenaire=partenaire).order_by('article__prix', 'article_id')
        p = request.query_params
        if p.get('categorie'):
            qs = qs.filter(categorie_vehicule=p['categorie'])
        if _entier(p.get('prix_max')) is not None:
            qs = qs.filter(article__prix__lte=_entier(p['prix_max']))
        if _entier(p.get('places_min')) is not None:
            qs = qs.filter(places__gte=_entier(p['places_min']))
        if p.get('boite'):
            qs = qs.filter(boite_vitesse=p['boite'])
        if p.get('avec_chauffeur') in ('1', 'true', 'True'):
            qs = qs.filter(chauffeur_disponible=True)
        elif p.get('avec_chauffeur') in ('0', 'false', 'False'):
            qs = qs.filter(chauffeur_obligatoire=False)
        if p.get('disponible') == '1':
            qs = qs.filter(disponibilite=Vehicule.Disponibilite.DISPONIBLE)

        return Response({
            'loueur': {
                'id': partenaire.id,
                'nom': partenaire.nom_commerce,
                'logo': _url(request, partenaire.logo),
                'couverture': _url(request, partenaire.photo_couverture),
                'telephone_pro': partenaire.telephone_pro,
                'whatsapp': partenaire.whatsapp,
            },
            'resultats': [_carte_vehicule(v, request) for v in qs],
        })


class VehiculeDetailPublicView(APIView):
    """GET /api/v1/locations/vehicules/<id>/ — fiche complète en une
    réponse (galerie, panoramas, caractéristiques, tarifs, conditions,
    point de prise en charge, loueur, autres véhicules disponibles du même
    loueur, périodes indisponibles issues des réservations confirmées)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk):
        v = (Vehicule.objects
             .filter(article_id=pk, article__type=Article.Type.VEHICULE, article__est_actif=True)
             .select_related('article__partenaire', 'localite', 'quartier_geo')
             .prefetch_related(
                 Prefetch('article__images', queryset=ArticleImage.objects.filter(est_active=True).order_by('ordre')),
                 Prefetch('article__panoramas', queryset=Panorama.objects.filter(est_active=True).order_by('ordre')),
             ).first())
        if v is None:
            return Response({'erreur': True, 'message': 'Véhicule introuvable.'}, status=404)

        a = v.article
        partenaire = a.partenaire
        autres = (_vehicules_qs()
                  .filter(article__partenaire=partenaire, disponibilite=Vehicule.Disponibilite.DISPONIBLE)
                  .exclude(article_id=a.id)[:4])

        return Response({
            'id': a.id,
            'titre': a.nom,
            'description': a.description,
            'galerie': [_url(request, i.image) for i in a.images.all()],
            'panoramas': PanoramaSerializer(a.panoramas.all(), many=True, context={'request': request}).data,
            'categorie_vehicule': v.categorie_vehicule,
            'categorie_libelle': v.get_categorie_vehicule_display(),
            'marque': v.marque,
            'modele': v.modele,
            'annee': v.annee,
            'couleur': v.couleur,
            'nb_places': v.places,
            'boite': v.boite_vitesse,
            'boite_libelle': v.get_boite_vitesse_display(),
            'carburant': v.carburant,
            'carburant_libelle': v.get_carburant_display(),
            'climatisation': v.climatisation,
            'equipements': v.equipements,
            'equipements_libelles': [services.EQUIPEMENTS_VEHICULE_LIBELLES.get(e, e) for e in v.equipements],
            'prix_jour': a.prix,
            'prix_jour_avec_chauffeur': v.prix_jour_avec_chauffeur,
            'chauffeur_disponible': v.chauffeur_disponible,
            'chauffeur_obligatoire': v.chauffeur_obligatoire,
            'caution': v.caution,
            'km_inclus_par_jour': v.km_inclus_par_jour,
            'prix_km_supplementaire': v.prix_km_supplementaire,
            'carburant_inclus': v.carburant_inclus,
            'duree_min_jours': v.duree_min_jours,
            'zone_circulation': v.zone_circulation,
            'disponibilite': v.disponibilite,
            'disponibilite_libelle': v.get_disponibilite_display(),
            'localisation_texte': _localisation_texte(v),
            'localite_nom': v.localite.nom if v.localite_id else None,
            'quartier_nom': v.quartier_geo.nom if v.quartier_geo_id else None,
            'secteur': v.secteur,
            'adresse_reperes': v.adresse_reperes,
            'latitude': v.localisation.y if v.localisation else None,
            'longitude': v.localisation.x if v.localisation else None,
            'loueur': {
                'id': partenaire.id,
                'nom': partenaire.nom_commerce,
                'telephone_pro': partenaire.telephone_pro,
                'whatsapp': partenaire.whatsapp,
            },
            'autres_vehicules': [_carte_vehicule(x, request) for x in autres],
            'periodes_indisponibles': [
                {'date_debut': r['date_debut'], 'date_fin': r['date_fin']}
                for r in services.reservations_confirmees(a.id)],
        })


# ═══════════════════════════════════════════════════════════════════════
# ÉTABLISSEMENTS ET HÉBERGEMENTS (Phase V2)
# ═══════════════════════════════════════════════════════════════════════

def _hebergements_qs():
    return (Hebergement.objects
            .filter(article__type=Article.Type.HEBERGEMENT, article__est_actif=True)
            .select_related('article'))


def _periode(request):
    """(date_debut, date_fin, erreur) depuis ?date_debut=&date_fin=
    (AAAA-MM-JJ). (None, None, None) si aucune des deux n'est fournie."""
    from datetime import date
    p = request.query_params
    brut_debut, brut_fin = p.get('date_debut'), p.get('date_fin')
    if not brut_debut and not brut_fin:
        return None, None, None
    try:
        debut, fin = date.fromisoformat(brut_debut or ''), date.fromisoformat(brut_fin or '')
    except ValueError:
        return None, None, 'date_debut et date_fin attendues ensemble, au format AAAA-MM-JJ.'
    if fin <= debut:
        return None, None, 'date_fin doit être postérieure à date_debut (au moins 1 nuit).'
    return debut, fin, None


def _carte_hebergement(h, request):
    a = h.article
    return {
        'id': a.id,
        'titre': a.nom,
        'photo': _photo_principale(a, request),
        'type_hebergement': h.type_hebergement,
        'type_hebergement_libelle': h.get_type_hebergement_display(),
        'capacite_adultes': h.capacite_adultes,
        'capacite_enfants': h.capacite_enfants,
        'lits': h.lits,
        'prix_nuit': a.prix,
        'prix_semaine': h.prix_semaine,
        'prix_mois': h.prix_mois,
        'disponibilite': h.disponibilite,
    }


class EtablissementPublicView(APIView):
    """GET /api/v1/locations/partenaires/<id>/etablissement/ — fiche
    établissement + hébergements actifs. Localisation, contacts, logo,
    couverture, description = ceux du partenaire. galerie / panoramas =
    images et panoramas actifs de ses hébergements (pas de galerie propre
    à l'établissement : aucun modèle dupliqué). Requêtes constantes."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, partenaire_id):
        partenaire = (ProfilPartenaire.objects
                      .filter(pk=partenaire_id, type_partenaire=ProfilPartenaire.TypePartenaire.HOTELIER,
                              statut=ProfilPartenaire.Statut.ACTIF, est_visible=True)
                      .select_related('profil_etablissement', 'localite', 'quartier_geo').first())
        if partenaire is None:
            return Response({'erreur': True, 'message': 'Établissement introuvable.'}, status=404)
        fiche = services.fiche_etablissement(partenaire)
        hebergements = list(
            _hebergements_qs().filter(article__partenaire=partenaire)
            .order_by('article__prix', 'article_id')
            .prefetch_related(
                Prefetch('article__images', queryset=ArticleImage.objects.filter(est_active=True).order_by('ordre')),
                Prefetch('article__panoramas', queryset=Panorama.objects.filter(est_active=True).order_by('ordre'))))
        panoramas = [pano for h in hebergements for pano in h.article.panoramas.all()]

        return Response({
            'etablissement': {
                'id': partenaire.id,
                'nom': partenaire.nom_commerce,
                'logo': _url(request, partenaire.logo),
                'couverture': _url(request, partenaire.photo_couverture),
                'galerie': [_url(request, i.image) for h in hebergements for i in h.article.images.all()],
                'panoramas': PanoramaSerializer(panoramas, many=True, context={'request': request}).data,
                'type_etablissement': fiche.type_etablissement,
                'type_etablissement_libelle': fiche.get_type_etablissement_display(),
                'etoiles': fiche.etoiles,
                'description': partenaire.description,
                'localisation_texte': _localisation_texte(partenaire),
                'latitude': partenaire.localisation.y if partenaire.localisation else None,
                'longitude': partenaire.localisation.x if partenaire.localisation else None,
                'telephone_pro': partenaire.telephone_pro,
                'whatsapp': partenaire.whatsapp,
                'heure_arrivee': fiche.heure_arrivee,
                'heure_depart': fiche.heure_depart,
                'equipements_etablissement': fiche.equipements,
                'equipements_etablissement_libelles': services.libelles(
                    fiche.equipements, services.EQUIPEMENTS_ETABLISSEMENT_LIBELLES),
                'petit_dejeuner': fiche.petit_dejeuner,
                'petit_dejeuner_libelle': fiche.get_petit_dejeuner_display(),
                'prix_petit_dejeuner': fiche.prix_petit_dejeuner,
                'politique_annulation': fiche.politique_annulation,
                'conditions': fiche.conditions,
            },
            'hebergements': [_carte_hebergement(h, request) for h in hebergements],
        })


def _hebergement_public(pk, avec_medias=False):
    qs = _hebergements_qs().filter(article_id=pk).select_related(
        'article__partenaire__profil_etablissement')
    if avec_medias:
        qs = qs.prefetch_related(
            Prefetch('article__images', queryset=ArticleImage.objects.filter(est_active=True).order_by('ordre')),
            Prefetch('article__panoramas', queryset=Panorama.objects.filter(est_active=True).order_by('ordre')))
    return qs.first()


class HebergementDetailPublicView(APIView):
    """GET /api/v1/locations/hebergements/<id>/?date_debut=&date_fin= —
    fiche complète ; unites_disponibles calculé si les dates sont fournies
    (null sinon)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk):
        debut, fin, erreur = _periode(request)
        if erreur:
            return Response({'erreur': True, 'message': erreur}, status=400)
        h = _hebergement_public(pk, avec_medias=True)
        if h is None:
            return Response({'erreur': True, 'message': 'Hébergement introuvable.'}, status=404)
        a = h.article
        fiche = services.fiche_etablissement(a.partenaire)
        return Response({
            'id': a.id,
            'titre': a.nom,
            'description': a.description,
            'galerie': [_url(request, i.image) for i in a.images.all()],
            'panoramas': PanoramaSerializer(a.panoramas.all(), many=True, context={'request': request}).data,
            'type_hebergement': h.type_hebergement,
            'type_hebergement_libelle': h.get_type_hebergement_display(),
            'capacite_adultes': h.capacite_adultes,
            'capacite_enfants': h.capacite_enfants,
            'lits': h.lits,
            'surface_m2': h.surface_m2,
            'equipements_hebergement': h.equipements,
            'equipements_hebergement_libelles': services.libelles(
                h.equipements, services.EQUIPEMENTS_HEBERGEMENT_LIBELLES),
            'prix_nuit': a.prix,
            'prix_semaine': h.prix_semaine,
            'prix_mois': h.prix_mois,
            'nb_unites': h.nb_unites,
            'duree_min_nuits': h.duree_min_nuits,
            'disponibilite': h.disponibilite,
            'disponibilite_libelle': h.get_disponibilite_display(),
            'etablissement': {
                'id': a.partenaire_id,
                'nom': a.partenaire.nom_commerce,
                'heure_arrivee': fiche.heure_arrivee,
                'heure_depart': fiche.heure_depart,
                'petit_dejeuner': fiche.petit_dejeuner,
                'petit_dejeuner_libelle': fiche.get_petit_dejeuner_display(),
                'prix_petit_dejeuner': fiche.prix_petit_dejeuner,
                'politique_annulation': fiche.politique_annulation,
            },
            'date_debut': debut,
            'date_fin': fin,
            'unites_disponibles': services.unites_disponibles(h, debut, fin) if debut else None,
        })


class HebergementDisponibilitePublicView(APIView):
    """GET /api/v1/locations/hebergements/<id>/disponibilite/?date_debut=&date_fin=
    → {unites_disponibles} (dates obligatoires)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk):
        debut, fin, erreur = _periode(request)
        if erreur or debut is None:
            return Response({'erreur': True, 'message': erreur or 'date_debut et date_fin sont requises.'},
                            status=400)
        h = _hebergement_public(pk)
        if h is None:
            return Response({'erreur': True, 'message': 'Hébergement introuvable.'}, status=404)
        return Response({'date_debut': debut, 'date_fin': fin,
                         'unites_disponibles': services.unites_disponibles(h, debut, fin)})


class MetaLocationsView(APIView):
    """GET /api/v1/locations/meta/ — référentiels publics, construits
    depuis les choix réellement validés par le backend (aucune liste
    recopiée à la main)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from .services import EQUIPEMENTS_LIBELLES
        return Response({
            'types_logement': [{'valeur': v, 'libelle': l} for v, l in Logement.TypeLogement.choices],
            'equipements': [{'valeur': v, 'libelle': l} for v, l in EQUIPEMENTS_LIBELLES.items()],
            'disponibilites': [{'valeur': v, 'libelle': l} for v, l in Logement.Disponibilite.choices],
            # Phase V1 (véhicules)
            'categories_vehicule': [{'valeur': v, 'libelle': l}
                                    for v, l in Vehicule.CategorieVehicule.choices],
            'boites': [{'valeur': v, 'libelle': l} for v, l in Vehicule.BoiteVitesse.choices],
            'carburants': [{'valeur': v, 'libelle': l} for v, l in Vehicule.Carburant.choices],
            'equipements_vehicule': [{'valeur': v, 'libelle': l}
                                     for v, l in services.EQUIPEMENTS_VEHICULE_LIBELLES.items()],
            # Phase V2 (hôtels, résidences meublées)
            'types_etablissement': [{'valeur': v, 'libelle': l}
                                    for v, l in ProfilEtablissement.TypeEtablissement.choices],
            'types_hebergement': [{'valeur': v, 'libelle': l}
                                  for v, l in Hebergement.TypeHebergement.choices],
            'equipements_etablissement': [{'valeur': v, 'libelle': l}
                                          for v, l in services.EQUIPEMENTS_ETABLISSEMENT_LIBELLES.items()],
            'equipements_hebergement': [{'valeur': v, 'libelle': l}
                                        for v, l in services.EQUIPEMENTS_HEBERGEMENT_LIBELLES.items()],
            'petit_dejeuner': [{'valeur': v, 'libelle': l}
                               for v, l in ProfilEtablissement.PetitDejeuner.choices],
        })
