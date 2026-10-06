"""Fiche partenaire éditable par l'admin (droit creer_partenaire, super-admin
toujours). Numéro de connexion et position GPS restent sur leurs routes dédiées.
"""
from django.db import transaction
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Categorie, PartenaireCategorie
from apps.core.permissions import ADroitDe
from apps.geo.coherence import verifier_coherence
from apps.geo.models import Departement, Localite, Quartier
from apps.users.models import ProfilPartenaire

from .moderation import _journaliser
from .models import JournalModeration

_PERMISSION = [IsAuthenticated, ADroitDe('creer_partenaire')]
TYPES = ProfilPartenaire.TypePartenaire
CHAMPS_TEXTE_COURTS = ('nom_commerce', 'type_partenaire', 'secteur', 'adresse',
                       'telephone_pro', 'whatsapp', 'email_pro')
CHAMPS_TEXTE_USER = ('prenom', 'nom')


class EditionSerializer(serializers.Serializer):
    prenom = serializers.CharField(max_length=150, required=False, allow_blank=True)
    nom = serializers.CharField(max_length=150, required=False, allow_blank=True)
    nom_commerce = serializers.CharField(max_length=150, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    type_partenaire = serializers.ChoiceField(choices=TYPES.choices, required=False)
    categories = serializers.ListField(child=serializers.IntegerField(), required=False)
    departement = serializers.PrimaryKeyRelatedField(
        queryset=Departement.objects.all(), required=False, allow_null=True)
    localite_id = serializers.PrimaryKeyRelatedField(
        source='localite', queryset=Localite.objects.filter(est_actif=True),
        required=False, allow_null=True)
    quartier_id = serializers.PrimaryKeyRelatedField(
        source='quartier_geo', queryset=Quartier.objects.filter(est_actif=True),
        required=False, allow_null=True)
    secteur = serializers.CharField(max_length=100, required=False, allow_blank=True)
    adresse = serializers.CharField(max_length=255, required=False, allow_blank=True)
    telephone_pro = serializers.CharField(max_length=20, required=False, allow_blank=True)
    whatsapp = serializers.CharField(max_length=20, required=False, allow_blank=True)
    email_pro = serializers.EmailField(required=False, allow_blank=True)
    logo = serializers.ImageField(required=False, allow_null=True)
    photo_couverture = serializers.ImageField(required=False, allow_null=True)
    supprimer_logo = serializers.BooleanField(required=False)
    supprimer_couverture = serializers.BooleanField(required=False)

    def validate_categories(self, ids):
        uniques = list(dict.fromkeys(ids))
        existantes = set(Categorie.objects.filter(id__in=uniques, est_active=True, est_archivee=False)
                         .values_list('id', flat=True))
        inconnues = [i for i in uniques if i not in existantes]
        if inconnues:
            raise serializers.ValidationError(f'Catégories inconnues ou inactives : {inconnues}')
        return uniques

    def validate(self, attrs):
        profil = self.context['profil']
        dep = attrs['departement'] if 'departement' in attrs else profil.departement
        loc = attrs['localite'] if 'localite' in attrs else profil.localite
        quart = attrs['quartier_geo'] if 'quartier_geo' in attrs else profil.quartier_geo
        if dep is None and loc is not None:
            dep = loc.departement
            attrs['departement'] = dep
        erreurs = verifier_coherence(dep, loc, quart)
        if erreurs:
            raise serializers.ValidationError(erreurs)
        return attrs


def _url(request, champ):
    if not champ:
        return None
    try:
        return request.build_absolute_uri(champ.url)
    except ValueError:
        return None


def _fiche(profil, request):
    liens = PartenaireCategorie.objects.filter(partenaire=profil).select_related('categorie').order_by('-est_principale', 'id')
    return {
        'id': profil.id,
        'prenom': profil.user.first_name,
        'nom': profil.user.last_name,
        'nom_commerce': profil.nom_commerce,
        'description': profil.description,
        'type_partenaire': profil.type_partenaire,
        'type_partenaire_libelle': profil.get_type_partenaire_display(),
        'categories': [{'id': l.categorie_id, 'nom': l.categorie.nom} for l in liens],
        'departement': profil.departement_id,
        'departement_nom': profil.departement.nom if profil.departement_id else None,
        'localite_id': profil.localite_id,
        'localite_nom': profil.localite.nom if profil.localite_id else None,
        'quartier_id': profil.quartier_geo_id,
        'quartier_nom': profil.quartier_geo.nom if profil.quartier_geo_id else None,
        'secteur': profil.secteur,
        'adresse': profil.adresse,
        'telephone_pro': profil.telephone_pro,
        'whatsapp': profil.whatsapp,
        'email_pro': profil.email_pro,
        'logo': _url(request, profil.logo),
        'photo_couverture': _url(request, profil.photo_couverture),
    }


def _appliquer_categories(profil, ids):
    """Remplace les liens : la première catégorie devient la principale."""
    PartenaireCategorie.objects.filter(partenaire=profil).exclude(categorie_id__in=ids).delete()
    for rang, cid in enumerate(ids):
        lien, _cree = PartenaireCategorie.objects.get_or_create(
            partenaire=profil, categorie_id=cid, defaults={'est_principale': rang == 0})
        if lien.est_principale != (rang == 0):
            lien.est_principale = rang == 0
            lien.save(update_fields=['est_principale'])


class PartenaireEditionView(APIView):
    """GET/PATCH /administration/partenaires/<id>/edition/ (pk = ProfilPartenaire.pk)."""
    permission_classes = _PERMISSION

    def _profil(self, pk):
        return (ProfilPartenaire.objects.select_related('user', 'departement', 'localite', 'quartier_geo')
                .filter(pk=pk).first())

    def get(self, request, pk):
        profil = self._profil(pk)
        if profil is None:
            return Response({'erreur': True, 'message': 'Partenaire introuvable.'}, status=404)
        return Response(_fiche(profil, request))

    def patch(self, request, pk):
        profil = self._profil(pk)
        if profil is None:
            return Response({'erreur': True, 'message': 'Partenaire introuvable.'}, status=404)
        ser = EditionSerializer(data=request.data, partial=True, context={'profil': profil})
        if not ser.is_valid():
            return Response({'erreur': True, 'details': ser.errors}, status=400)
        v = ser.validated_data
        changements = []

        with transaction.atomic():
            user = profil.user
            maj_user = []
            for champ, attr in (('prenom', 'first_name'), ('nom', 'last_name')):
                if champ in v and v[champ] != getattr(user, attr):
                    ancien = getattr(user, attr)
                    setattr(user, attr, v[champ])
                    maj_user.append(attr)
                    changements.append(f'{champ} ({ancien} → {v[champ]})')
            if maj_user:
                user.save(update_fields=maj_user)

            if 'categories' in v:
                avant = [l.categorie_id for l in PartenaireCategorie.objects.filter(
                    partenaire=profil).order_by('-est_principale', 'id')]
                if avant != v['categories']:
                    _appliquer_categories(profil, v['categories'])
                    changements.append('categories')

            for champ in ('nom_commerce', 'description', 'type_partenaire', 'secteur', 'adresse',
                          'telephone_pro', 'whatsapp', 'email_pro'):
                if champ in v and v[champ] != getattr(profil, champ):
                    ancien = getattr(profil, champ)
                    setattr(profil, champ, v[champ])
                    changements.append(f'{champ} ({ancien} → {v[champ]})' if champ in CHAMPS_TEXTE_COURTS
                                       else champ)
            for champ in ('departement', 'localite', 'quartier_geo'):
                if champ in v and getattr(profil, f'{champ}_id') != (v[champ].id if v[champ] else None):
                    setattr(profil, champ, v[champ])
                    changements.append(champ)

            for champ, supprimer in (('logo', 'supprimer_logo'), ('photo_couverture', 'supprimer_couverture')):
                fichier = getattr(profil, champ)
                nouveau = v.get(champ)
                if nouveau is not None or (champ in v and nouveau is None) or v.get(supprimer):
                    if fichier:
                        fichier.delete(save=False)
                    setattr(profil, champ, nouveau)
                    changements.append(f'{champ} ({"remplacé" if nouveau is not None else "retiré"})')

            profil.save()
            if changements:
                _journaliser(request.user, profil.user, JournalModeration.Action.PARTENAIRE_EDITION,
                             ' ; '.join(changements)[:255])

        return Response(_fiche(profil, request))
