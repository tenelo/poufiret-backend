"""Lecture publique des logements (Locations Phase M1). AllowAny — même mur
d'inscription que le reste du catalogue : aucune règle nouvelle."""
from django.db.models import Prefetch
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Article, ArticleImage, Logement, Panorama
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


def _localisation_texte(logement):
    return ' - '.join(filter(None, [
        logement.localite.nom if logement.localite_id else None,
        logement.quartier_geo.nom if logement.quartier_geo_id else None,
        logement.secteur or None,
    ]))


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
        })
