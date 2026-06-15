"""Serializers messaging — bloc C : DemandeIntervention."""
from rest_framework import serializers
from .models import DemandeIntervention, DemandeInterventionPhoto


class DemandeInterventionPhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = DemandeInterventionPhoto
        fields = ['id', 'demande', 'image', 'legende', 'ordre', 'created_at']
        read_only_fields = ['created_at']


class DemandeInterventionSerializer(serializers.ModelSerializer):
    photos = DemandeInterventionPhotoSerializer(many=True, read_only=True)
    client_nom = serializers.SerializerMethodField()
    artisan_nom = serializers.CharField(source='artisan.nom_commerce', read_only=True)

    class Meta:
        model = DemandeIntervention
        fields = ['id', 'numero', 'user', 'client_nom', 'artisan', 'artisan_nom',
                  'type_intervention', 'type_libre', 'description', 'urgence',
                  'adresse', 'adresse_snapshot', 'description_acces',
                  'disponibilite_preferee', 'statut', 'date_proposee', 'prix_propose',
                  'raison_refus', 'conversation', 'photos', 'created_at']
        read_only_fields = ['numero', 'user', 'statut', 'date_proposee',
                            'prix_propose', 'raison_refus', 'conversation']

    def get_client_nom(self, obj):
        return obj.user.get_full_name() or obj.user.username or obj.user.telephone
