"""Serializers des notifications in-app admin.

Réutilise apps.moderation.models.Notification (modèle générique déjà
existant, non dupliqué) — voir apps.publicites.services._notifier_admins_pub
pour l'émission (soumission de pub, paiement confirmé).
"""
from rest_framework import serializers

from apps.moderation.models import Notification


class NotificationAdminSerializer(serializers.ModelSerializer):
    """id, type, titre, message, lue, cree_le, publicite_id, statut_publicite
    — contrat exact demandé côté Angular. `publicite_id`/`statut_publicite`
    sont lus depuis `data` (JSONField de deep-linking), absents (None) pour
    un futur type de notification qui ne concernerait pas une pub."""
    message = serializers.CharField(source='contenu', read_only=True)
    lue = serializers.BooleanField(source='lu', read_only=True)
    cree_le = serializers.DateTimeField(source='created_at', read_only=True)
    publicite_id = serializers.SerializerMethodField()
    statut_publicite = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ['id', 'type', 'titre', 'message', 'lue', 'cree_le',
                  'publicite_id', 'statut_publicite']

    def get_publicite_id(self, obj):
        return obj.data.get('publicite_id')

    def get_statut_publicite(self, obj):
        return obj.data.get('statut_publicite')
