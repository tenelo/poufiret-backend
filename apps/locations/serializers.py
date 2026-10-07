"""Sérialiseur d'écriture des logements (Article + Logement, une seule
ressource). La lecture passe par apps.locations.services.logement_dict,
pas par ce sérialiseur (évite de mélanger champs écrits/dérivés)."""
from rest_framework import serializers

from apps.catalog.models import Logement
from apps.geo.coherence import verifier_coherence
from apps.geo.models import Localite, Quartier

from .services import valider_equipements


class LogementGestionSerializer(serializers.Serializer):
    """context requis : partenaire, acteur_role, acteur_nom."""
    nom = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True)
    prix = serializers.DecimalField(max_digits=12, decimal_places=0)
    est_actif = serializers.BooleanField(required=False)

    type_logement = serializers.ChoiceField(choices=Logement.TypeLogement.choices)
    nb_chambres = serializers.IntegerField(required=False, min_value=0)
    nb_salons = serializers.IntegerField(required=False, min_value=0)
    nb_salles_de_bain = serializers.IntegerField(source='nb_sdb', required=False, min_value=0)
    surface_m2 = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    meuble = serializers.BooleanField(required=False)
    caution_mois = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    avance_mois = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    frais_agence = serializers.DecimalField(
        max_digits=12, decimal_places=0, required=False, allow_null=True)
    compteur_eau_individuel = serializers.BooleanField(required=False)
    compteur_electricite_individuel = serializers.BooleanField(required=False)
    equipements = serializers.ListField(required=False)
    disponible_a_partir_du = serializers.DateField(required=False, allow_null=True)

    localite_id = serializers.PrimaryKeyRelatedField(
        source='localite', queryset=Localite.objects.filter(est_actif=True),
        required=False, allow_null=True)
    quartier_id = serializers.PrimaryKeyRelatedField(
        source='quartier_geo', queryset=Quartier.objects.filter(est_actif=True),
        required=False, allow_null=True)
    secteur = serializers.CharField(max_length=100, required=False, allow_blank=True)
    adresse_reperes = serializers.CharField(required=False, allow_blank=True)
    latitude = serializers.FloatField(
        required=False, allow_null=True, min_value=-90, max_value=90)
    longitude = serializers.FloatField(
        required=False, allow_null=True, min_value=-180, max_value=180)

    def validate_equipements(self, valeur):
        normalises = valider_equipements(valeur)
        if normalises is None:
            from .services import EQUIPEMENTS_REFERENTIEL
            raise serializers.ValidationError(
                f'Valeurs attendues parmi : {", ".join(EQUIPEMENTS_REFERENTIEL)}.')
        return normalises

    def validate(self, attrs):
        lat_in, lng_in = 'latitude' in attrs, 'longitude' in attrs
        if lat_in or lng_in:
            if not (lat_in and lng_in) or (attrs.get('latitude') is None) != (attrs.get('longitude') is None):
                msg = ['latitude et longitude doivent être fournis ensemble (ou null pour les deux).']
                raise serializers.ValidationError({'latitude': msg, 'longitude': msg})

        inst = self.instance
        partenaire = self.context['partenaire']
        localite = attrs['localite'] if 'localite' in attrs else (inst.localite if inst else None)
        quartier = attrs['quartier_geo'] if 'quartier_geo' in attrs else (inst.quartier_geo if inst else None)
        erreurs = verifier_coherence(partenaire.departement, localite, quartier)
        if erreurs:
            raise serializers.ValidationError(erreurs)
        return attrs

    def create(self, validated_data):
        from django.utils.text import slugify

        from apps.catalog.correspondances import categories_correspondantes
        from apps.catalog.models import Article
        from django.contrib.gis.geos import Point

        partenaire = self.context['partenaire']
        nom = validated_data.pop('nom')
        prix = validated_data.pop('prix')
        description = validated_data.pop('description', '')
        est_actif = validated_data.pop('est_actif', True)
        lat = validated_data.pop('latitude', None)
        lng = validated_data.pop('longitude', None)

        base = slugify(nom)[:200] or 'logement'
        slug, n = base, 1
        while Article.objects.filter(partenaire=partenaire, slug=slug).exists():
            n += 1
            slug = f'{base}-{n}'[:220]
        categorie = categories_correspondantes(partenaire.type_partenaire).first()

        article = Article.objects.create(
            partenaire=partenaire, categorie=categorie, nom=nom, slug=slug,
            type=Article.Type.LOGEMENT, prix=prix, description=description, est_actif=est_actif)
        return Logement.objects.create(
            article=article, localisation=Point(lng, lat, srid=4326) if lat is not None else None,
            modifie_par_role=self.context['acteur_role'], modifie_par_nom=self.context['acteur_nom'],
            **validated_data)

    def update(self, inst, validated_data):
        from django.contrib.gis.geos import Point

        article_champs = {k: validated_data.pop(k) for k in
                          ('nom', 'description', 'prix', 'est_actif') if k in validated_data}
        if article_champs:
            for k, v in article_champs.items():
                setattr(inst.article, k, v)
            inst.article.save(update_fields=list(article_champs) + ['updated_at'])

        if 'latitude' in validated_data or 'longitude' in validated_data:
            lat = validated_data.pop('latitude', None)
            lng = validated_data.pop('longitude', None)
            inst.localisation = Point(lng, lat, srid=4326) if lat is not None else None

        validated_data['modifie_par_role'] = self.context['acteur_role']
        validated_data['modifie_par_nom'] = self.context['acteur_nom']
        for k, v in validated_data.items():
            setattr(inst, k, v)
        inst.save()
        return inst
