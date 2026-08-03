from rest_framework import serializers

from .models import FormulePublicite, ImagePublicite, Publicite


class FormulePubliciteSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormulePublicite
        fields = [
            'id', 'nom', 'prix', 'priorite', 'duree_jours', 'passages_par_jour',
            'duree_affichage_secondes', 'quota_partenaires', 'acces_heures_affluence',
            'types_affichage', 'nb_images_max', 'video_autorisee',
            'duree_video_max_secondes', 'cible_pourcentage_actifs',
        ]


class ImagePubliciteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImagePublicite
        fields = ['id', 'image', 'ordre']


class PubliciteListSerializer(serializers.ModelSerializer):
    """Diffusion publique : carrousel, page publicités."""
    partenaire_id = serializers.IntegerField(read_only=True)
    duree_affichage_secondes = serializers.IntegerField(
        source='formule.duree_affichage_secondes', read_only=True,
    )
    priorite = serializers.IntegerField(source='formule.priorite', read_only=True)

    class Meta:
        model = Publicite
        fields = ['id', 'titre', 'image_couverture', 'partenaire_id',
                  'duree_affichage_secondes', 'priorite']


class PubliciteDetailSerializer(serializers.ModelSerializer):
    images = ImagePubliciteSerializer(many=True, read_only=True)
    partenaire_id = serializers.IntegerField(read_only=True)
    nom_partenaire = serializers.CharField(source='partenaire.nom_commerce', read_only=True)

    portee_effective = serializers.CharField(read_only=True)
    class Meta:
        model = Publicite
        fields = ['id', 'titre', 'description', 'image_couverture', 'video',
                  'images', 'partenaire_id', 'nom_partenaire',
                  'portee', 'portee_effective']


class PubliciteCreationSerializer(serializers.ModelSerializer):
    """Création par le partenaire (parcours 'faire une publicité')."""

    class Meta:
        model = Publicite
        fields = ['id', 'formule', 'titre', 'description', 'image_couverture',
                  'video', 'portee', 'statut']
        read_only_fields = ['statut']

    def validate(self, donnees):
        formule = donnees.get('formule')
        if formule and not formule.est_active:
            raise serializers.ValidationError('Cette formule n\'est plus disponible.')
        if donnees.get('video') and formule and not formule.video_autorisee:
            raise serializers.ValidationError('Votre formule n\'autorise pas la vidéo.')
        portee = donnees.get('portee')
        if portee:
            from apps.users.models import Portee
            requete = self.context.get('request')
            profil = getattr(getattr(requete, 'user', None),
                             'profil_partenaire', None)
            portee_forfait = getattr(profil, 'portee', Portee.DEPARTEMENT)
            if Portee.rang(portee) < Portee.rang(portee_forfait):
                raise serializers.ValidationError({
                    'portee': (
                        'La portée choisie est déjà couverte par votre '
                        'forfait. Choisissez une portée supérieure ou '
                        'laissez celle du forfait.'
                    )
                })
        return donnees
