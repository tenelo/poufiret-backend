"""Serializers du bloc administration (G5).

Jusqu'ici cette app construisait ses réponses à la main (dicts). Premiers
serializers DRF du module : lecture seule, dédiés à la supervision admin
(demandes d'intervention, liste plate des partenaires).
"""
from rest_framework import serializers

from apps.messaging.models import DemandeIntervention
from apps.users.models import ProfilPartenaire, SessionAppareil


class InterventionAdminSerializer(serializers.ModelSerializer):
    """Vue de supervision (lecture seule) d'une demande d'intervention,
    tous artisans confondus — réservée à l'admin (ADroitDe('voir_interventions')).
    """
    statut_libelle = serializers.CharField(source='get_statut_display', read_only=True)
    urgence_libelle = serializers.CharField(source='get_urgence_display', read_only=True)

    client_telephone = serializers.CharField(source='user.telephone', read_only=True)
    client_nom = serializers.SerializerMethodField()

    artisan_id = serializers.IntegerField(source='artisan.id', read_only=True)
    artisan_nom = serializers.CharField(source='artisan.nom_commerce', read_only=True)
    artisan_type = serializers.CharField(source='artisan.type_partenaire', read_only=True)

    class Meta:
        model = DemandeIntervention
        fields = [
            'id', 'numero', 'statut', 'statut_libelle',
            'type_intervention', 'type_libre', 'description',
            'urgence', 'urgence_libelle',
            'client_telephone', 'client_nom',
            'artisan_id', 'artisan_nom', 'artisan_type',
            'adresse_snapshot', 'latitude', 'longitude',
            'created_at', 'acceptee_le', 'terminee_le',
        ]
        read_only_fields = fields

    def get_client_nom(self, obj):
        return obj.user.get_full_name() or obj.user.username or obj.user.telephone


class PartenaireListeAdminSerializer(serializers.ModelSerializer):
    """Ligne de la liste plate admin des partenaires (une ligne par
    partenaire) — réservée à l'admin (ADroitDe('voir_indicateurs')), même
    capacité que le tableau de bord agrégé IndicateursPartenairesView.
    """
    type_partenaire_libelle = serializers.CharField(
        source='get_type_partenaire_display', read_only=True)
    statut_libelle = serializers.CharField(source='get_statut_display', read_only=True)
    categories = serializers.SerializerMethodField()
    departement_nom = serializers.CharField(
        source='departement.nom', read_only=True, default='')
    telephone_compte = serializers.CharField(source='user.telephone', read_only=True)
    plan_libelle = serializers.CharField(source='plan.libelle', read_only=True, default='')

    class Meta:
        model = ProfilPartenaire
        fields = [
            'id', 'nom_commerce',
            'type_partenaire', 'type_partenaire_libelle',
            'categories',
            'ville', 'quartier', 'departement_nom',
            'telephone_compte', 'telephone_pro', 'whatsapp',
            'statut', 'statut_libelle', 'est_visible', 'badge_certifie', 'est_faveur',
            'plan_libelle', 'abonnement_fin', 'nb_vues', 'created_at',
        ]
        read_only_fields = fields

    def get_categories(self, obj):
        return [lien.categorie.nom for lien in obj.liens_categories.all()]


class ConnexionAdminSerializer(serializers.ModelSerializer):
    """Une ligne SessionAppareil = une connexion — vue de supervision des
    connexions des ADMINS uniquement (le filtre user__is_staff=True vit
    dans la vue, pas ici) — réservée à ADroitDe('lire_journal'), même
    capacité que le journal d'audit.
    """
    utilisateur_id = serializers.IntegerField(source='user.id', read_only=True)
    telephone = serializers.CharField(source='user.telephone', read_only=True)
    nom = serializers.SerializerMethodField()
    is_superuser = serializers.BooleanField(source='user.is_superuser', read_only=True)
    date_connexion = serializers.DateTimeField(source='cree_le', read_only=True)
    plateforme_libelle = serializers.CharField(
        source='get_plateforme_display', read_only=True)

    class Meta:
        model = SessionAppareil
        fields = [
            'id', 'utilisateur_id', 'telephone', 'nom', 'is_superuser',
            'date_connexion', 'adresse_ip', 'plateforme', 'plateforme_libelle',
            'appareil_nom', 'est_active', 'derniere_activite_le',
        ]
        read_only_fields = fields

    def get_nom(self, obj):
        return obj.user.get_full_name() or obj.user.username or obj.user.telephone
