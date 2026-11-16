"""Serializers admin des pubs Poufiret, des écrans du parcours et des
réglages (capacité gerer_pubs_poufiret)."""
from rest_framework import serializers

from . import services_poufiret as sp
from .models import EcranDecouverte, ParametresPoufiret, PubPoufiret


class PubPoufiretAdminSerializer(serializers.ModelSerializer):
    """Contexte facultatif : `accessibles` (ids de catégories ouvrables) et
    `par_type` ({pub_id: {emplacement: n}}) pour une liste sans requête par
    ligne."""
    categorie_nom = serializers.CharField(source='categorie.nom', read_only=True, default=None)
    categorie_disponible = serializers.SerializerMethodField()
    taux_clic = serializers.SerializerMethodField()
    impressions_par_type = serializers.SerializerMethodField()

    class Meta:
        model = PubPoufiret
        fields = ['id', 'titre', 'texte', 'image_couverture', 'categorie', 'categorie_nom',
                  'categorie_disponible', 'est_active', 'ordre', 'date_debut', 'date_fin',
                  'portee', 'region', 'departement',
                  'nb_impressions', 'nb_clics', 'taux_clic', 'nb_personnes_touchees',
                  'impressions_par_type', 'cree_le', 'modifie_le']
        read_only_fields = ['id', 'nb_impressions', 'nb_clics', 'nb_personnes_touchees',
                            'cree_le', 'modifie_le']
        extra_kwargs = {'categorie': {'required': True, 'allow_null': False}}

    def _accessibles(self):
        if 'accessibles' not in self.context:
            self.context['accessibles'] = sp.categories_accessibles()
        return self.context['accessibles']

    def get_categorie_disponible(self, obj):
        return obj.categorie_id is not None and obj.categorie_id in self._accessibles()

    def get_taux_clic(self, obj):
        return sp.taux_clic(obj.nb_clics, obj.nb_impressions)

    def get_impressions_par_type(self, obj):
        par_type = self.context.get('par_type')
        if par_type is not None and obj.pk in par_type:
            return par_type[obj.pk]
        return sp.impressions_par_type([obj.pk])[obj.pk]

    def validate_categorie(self, categorie):
        raison = sp.raison_categorie_invalide(categorie)
        if raison:
            raise serializers.ValidationError(raison)
        return categorie

    def validate(self, attrs):
        inst = self.instance

        def val(nom):
            return attrs[nom] if nom in attrs else getattr(inst, nom, None)

        debut, fin = val('date_debut'), val('date_fin')
        if debut and fin and fin <= debut:
            raise serializers.ValidationError({'date_fin': 'La date de fin doit être après la date de début.'})
        portee = val('portee') or PubPoufiret.Portee.TOUT
        if portee == PubPoufiret.Portee.REGION:
            if not val('region'):
                raise serializers.ValidationError({'region': 'Région obligatoire pour une portée « région ».'})
            attrs['departement'] = None
        elif portee == PubPoufiret.Portee.DEPARTEMENT:
            if not val('departement'):
                raise serializers.ValidationError(
                    {'departement': 'Département obligatoire pour une portée « département ».'})
            attrs['region'] = None
        else:
            attrs['region'] = attrs['departement'] = None
        return attrs


class EcranDecouverteAdminSerializer(serializers.ModelSerializer):
    bouton_categorie_nom = serializers.CharField(source='bouton_categorie.nom', read_only=True, default=None)
    bouton_categorie_disponible = serializers.SerializerMethodField()

    class Meta:
        model = EcranDecouverte
        fields = ['id', 'ordre', 'image', 'titre', 'texte', 'bouton_libelle', 'bouton_categorie',
                  'bouton_categorie_nom', 'bouton_categorie_disponible', 'est_actif',
                  'cree_le', 'modifie_le']
        read_only_fields = ['id', 'cree_le', 'modifie_le']

    def get_bouton_categorie_disponible(self, obj):
        if obj.bouton_categorie_id is None:
            return None
        if 'accessibles' not in self.context:
            self.context['accessibles'] = sp.categories_accessibles()
        return obj.bouton_categorie_id in self.context['accessibles']

    def validate_bouton_categorie(self, categorie):
        if categorie is not None:
            raison = sp.raison_categorie_invalide(categorie)
            if raison:
                raise serializers.ValidationError(raison)
        return categorie

    def validate(self, attrs):
        inst = self.instance
        libelle = attrs['bouton_libelle'] if 'bouton_libelle' in attrs else getattr(inst, 'bouton_libelle', '')
        cat = attrs['bouton_categorie'] if 'bouton_categorie' in attrs else getattr(inst, 'bouton_categorie', None)
        if bool((libelle or '').strip()) != (cat is not None):
            raise serializers.ValidationError(
                {'bouton_libelle': 'Le bouton demande un libellé ET une catégorie (ou aucun des deux).'})
        return attrs


class ParametresPoufiretSerializer(serializers.ModelSerializer):
    frequence_pub_maison = serializers.IntegerField(min_value=1, max_value=50, required=False)
    duree_affichage_secondes = serializers.IntegerField(min_value=1, max_value=60, required=False)

    class Meta:
        model = ParametresPoufiret
        fields = ['pubs_maison_actives', 'frequence_pub_maison', 'duree_affichage_secondes',
                  'parcours_actif', 'version_parcours', 'modifie_le']
        read_only_fields = ['version_parcours', 'modifie_le']

    def validate_parcours_actif(self, valeur):
        if valeur and not (self.instance and self.instance.parcours_actif):
            raison = sp.raison_refus_parcours()
            if raison:
                raise serializers.ValidationError(raison)
        return valeur
