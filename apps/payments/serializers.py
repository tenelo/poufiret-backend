"""Serializers Paiement (Module 5)."""
from rest_framework import serializers
from .models import Paiement


class PaiementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Paiement
        fields = ['id', 'user', 'partenaire', 'type_objet', 'objet_id', 'montant',
                  'mode', 'statut', 'reference_externe', 'note', 'valide_par',
                  'valide_le', 'cree_le', 'modifie_le']
        read_only_fields = ['user', 'statut', 'valide_par', 'valide_le']
