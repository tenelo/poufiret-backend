from rest_framework import serializers

from .models import Departement, Quartier


class DepartementSerializer(serializers.ModelSerializer):
    """Département avec sa région et son district déduits.

    C'est le seul niveau choisi par l'utilisateur ; region et district
    sont renvoyes pour affichage et filtrage cote client si besoin.
    """
    region = serializers.CharField(source='region.nom', read_only=True)
    district = serializers.CharField(
        source='region.district.nom', read_only=True)

    class Meta:
        model = Departement
        fields = ['id', 'nom', 'region', 'district']


class QuartierSerializer(serializers.ModelSerializer):
    """Quartier d'un departement, pour l'autocompletion en livraison."""

    class Meta:
        model = Quartier
        fields = ['id', 'nom']
