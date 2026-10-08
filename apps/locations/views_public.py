"""Lecture publique des logements (Locations Phase M1) et des véhicules
(Phase V1). AllowAny — même mur
d'inscription que le reste du catalogue : aucune règle nouvelle."""
from django.db.models import Prefetch
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Article, ArticleImage, Logement, Panorama, Vehicule
from apps.catalog.serializers import PanoramaSerializer
from apps.users.models import ProfilPartenaire

from . import services


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
        })
