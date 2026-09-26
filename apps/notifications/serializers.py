"""Serializers des notifications in-app admin.

Réutilise apps.moderation.models.Notification (modèle générique déjà
existant, non dupliqué) — voir apps.publicites.services._notifier_admins_pub
pour l'émission (soumission de pub, paiement confirmé).
"""
from rest_framework import serializers

from apps.moderation.models import Notification


class NotificationAdminSerializer(serializers.ModelSerializer):
    """id, type, titre, message, lue, cree_le, publicite_id, statut_publicite,
    commande_id, groupe — contrat exact demandé côté Angular. Tous les champs
    de deep-linking sont lus depuis `data` (JSONField) et valent None quand
    ils ne concernent pas le type de notification (pub vs commande) —
    ajout uniquement, rien retiré des champs pub existants."""
    message = serializers.CharField(source='contenu', read_only=True)
    lue = serializers.BooleanField(source='lu', read_only=True)
    cree_le = serializers.DateTimeField(source='created_at', read_only=True)
    publicite_id = serializers.SerializerMethodField()
    statut_publicite = serializers.SerializerMethodField()
    commande_id = serializers.SerializerMethodField()
    groupe = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ['id', 'type', 'titre', 'message', 'lue', 'cree_le',
                  'publicite_id', 'statut_publicite', 'commande_id', 'groupe']

    def get_publicite_id(self, obj):
        return obj.data.get('publicite_id')

    def get_statut_publicite(self, obj):
        return obj.data.get('statut_publicite')

    def get_commande_id(self, obj):
        return obj.data.get('commande_id')

    def get_groupe(self, obj):
        return obj.data.get('groupe')
