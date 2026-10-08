"""Sérialiseurs d'écriture des biens en location (Article + fiche, une
seule ressource) : logements (M1) et véhicules (V1). La lecture passe par
apps.locations.services.logement_dict / vehicule_dict, pas par ces
sérialiseurs (évite de mélanger champs écrits/dérivés)."""
from decimal import Decimal

from rest_framework import serializers

from apps.catalog.models import Article, Logement, Vehicule
from apps.geo.coherence import verifier_coherence
from apps.geo.models import Localite, Quartier

from .services import EQUIPEMENTS_REFERENTIEL, EQUIPEMENTS_VEHICULE_LIBELLES, valider_equipements


class _BienGestionSerializer(serializers.Serializer):
    """Base commune : champs portés par l'Article (nom, description, prix,
    est_actif) + localisation propre au bien (cohérence apps.geo).
    context requis : partenaire, acteur_role, acteur_nom.
    Sous-classes : modele_fiche (fiche 1-1), article_type, slug_defaut,
    champs_creation (valeurs imposées à la création de la fiche)."""
    modele_fiche = None
    article_type = None
    slug_defaut = 'bien'
    champs_creation = {}

    nom = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True)
    prix = serializers.DecimalField(max_digits=12, decimal_places=0)
    est_actif = serializers.BooleanField(required=False)

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
        from django.contrib.gis.geos import Point
        from django.utils.text import slugify

        from apps.catalog.correspondances import categories_correspondantes

        partenaire = self.context['partenaire']
        nom = validated_data.pop('nom')
        prix = validated_data.pop('prix')
        description = validated_data.pop('description', '')
        est_actif = validated_data.pop('est_actif', True)
        lat = validated_data.pop('latitude', None)
        lng = validated_data.pop('longitude', None)

        base = slugify(nom)[:200] or self.slug_defaut
        slug, n = base, 1
        while Article.objects.filter(partenaire=partenaire, slug=slug).exists():
            n += 1
            slug = f'{base}-{n}'[:220]
        categorie = categories_correspondantes(partenaire.type_partenaire).first()

        article = Article.objects.create(
            partenaire=partenaire, categorie=categorie, nom=nom, slug=slug,
            type=self.article_type, prix=prix, description=description, est_actif=est_actif)
        return self.modele_fiche.objects.create(
            article=article, localisation=Point(lng, lat, srid=4326) if lat is not None else None,
            modifie_par_role=self.context['acteur_role'], modifie_par_nom=self.context['acteur_nom'],
            **self.champs_creation, **validated_data)

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


class LogementGestionSerializer(_BienGestionSerializer):
    modele_fiche = Logement
    article_type = Article.Type.LOGEMENT
    slug_defaut = 'logement'

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

    def validate_equipements(self, valeur):
        normalises = valider_equipements(valeur)
        if normalises is None:
            raise serializers.ValidationError(
                f'Valeurs attendues parmi : {", ".join(EQUIPEMENTS_REFERENTIEL)}.')
        return normalises


class VehiculeGestionSerializer(_BienGestionSerializer):
    """Prix de l'Article = prix/jour sans chauffeur. Réutilise les champs
    existants de catalog.Vehicule : places (nb_places), boite_vitesse
    (boite), carburant."""
    modele_fiche = Vehicule
    article_type = Article.Type.VEHICULE
    slug_defaut = 'vehicule'
    champs_creation = {'mode': Vehicule.Mode.LOCATION}

    categorie_vehicule = serializers.ChoiceField(choices=Vehicule.CategorieVehicule.choices)
    marque = serializers.CharField(max_length=50)
    modele = serializers.CharField(max_length=100)
    annee = serializers.IntegerField(required=False, allow_null=True, min_value=1900, max_value=2100)
    couleur = serializers.CharField(max_length=50, required=False, allow_blank=True)
    nb_places = serializers.IntegerField(source='places', required=False, allow_null=True, min_value=1)
    boite = serializers.ChoiceField(
        source='boite_vitesse', choices=Vehicule.BoiteVitesse.choices, required=False, allow_blank=True)
    carburant = serializers.ChoiceField(
        choices=Vehicule.Carburant.choices, required=False, allow_blank=True)
    climatisation = serializers.BooleanField(required=False)
    equipements = serializers.ListField(required=False)
    chauffeur_disponible = serializers.BooleanField(required=False)
    chauffeur_obligatoire = serializers.BooleanField(required=False)
    prix_jour_avec_chauffeur = serializers.DecimalField(
        max_digits=12, decimal_places=0, required=False, allow_null=True, min_value=Decimal(0))
    caution = serializers.DecimalField(
        max_digits=12, decimal_places=0, required=False, allow_null=True, min_value=Decimal(0))
    km_inclus_par_jour = serializers.IntegerField(required=False, min_value=0)
    prix_km_supplementaire = serializers.DecimalField(
        max_digits=12, decimal_places=0, required=False, allow_null=True, min_value=Decimal(0))
    carburant_inclus = serializers.BooleanField(required=False)
    duree_min_jours = serializers.IntegerField(required=False, min_value=1)
    zone_circulation = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate_equipements(self, valeur):
        normalises = valider_equipements(valeur, list(EQUIPEMENTS_VEHICULE_LIBELLES))
        if normalises is None:
            raise serializers.ValidationError(
                f'Valeurs attendues parmi : {", ".join(EQUIPEMENTS_VEHICULE_LIBELLES)}.')
        return normalises

    def validate(self, attrs):
        attrs = super().validate(attrs)
        inst = self.instance

        def valeur(champ, defaut):
            return attrs[champ] if champ in attrs else (getattr(inst, champ) if inst else defaut)

        disponible = valeur('chauffeur_disponible', False)
        if valeur('chauffeur_obligatoire', False) and not disponible:
            raise serializers.ValidationError({'chauffeur_obligatoire': [
                'Un chauffeur obligatoire suppose chauffeur_disponible=true.']})
        if disponible and valeur('prix_jour_avec_chauffeur', None) is None:
            raise serializers.ValidationError({'prix_jour_avec_chauffeur': [
                'Requis lorsque le chauffeur est disponible.']})
        return attrs
