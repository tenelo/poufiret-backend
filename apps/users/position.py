"""Position GPS d'un partenaire : validation, avertissement hors Côte d'Ivoire,
écriture avec traçabilité. Partagé par le partenaire (MonProfilPartenaire),
la création admin et la route admin de position."""
from django.contrib.gis.geos import Point
from django.utils import timezone
from rest_framework import serializers

CI_LAT = (4.0, 11.0)
CI_LNG = (-8.8, -2.2)
MSG_PAIRE = 'latitude et longitude doivent être fournis ensemble (ou null pour les deux, pour effacer).'


class PositionSerializer(serializers.Serializer):
    latitude = serializers.FloatField(required=False, allow_null=True, min_value=-90, max_value=90)
    longitude = serializers.FloatField(required=False, allow_null=True, min_value=-180, max_value=180)

    def validate(self, attrs):
        verifier_paire(attrs)
        return attrs


def verifier_paire(attrs):
    """Les deux valeurs ensemble (nulles ou non) ; aucune si absentes."""
    if 'latitude' not in attrs and 'longitude' not in attrs:
        return
    if 'latitude' not in attrs or 'longitude' not in attrs or \
            (attrs['latitude'] is None) != (attrs['longitude'] is None):
        raise serializers.ValidationError({'latitude': [MSG_PAIRE], 'longitude': [MSG_PAIRE]})


def avertissement_position(lat, lng):
    if lat is None or lng is None:
        return None
    if CI_LAT[0] <= lat <= CI_LAT[1] and CI_LNG[0] <= lng <= CI_LNG[1]:
        return None
    return "Position hors de Côte d'Ivoire : vérifiez les coordonnées."


def appliquer_position(profil, lat, lng, role):
    """Écrit (ou efface si lat/lng nuls) la position et sa traçabilité.
    Retourne l'avertissement éventuel."""
    profil.localisation = None if lat is None else Point(lng, lat, srid=4326)
    profil.position_modifiee_le = timezone.now()
    profil.position_modifiee_par_role = role
    profil.save(update_fields=['localisation', 'position_modifiee_le',
                               'position_modifiee_par_role', 'updated_at'])
    return avertissement_position(lat, lng)


def position_dict(profil, avertissement=None):
    loc = profil.localisation
    return {
        'latitude': loc.y if loc else None,
        'longitude': loc.x if loc else None,
        'position_modifiee_le': profil.position_modifiee_le,
        'position_modifiee_par_role': profil.position_modifiee_par_role or None,
        'avertissement_position': avertissement,
    }


def texte_position(profil):
    loc = profil.localisation
    return f'{loc.y:.6f},{loc.x:.6f}' if loc else 'aucune'
