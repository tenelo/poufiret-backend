"""Serializers admin (CRUD complet) de la géographie.

Distincts des serializers publics (apps.geo.serializers, INCHANGÉS) : ceux-ci
exposent l'édition (nom, actif, parent) et les infos de supervision (parent,
ancêtres, nombre d'enfants directs, horodatage) pour l'admin Angular.
Réservés à ADroitDe('gerer_geographie') — voir apps.geo.admin_views.

Le champ modèle `est_actif` est exposé côté API sous le nom `actif` (celui
demandé pour ce CRUD), sans renommer la colonne DB : `source='est_actif'`
fait le pont, on garde ainsi la convention `est_actif`/`est_active` déjà
utilisée partout ailleurs dans le projet (Departement, Quartier, Categorie...).
"""
from rest_framework import serializers

from .models import Departement, Localite, Quartier, Region


class RegionAdminSerializer(serializers.ModelSerializer):
    actif = serializers.BooleanField(source='est_actif', required=False)
    parent_id = serializers.IntegerField(source='district_id', read_only=True)
    parent_nom = serializers.CharField(source='district.nom', read_only=True)
    nb_enfants = serializers.SerializerMethodField()

    class Meta:
        model = Region
        fields = ['id', 'nom', 'actif', 'district', 'parent_id', 'parent_nom',
                  'nb_enfants', 'cree_le', 'modifie_le']
        extra_kwargs = {'district': {'write_only': True}}

    def get_nb_enfants(self, obj):
        return obj.departements.count()

    def validate(self, attrs):
        nom = (attrs.get('nom') if 'nom' in attrs else getattr(self.instance, 'nom', '') or '')
        nom = nom.strip()
        if not nom:
            raise serializers.ValidationError({'nom': ['Le nom est requis.']})
        qs = Region.objects.filter(nom__iexact=nom)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                {'nom': [f'Une région « {nom} » existe déjà.']})
        attrs['nom'] = nom
        return attrs


class DepartementAdminSerializer(serializers.ModelSerializer):
    actif = serializers.BooleanField(source='est_actif', required=False)
    parent_id = serializers.IntegerField(source='region_id', read_only=True)
    parent_nom = serializers.CharField(source='region.nom', read_only=True)
    region_nom = serializers.CharField(source='region.nom', read_only=True)
    district_nom = serializers.CharField(source='region.district.nom', read_only=True)
    nb_enfants = serializers.SerializerMethodField()

    class Meta:
        model = Departement
        fields = ['id', 'nom', 'actif', 'region', 'parent_id', 'parent_nom',
                  'region_nom', 'district_nom', 'nb_enfants',
                  'cree_le', 'modifie_le']
        extra_kwargs = {'region': {'write_only': True}}

    def get_nb_enfants(self, obj):
        return obj.localites.count()

    def validate(self, attrs):
        nom = (attrs.get('nom') if 'nom' in attrs else getattr(self.instance, 'nom', '') or '')
        nom = nom.strip()
        region = attrs.get('region') or getattr(self.instance, 'region', None)
        if not nom:
            raise serializers.ValidationError({'nom': ['Le nom est requis.']})
        if region is None:
            raise serializers.ValidationError({'region': ['La région est requise.']})
        qs = Departement.objects.filter(region=region, nom__iexact=nom)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                {'nom': [f'Un département « {nom} » existe déjà dans cette région.']})
        attrs['nom'] = nom
        return attrs


class LocaliteAdminSerializer(serializers.ModelSerializer):
    actif = serializers.BooleanField(source='est_actif', required=False)
    parent_id = serializers.IntegerField(source='departement_id', read_only=True)
    parent_nom = serializers.CharField(source='departement.nom', read_only=True)
    departement_nom = serializers.CharField(source='departement.nom', read_only=True)
    region_nom = serializers.CharField(source='departement.region.nom', read_only=True)
    district_nom = serializers.CharField(
        source='departement.region.district.nom', read_only=True)
    nb_enfants = serializers.SerializerMethodField()

    class Meta:
        model = Localite
        fields = ['id', 'nom', 'actif', 'departement', 'parent_id', 'parent_nom',
                  'departement_nom', 'region_nom', 'district_nom', 'nb_enfants',
                  'cree_le', 'modifie_le']
        extra_kwargs = {'departement': {'write_only': True}}

    def get_nb_enfants(self, obj):
        return obj.quartiers.count()

    def validate(self, attrs):
        nom = (attrs.get('nom') if 'nom' in attrs else getattr(self.instance, 'nom', '') or '')
        nom = nom.strip()
        departement = attrs.get('departement') or getattr(self.instance, 'departement', None)
        if not nom:
            raise serializers.ValidationError({'nom': ['Le nom est requis.']})
        if departement is None:
            raise serializers.ValidationError({'departement': ['Le département est requis.']})
        qs = Localite.objects.filter(departement=departement, nom__iexact=nom)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                {'nom': [f'Une localité « {nom} » existe déjà dans ce département.']})
        attrs['nom'] = nom
        return attrs


class QuartierAdminSerializer(serializers.ModelSerializer):
    actif = serializers.BooleanField(source='est_actif', required=False)
    parent_id = serializers.IntegerField(source='localite_id', read_only=True)
    parent_nom = serializers.CharField(source='localite.nom', read_only=True)
    localite_nom = serializers.CharField(source='localite.nom', read_only=True)
    departement_nom = serializers.CharField(
        source='localite.departement.nom', read_only=True)
    region_nom = serializers.CharField(
        source='localite.departement.region.nom', read_only=True)
    nb_enfants = serializers.SerializerMethodField()

    class Meta:
        model = Quartier
        fields = ['id', 'nom', 'actif', 'localite', 'parent_id', 'parent_nom',
                  'localite_nom', 'departement_nom', 'region_nom', 'nb_enfants',
                  'cree_le', 'modifie_le']
        extra_kwargs = {'localite': {'write_only': True}}

    def get_nb_enfants(self, obj):
        return 0  # niveau le plus fin, jamais d'enfants

    def validate(self, attrs):
        nom = (attrs.get('nom') if 'nom' in attrs else getattr(self.instance, 'nom', '') or '')
        nom = nom.strip()
        localite = attrs.get('localite') or getattr(self.instance, 'localite', None)
        if not nom:
            raise serializers.ValidationError({'nom': ['Le nom est requis.']})
        if localite is None:
            raise serializers.ValidationError({'localite': ['La localité est requise.']})
        qs = Quartier.objects.filter(localite=localite, nom__iexact=nom)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                {'nom': [f'Un quartier « {nom} » existe déjà dans cette localité.']})
        attrs['nom'] = nom
        return attrs
