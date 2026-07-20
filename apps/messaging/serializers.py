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
    client_telephone = serializers.CharField(source='client.telephone', read_only=True)
    partenaire_telephone = serializers.SerializerMethodField()
    artisan_nom = serializers.CharField(source='artisan.nom_commerce', read_only=True)

    class Meta:
        model = DemandeIntervention
        fields = ['id', 'numero', 'user', 'client_nom', 'artisan', 'artisan_nom',
                  'client_telephone', 'artisan_telephone',
                  'type_intervention', 'type_libre', 'description', 'urgence',
                  'latitude', 'longitude',
                  'adresse', 'adresse_snapshot', 'description_acces',
                  'disponibilite_preferee', 'statut', 'date_proposee', 'prix_propose',
                  'raison_refus', 'conversation', 'photos', 'created_at']
        read_only_fields = ['numero', 'user', 'statut', 'date_proposee',
                            'prix_propose', 'raison_refus', 'conversation']

    def get_partenaire_telephone(self, obj):
        return obj.partenaire.telephone_pro or obj.partenaire.user.telephone

    def get_client_nom(self, obj):
        return obj.user.get_full_name() or obj.user.username or obj.user.telephone


from .models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    expediteur_nom = serializers.SerializerMethodField()
    class Meta:
        model = Message
        fields = ['id', 'conversation', 'expediteur', 'expediteur_nom', 'type',
                  'contenu', 'media_url', 'statut', 'created_at']
        read_only_fields = ['expediteur', 'statut']
    def get_expediteur_nom(self, obj):
        if not obj.expediteur: return 'Système'
        return obj.expediteur.get_full_name() or obj.expediteur.username or obj.expediteur.telephone


class ConversationSerializer(serializers.ModelSerializer):
    partenaire_nom = serializers.CharField(source='partenaire.nom_commerce', read_only=True)
    client_nom = serializers.SerializerMethodField()
    client_telephone = serializers.CharField(source='client.telephone', read_only=True)
    partenaire_telephone = serializers.SerializerMethodField()
    dernier_message = serializers.SerializerMethodField()
    class Meta:
        model = Conversation
        fields = ['id', 'client', 'client_nom', 'partenaire', 'partenaire_nom',
                  'article', 'client_telephone', 'partenaire_telephone',
                  'derniere_activite', 'est_archivee', 'dernier_message', 'created_at']
        read_only_fields = ['client']
    def get_partenaire_telephone(self, obj):
        return obj.partenaire.telephone_pro or obj.partenaire.user.telephone

    def get_client_nom(self, obj):
        return obj.client.get_full_name() or obj.client.username or obj.client.telephone
    def get_dernier_message(self, obj):
        m = obj.messages.order_by('-created_at').first()
        return {'contenu': m.contenu, 'created_at': m.created_at.isoformat()} if m else None
