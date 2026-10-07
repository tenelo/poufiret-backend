"""Sérialiseurs des demandes de visite/réservation."""
from rest_framework import serializers

from apps.catalog.models import Article

from .models import DemandeReservation, HistoriqueDemande, NoteAdminDemande
from .services import visite_eligible


class HistoriqueDemandeSerializer(serializers.ModelSerializer):
    acteur_nom = serializers.SerializerMethodField()

    class Meta:
        model = HistoriqueDemande
        fields = ['id', 'statut', 'acteur_nom', 'acteur_role', 'commentaire', 'cree_le']

    def get_acteur_nom(self, obj):
        if not obj.acteur_id:
            return ''
        return obj.acteur.get_full_name() or obj.acteur.username or obj.acteur.telephone


class NoteAdminDemandeSerializer(serializers.ModelSerializer):
    auteur_nom = serializers.SerializerMethodField()

    class Meta:
        model = NoteAdminDemande
        fields = ['id', 'auteur_nom', 'texte', 'cree_le']

    def get_auteur_nom(self, obj):
        if not obj.auteur_id:
            return ''
        return obj.auteur.get_full_name() or obj.auteur.username or obj.auteur.telephone


class DemandeSerializer(serializers.ModelSerializer):
    """Vue client/loueur : jamais les notes internes admin."""
    statut_libelle = serializers.CharField(source='get_statut_display', read_only=True)
    nature_libelle = serializers.CharField(source='get_nature_display', read_only=True)
    objet_id = serializers.IntegerField(read_only=True)
    objet_nom = serializers.CharField(source='objet.nom', read_only=True)
    objet_type = serializers.CharField(source='objet.type', read_only=True)
    partenaire_nom = serializers.CharField(source='partenaire.nom_commerce', read_only=True)
    client_nom = serializers.SerializerMethodField()
    historique = HistoriqueDemandeSerializer(many=True, read_only=True)

    class Meta:
        model = DemandeReservation
        fields = ['id', 'numero', 'nature', 'nature_libelle', 'objet_id', 'objet_nom', 'objet_type',
                  'partenaire', 'partenaire_nom', 'client', 'client_nom',
                  'date_souhaitee', 'date_debut', 'date_fin', 'nb_personnes', 'message',
                  'telephone_contact', 'statut', 'statut_libelle', 'raison_refus',
                  'created_at', 'confirmee_le', 'terminee_le', 'historique']
        read_only_fields = fields

    def get_client_nom(self, obj):
        return obj.client.get_full_name() or obj.client.username or obj.client.telephone


class DemandeAdminListSerializer(DemandeSerializer):
    groupe = serializers.SerializerMethodField()

    class Meta(DemandeSerializer.Meta):
        fields = DemandeSerializer.Meta.fields + ['groupe']
        read_only_fields = fields

    def get_groupe(self, obj):
        from .services import GROUPE_PAR_STATUT
        return GROUPE_PAR_STATUT.get(obj.statut, '')


class DemandeAdminDetailSerializer(DemandeAdminListSerializer):
    notes_admin = NoteAdminDemandeSerializer(many=True, read_only=True)
    transitions_possibles = serializers.SerializerMethodField()

    class Meta(DemandeAdminListSerializer.Meta):
        fields = DemandeAdminListSerializer.Meta.fields + ['notes_admin', 'transitions_possibles']
        read_only_fields = fields

    def get_transitions_possibles(self, obj):
        from .services import transitions_possibles
        return transitions_possibles(obj.statut, 'admin')


class DemandeLoueurSerializer(DemandeSerializer):
    """Vue loueur (mon-espace/) : comme DemandeSerializer, + transitions_possibles
    (règles de commentaire obligatoire du périmètre loueur)."""
    transitions_possibles = serializers.SerializerMethodField()

    class Meta(DemandeSerializer.Meta):
        fields = DemandeSerializer.Meta.fields + ['transitions_possibles']
        read_only_fields = fields

    def get_transitions_possibles(self, obj):
        from .services import transitions_possibles
        return transitions_possibles(obj.statut, 'loueur')


class CreerDemandeSerializer(serializers.Serializer):
    """Entrée de POST /reservations/ (client)."""
    objet_id = serializers.PrimaryKeyRelatedField(
        source='objet', queryset=Article.objects.filter(est_actif=True))
    nature = serializers.ChoiceField(choices=DemandeReservation.Nature.choices)
    date_souhaitee = serializers.DateTimeField(required=False, allow_null=True)
    date_debut = serializers.DateField(required=False, allow_null=True)
    date_fin = serializers.DateField(required=False, allow_null=True)
    nb_personnes = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    message = serializers.CharField(required=False, allow_blank=True)
    telephone_contact = serializers.CharField(required=False, allow_blank=True, max_length=20)

    def validate(self, attrs):
        if attrs['nature'] == DemandeReservation.Nature.VISITE:
            if not attrs.get('date_souhaitee'):
                raise serializers.ValidationError({'date_souhaitee': ['Requise pour une visite.']})
            if not visite_eligible(attrs['objet']):
                raise serializers.ValidationError(
                    {'objet_id': ["Ce logement n'est pas disponible pour une visite."]})
        else:
            if not attrs.get('date_debut') or not attrs.get('date_fin'):
                raise serializers.ValidationError({
                    'date_debut': ['date_debut et date_fin sont requises pour une réservation.'],
                    'date_fin': ['date_debut et date_fin sont requises pour une réservation.']})
            if attrs['date_fin'] <= attrs['date_debut']:
                raise serializers.ValidationError({'date_fin': ['Doit être postérieure à date_debut.']})
        return attrs
