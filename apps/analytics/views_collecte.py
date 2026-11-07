"""Collecte pour analyses / IA : clic sur un résultat de recherche et
événements envoyés par le client (appel, WhatsApp, partage, itinéraire).
Écritures via apps.analytics.collecte (consentement, best-effort)."""
import json

from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from apps.catalog.models import Categorie
from apps.core.exceptions import ErreurMetier
from apps.users.models import ProfilPartenaire

from . import collecte
from .models import EvenementApp, Plateforme, RechercheLog

MAX_EVENEMENTS_PAR_ENVOI = 50
TAILLE_MAX_DONNEES = 2000  # caractères JSON par événement


class _CollecteAnonThrottle(AnonRateThrottle):
    scope = 'collecte_anon'
    rate = '60/min'


class _CollecteUserThrottle(UserRateThrottle):
    scope = 'collecte_user'
    rate = '120/min'


_THROTTLES = [_CollecteAnonThrottle, _CollecteUserThrottle]


class RechercheClicView(APIView):
    """POST /api/v1/analytics/recherches/<id>/clic/ {resultat_type, resultat_id}
    — enregistre le résultat touché après une recherche. Une seule fois ; par
    l'auteur de la recherche (ou n'importe qui si la recherche est anonyme)."""
    permission_classes = [AllowAny]
    throttle_classes = _THROTTLES

    def post(self, request, pk=None):
        ligne = RechercheLog.objects.filter(pk=pk).first()
        if ligne is None:
            raise ErreurMetier('Recherche introuvable.', status_code=404)
        if ligne.utilisateur_id and ligne.utilisateur_id != getattr(request.user, 'id', None):
            raise ErreurMetier("Cette recherche n'est pas la vôtre.", status_code=403)
        type_resultat = request.data.get('resultat_type')
        if type_resultat not in RechercheLog.TypeResultat.values:
            raise ErreurMetier('resultat_type invalide (attendu : article ou partenaire).',
                               {'resultat_type': list(RechercheLog.TypeResultat.values)})
        resultat_id = str(request.data.get('resultat_id') or '').strip()
        if not resultat_id or len(resultat_id) > 64:
            raise ErreurMetier('resultat_id requis (64 caractères au plus).')
        # Mise à jour conditionnelle : un seul clic enregistré, même en cas d'envois simultanés.
        n = RechercheLog.objects.filter(pk=ligne.pk, clique_le__isnull=True).update(
            resultat_type=type_resultat, resultat_id=resultat_id, clique_le=timezone.now())
        if n == 0:
            raise ErreurMetier('Un résultat a déjà été enregistré pour cette recherche.', status_code=409)
        ligne.refresh_from_db()
        return Response({'id': ligne.id, 'resultat_type': ligne.resultat_type,
                         'resultat_id': ligne.resultat_id, 'clique_le': ligne.clique_le})


class EvenementClientSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=collecte.TYPES_EVENEMENTS_CLIENT)
    partenaire_id = serializers.IntegerField(required=False, allow_null=True)
    objet_type = serializers.CharField(required=False, allow_blank=True, max_length=30, default='')
    objet_id = serializers.CharField(required=False, allow_blank=True, max_length=64, default='')
    categorie_id = serializers.IntegerField(required=False, allow_null=True)
    valeur = serializers.DecimalField(required=False, allow_null=True, max_digits=12, decimal_places=2)
    donnees = serializers.DictField(required=False, default=dict)
    plateforme = serializers.ChoiceField(choices=Plateforme.values, required=False)
    version_app = serializers.CharField(required=False, allow_blank=True, max_length=20)

    def validate_partenaire_id(self, valeur):
        if valeur is not None and not ProfilPartenaire.objects.filter(pk=valeur).exists():
            raise serializers.ValidationError('Partenaire introuvable.')
        return valeur

    def validate_categorie_id(self, valeur):
        if valeur is not None and not Categorie.objects.filter(pk=valeur).exists():
            raise serializers.ValidationError('Catégorie introuvable.')
        return valeur

    def validate_donnees(self, valeur):
        if len(json.dumps(valeur, default=str)) > TAILLE_MAX_DONNEES:
            raise serializers.ValidationError(f'donnees trop volumineuses ({TAILLE_MAX_DONNEES} caractères max).')
        return valeur


class EvenementsClientView(APIView):
    """POST /api/v1/analytics/evenements/ — un événement (objet) ou une liste
    (50 au plus). Types autorisés : appel_partenaire, whatsapp_partenaire,
    partage_article, partage_partenaire, itineraire_partenaire. Validation
    stricte, tout ou rien : un élément invalide → 400, rien n'est enregistré."""
    permission_classes = [AllowAny]
    throttle_classes = _THROTTLES

    def post(self, request):
        donnees = request.data
        if isinstance(donnees, dict):
            elements = [donnees]
        elif isinstance(donnees, list):
            elements = donnees
        else:
            raise ErreurMetier('Corps attendu : un événement (objet) ou une liste d\'événements.')
        if not elements:
            raise ErreurMetier('Liste vide.')
        if len(elements) > MAX_EVENEMENTS_PAR_ENVOI:
            raise ErreurMetier(f'{MAX_EVENEMENTS_PAR_ENVOI} événements au plus par envoi.',
                               {'nb_recus': len(elements)})
        ser = EvenementClientSerializer(data=elements, many=True)
        if not ser.is_valid():
            erreurs = {str(i): e for i, e in enumerate(ser.errors) if e}
            raise ErreurMetier('Événement(s) invalide(s) : rien n\'a été enregistré.', erreurs)
        crees = 0
        for e in ser.validated_data:
            if collecte.enregistrer_evenement(
                    e['type'], request=request, partenaire=(ProfilPartenaire(pk=e['partenaire_id'])
                                                            if e.get('partenaire_id') else None),
                    objet_type=e.get('objet_type', ''), objet_id=e.get('objet_id', ''),
                    categorie=Categorie(pk=e['categorie_id']) if e.get('categorie_id') else None,
                    valeur=e.get('valeur'), donnees=e.get('donnees') or {},
                    plateforme=e.get('plateforme'), version_app=e.get('version_app')):
                crees += 1
        return Response({'nb_enregistres': crees}, status=status.HTTP_201_CREATED)
